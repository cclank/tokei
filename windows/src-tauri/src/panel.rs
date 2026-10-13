//! 常规主窗口和独立托盘快捷面板，各自保留对应的窗口行为。

use crate::{
    placement::{quick_placement, Bounds},
    store,
};
use serde::{Deserialize, Serialize};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, PhysicalSize, Rect};

// 沿用原窗口标签，保留现有 WebView 偏好和权限配置。
pub const LABEL: &str = "panel";
pub const QUICK_LABEL: &str = "quick";
const PREFS_FILE: &str = "windows-ui.json";

#[derive(Clone, Copy, Default, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TrayAction {
    #[default]
    Quick,
    Window,
}

#[derive(Default)]
pub struct SurfaceState {
    quick: Mutex<QuickState>,
    action: Mutex<TrayAction>,
}

#[derive(Default)]
struct QuickState {
    tray: Option<Bounds>,
    blurred_at: Option<Instant>,
}

impl SurfaceState {
    pub fn load() -> Self {
        let action = store::read_tokei_file(PREFS_FILE.into())
            .ok()
            .flatten()
            .and_then(|s| serde_json::from_str::<serde_json::Value>(&s).ok())
            .and_then(|v| v.get("tray_action").cloned())
            .and_then(|v| serde_json::from_value(v).ok())
            .unwrap_or_default();
        Self {
            action: Mutex::new(action),
            ..Default::default()
        }
    }
}

#[tauri::command]
pub fn get_tray_click_action(state: tauri::State<'_, SurfaceState>) -> TrayAction {
    *state.action.lock().unwrap_or_else(|e| e.into_inner())
}

#[tauri::command]
pub fn set_tray_click_action(
    app: AppHandle,
    state: tauri::State<'_, SurfaceState>,
    action: TrayAction,
) -> Result<TrayAction, String> {
    let mut selected = state.action.lock().unwrap_or_else(|e| e.into_inner());
    let mut prefs = match store::read_tokei_file(PREFS_FILE.into())? {
        Some(text) => serde_json::from_str::<serde_json::Map<String, serde_json::Value>>(&text)
            .map_err(|e| e.to_string())?,
        None => serde_json::Map::new(),
    };
    prefs.insert(
        "tray_action".into(),
        serde_json::to_value(action).map_err(|e| e.to_string())?,
    );
    store::write_tokei_file(
        PREFS_FILE.into(),
        serde_json::to_string_pretty(&prefs).map_err(|e| e.to_string())?,
    )?;
    *selected = action;
    hide_quick(&app);
    Ok(action)
}

pub fn tray_click(app: &AppHandle, rect: Rect) {
    match get_tray_click_action(app.state::<SurfaceState>()) {
        TrayAction::Window => show(app),
        TrayAction::Quick => toggle_quick(app, rect),
    }
}

pub fn show(app: &AppHandle) {
    hide_quick(app);
    let Some(window) = app.get_webview_window(LABEL) else {
        return;
    };
    let _ = window.show();
    if window.is_minimized().unwrap_or(false) {
        let _ = window.unminimize();
    }
    let _ = window.set_focus();
    let _ = app.emit_to(LABEL, "tokei://panel-shown", ());
}

#[tauri::command]
pub fn open_main_window(app: AppHandle, range: Option<String>) -> Result<(), String> {
    if range.as_deref().is_some_and(|range| {
        !["today", "yesterday", "week", "last_week", "month", "year"].contains(&range)
    }) {
        return Err("Unknown time range".into());
    }
    show(&app);
    app.emit_to(LABEL, "tokei://open-home", range)
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub fn hide_quick_panel(app: AppHandle) {
    hide_quick(&app);
}

#[tauri::command]
pub fn open_quick_panel(app: AppHandle) {
    show_quick(&app, None);
}

#[tauri::command]
pub fn quick_panel_visible(app: AppHandle) -> bool {
    app.get_webview_window(QUICK_LABEL)
        .is_some_and(|window| window.is_visible().unwrap_or(false))
}

pub fn hide_quick(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(QUICK_LABEL) {
        let _ = window.hide();
        let _ = app.emit_to(LABEL, "tokei://quick-visible", false);
    }
}

pub fn quick_blurred(app: &AppHandle) {
    if !quick_panel_visible(app.clone()) {
        return;
    }
    let state = app.state::<SurfaceState>();
    state
        .quick
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .blurred_at = Some(Instant::now());
    hide_quick(app);
}

fn toggle_quick(app: &AppHandle, rect: Rect) {
    let state = app.state::<SurfaceState>();
    let just_blurred = state
        .quick
        .lock()
        .unwrap_or_else(|e| e.into_inner())
        .blurred_at
        .is_some_and(|time| time.elapsed() < Duration::from_millis(300));
    if quick_panel_visible(app.clone()) || just_blurred {
        hide_quick(app);
        return;
    }
    show_quick(app, Some(rect));
}

pub fn show_quick(app: &AppHandle, rect: Option<Rect>) {
    let Some(window) = app.get_webview_window(QUICK_LABEL) else {
        return;
    };
    let state = app.state::<SurfaceState>();
    let mut quick = state.quick.lock().unwrap_or_else(|e| e.into_inner());
    if let Some(rect) = rect {
        let scale = window.scale_factor().unwrap_or(1.0);
        let position = rect.position.to_physical::<f64>(scale);
        let size = rect.size.to_physical::<f64>(scale);
        quick.tray = Some(Bounds {
            x: position.x,
            y: position.y,
            width: size.width,
            height: size.height,
        });
    }
    let tray = quick.tray;
    quick.blurred_at = None;
    drop(quick);
    let monitor = tray
        .and_then(|rect| {
            window
                .monitor_from_point(rect.x + rect.width / 2.0, rect.y + rect.height / 2.0)
                .ok()
                .flatten()
        })
        .or_else(|| window.primary_monitor().ok().flatten());
    if let Some(monitor) = monitor {
        let work = monitor.work_area();
        let place = quick_placement(
            Bounds {
                x: work.position.x as f64,
                y: work.position.y as f64,
                width: work.size.width as f64,
                height: work.size.height as f64,
            },
            monitor.scale_factor(),
            tray,
        );
        let _ = window.set_position(PhysicalPosition::new(place.x, place.y));
        let _ = window.set_size(PhysicalSize::new(place.width, place.height));
        let _ = window.set_position(PhysicalPosition::new(place.x, place.y));
    }
    let _ = window.show();
    let _ = window.set_focus();
    let _ = app.emit_to(LABEL, "tokei://quick-visible", true);
}

pub fn hide(app: &AppHandle) {
    if let Some(window) = app.get_webview_window(LABEL) {
        let _ = window.hide();
    }
}
