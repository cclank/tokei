//! 主窗口采集一次，快捷面板订阅同一份状态。历史记录仍由主窗口写入。

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::sync::Mutex;
use tauri::{AppHandle, Emitter, WebviewWindow};

#[derive(Clone, Default, Serialize, Deserialize)]
pub struct UsageState {
    pub usage: Option<Value>,
    pub error: Option<String>,
    pub updated_at: Option<u64>,
    pub refreshing: bool,
}

#[derive(Clone, Default, Serialize)]
pub struct UsageSnapshot {
    pub revision: u64,
    pub state: UsageState,
}

#[derive(Default)]
pub struct SnapshotStore(Mutex<UsageSnapshot>);

impl SnapshotStore {
    fn read(&self) -> UsageSnapshot {
        self.0.lock().unwrap_or_else(|e| e.into_inner()).clone()
    }

    fn publish(&self, state: UsageState) -> UsageSnapshot {
        let mut current = self.0.lock().unwrap_or_else(|e| e.into_inner());
        current.revision += 1;
        current.state = state;
        current.clone()
    }
}

#[tauri::command]
pub fn get_usage_snapshot(store: tauri::State<'_, SnapshotStore>) -> UsageSnapshot {
    store.read()
}

#[tauri::command]
pub fn publish_usage_snapshot(
    app: AppHandle,
    window: WebviewWindow,
    store: tauri::State<'_, SnapshotStore>,
    snapshot: UsageState,
) -> Result<(), String> {
    if window.label() != crate::panel::LABEL {
        return Err("Only the main window can publish usage".into());
    }
    if snapshot
        .usage
        .as_ref()
        .is_some_and(|usage| !usage.is_object())
    {
        return Err("Usage must be a JSON object".into());
    }
    let latest = store.publish(snapshot);
    app.emit_to(crate::panel::QUICK_LABEL, "tokei://usage-state", latest)
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub fn request_usage_refresh(app: AppHandle) -> Result<(), String> {
    app.emit_to(crate::panel::LABEL, "tokei://refresh", ())
        .map_err(|e| e.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn shared_snapshot_preserves_last_usage_while_refreshing_or_failing() {
        let store = SnapshotStore::default();
        assert_eq!(store.read().revision, 0);
        let usage = serde_json::json!({ "codex": { "tokens": 12345 } });
        let first = store.publish(UsageState {
            usage: Some(usage.clone()),
            updated_at: Some(1234),
            ..Default::default()
        });
        let next = store.publish(UsageState {
            usage: Some(usage.clone()),
            updated_at: Some(1234),
            refreshing: true,
            ..Default::default()
        });
        let failed = store.publish(UsageState {
            usage: Some(usage.clone()),
            updated_at: Some(1234),
            error: Some("offline".into()),
            refreshing: false,
        });
        assert!(first.revision < next.revision && next.revision < failed.revision);
        assert_eq!(store.read().state.usage, Some(usage));
        assert_eq!(store.read().state.updated_at, Some(1234));
        assert!(!store.read().state.refreshing);
    }
}
