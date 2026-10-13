//! Windows authorization and launch reporting. No credentials are sent to a WebView.
use crate::{collector, panel, store};
use serde::Serialize;
use serde_json::{json, Map};
use std::process::{Child, Stdio};
use std::sync::Mutex;
use tauri::{AppHandle, Manager, WebviewWindow};

#[derive(Default)]
struct Launch {
    started: bool,
    child: Option<Child>,
}

#[derive(Default)]
pub struct ActivityState(Mutex<Launch>);

impl ActivityState {
    pub fn stop(&self) {
        stop_reporter(&mut self.0.lock().unwrap_or_else(|e| e.into_inner()));
    }
}

fn stop_reporter(launch: &mut Launch) {
    if let Some(mut child) = launch.child.take() {
        if matches!(child.try_wait(), Ok(None)) {
            let _ = child.kill();
        }
        let _ = child.wait();
    }
}

fn main_only(window: &WebviewWindow) -> Result<(), String> {
    if window.label() == panel::LABEL {
        Ok(())
    } else {
        Err("Privacy controls belong to the main window".into())
    }
}

fn save_activity(enabled: bool) -> Result<(), String> {
    let mut patch = Map::new();
    patch.insert("share_basic_activity".into(), json!(enabled));
    store::update_tokei_config(patch).map(|_| ())
}

#[tauri::command]
pub fn start_activity_reporter(
    app: AppHandle,
    window: WebviewWindow,
    state: tauri::State<'_, ActivityState>,
    enabled: bool,
) -> Result<(), String> {
    main_only(&window)?;
    let mut launch = state.0.lock().unwrap_or_else(|e| e.into_inner());
    if launch.started {
        return Ok(());
    }
    launch.started = true;
    let enabled = store::read_tokei_config()
        .get("share_basic_activity")
        .and_then(|value| value.as_bool())
        .unwrap_or(enabled);
    save_activity(enabled)?;
    if !enabled || !cfg!(windows) {
        return Ok(());
    }
    let directory = app
        .path()
        .app_local_data_dir()
        .map_err(|_| "Telemetry directory unavailable")?
        .join("Telemetry");
    #[cfg(debug_assertions)]
    let directory = match std::env::var_os("TOKEI_TEST_STATE_DIR") {
        Some(path) => std::path::PathBuf::from(path).join("Telemetry"),
        None => directory,
    };
    let mut command = collector::bridge_command(&app)?;
    command
        .arg("activity")
        .arg("--directory")
        .arg(directory)
        .arg("--version")
        .arg(app.package_info().version.to_string())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    launch.child = command.spawn().ok(); // A failure is never retried during this run.
    Ok(())
}

#[tauri::command]
pub fn set_activity_statistics(
    window: WebviewWindow,
    state: tauri::State<'_, ActivityState>,
    enabled: bool,
) -> Result<(), String> {
    main_only(&window)?;
    let mut launch = state.0.lock().unwrap_or_else(|e| e.into_inner());
    save_activity(enabled)?;
    if !enabled {
        stop_reporter(&mut launch);
    }
    // Re-enabling takes effect on the next launch, matching the Mac application.
    Ok(())
}

#[derive(Serialize)]
pub struct Authorization {
    status: String,
}

async fn authorization(
    app: AppHandle,
    window: WebviewWindow,
    mode: &'static str,
) -> Result<Authorization, String> {
    main_only(&window)?;
    tauri::async_runtime::spawn_blocking(move || {
        let raw = collector::run_bridge(&app, mode)?;
        let value: serde_json::Value =
            serde_json::from_str(&raw).map_err(|_| "Invalid authorization result")?;
        let status = value
            .get("status")
            .and_then(|v| v.as_str())
            .unwrap_or("unavailable");
        let status = match status {
            "authorized"
            | "authorization_required"
            | "expired"
            | "login_required"
            | "disabled"
            | "unsupported_platform"
            | "unsupported_format" => status,
            _ => "unavailable",
        };
        Ok(Authorization {
            status: status.into(),
        })
    })
    .await
    .map_err(|_| "Authorization helper stopped".to_string())?
}

#[tauri::command]
pub async fn grok_bot_authorization_status(
    app: AppHandle,
    window: WebviewWindow,
) -> Result<Authorization, String> {
    authorization(app, window, "grok-status").await
}

#[tauri::command]
pub async fn authorize_grok_bot(
    app: AppHandle,
    window: WebviewWindow,
) -> Result<Authorization, String> {
    authorization(app, window, "grok-authorize").await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read;
    use std::time::Duration;

    #[test]
    fn opt_out_terminates_the_reporting_process() {
        let mut child =
            std::process::Command::new(if cfg!(windows) { "python" } else { "python3" })
                .args(["-c", "import time\ntime.sleep(60)"])
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .spawn()
                .unwrap();
        let mut output = child.stdout.take().unwrap();
        let (send, receive) = std::sync::mpsc::channel();
        let reader = std::thread::spawn(move || {
            let _ = output.read_to_end(&mut Vec::new());
            let _ = send.send(());
        });
        let state = ActivityState(Mutex::new(Launch {
            started: true,
            child: Some(child),
        }));
        state.stop();
        assert!(
            receive.recv_timeout(Duration::from_secs(2)).is_ok(),
            "Reporter survived opt-out"
        );
        reader.join().unwrap();
    }
}
