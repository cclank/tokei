//! 托盘弹出面板：挂在托盘图标旁边，失去焦点就收起。
//!
//! 位置用点托盘时拿到的图标矩形来算：任务栏在下面（Windows 默认）就弹到图标上方，
//! 在上面（macOS 菜单栏、或把任务栏拖到顶部）就弹到下方；水平方向以图标为中心，
//! 并夹在这块屏幕的工作区里。高度按屏幕比例，和 Mac 版一样不写死。

use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::{AppHandle, Emitter, Manager, PhysicalPosition, PhysicalSize, Rect, WebviewWindow};

pub const LABEL: &str = "panel";
/// 逻辑像素。两列卡片的宽度，与 Mac 版宽面板一致。
const WIDTH: f64 = 640.0;
/// 面板最多占屏幕工作区高度的比例（Mac 版 PanelPlacement.heightRatio）。
const HEIGHT_RATIO: f64 = 0.88;
const MIN_HEIGHT: f64 = 420.0;
const MARGIN: f64 = 8.0;

#[derive(Default)]
pub struct PanelState {
    inner: Mutex<Inner>,
}

#[derive(Default)]
struct Inner {
    /// 上次点托盘时图标的位置（物理像素）：从菜单、第二个实例唤出面板时沿用。
    tray: Option<(PhysicalPosition<f64>, PhysicalSize<f64>)>,
    /// 面板因失焦收起的时间。点托盘图标本身就会先让面板失焦，紧接着的那次点击
    /// 应当是「关掉」而不是「重新打开」。
    blurred_at: Option<Instant>,
}

fn window(app: &AppHandle) -> Option<WebviewWindow> {
    app.get_webview_window(LABEL)
}

pub fn toggle(app: &AppHandle, rect: Rect) {
    let Some(win) = window(app) else { return };
    let state = app.state::<PanelState>();
    let just_blurred = state
        .inner
        .lock()
        .ok()
        .and_then(|inner| inner.blurred_at)
        .is_some_and(|at| at.elapsed() < Duration::from_millis(300));
    if win.is_visible().unwrap_or(false) || just_blurred {
        hide(app);
        return;
    }
    show_near_tray(app, Some(rect));
}

pub fn show_near_tray(app: &AppHandle, rect: Option<Rect>) {
    let Some(win) = window(app) else { return };
    let state = app.state::<PanelState>();
    let scale = win.scale_factor().unwrap_or(1.0);
    let tray = rect
        .map(|r| (r.position.to_physical::<f64>(scale), r.size.to_physical::<f64>(scale)))
        .or_else(|| state.inner.lock().ok().and_then(|inner| inner.tray));
    if let Ok(mut inner) = state.inner.lock() {
        if tray.is_some() {
            inner.tray = tray;
        }
        inner.blurred_at = None;
    }
    place(&win, tray);
    let _ = win.show();
    let _ = win.set_focus();
    let _ = app.emit("tokei://panel-shown", ());
}

pub fn hide(app: &AppHandle) {
    if let Some(win) = window(app) {
        let _ = win.hide();
    }
}

pub fn on_blur(app: &AppHandle) {
    let Some(win) = window(app) else { return };
    if !win.is_visible().unwrap_or(false) {
        return;
    }
    if let Ok(mut inner) = app.state::<PanelState>().inner.lock() {
        inner.blurred_at = Some(Instant::now());
    }
    let _ = win.hide();
}

fn place(win: &WebviewWindow, tray: Option<(PhysicalPosition<f64>, PhysicalSize<f64>)>) {
    let monitor = tray
        .and_then(|(pos, size)| {
            win.monitor_from_point(pos.x + size.width / 2.0, pos.y + size.height / 2.0)
                .ok()
                .flatten()
        })
        .or_else(|| win.primary_monitor().ok().flatten());
    let Some(monitor) = monitor else { return };
    let scale = monitor.scale_factor();
    let work = monitor.work_area();
    let (wx, wy) = (work.position.x as f64, work.position.y as f64);
    let (ww, wh) = (work.size.width as f64, work.size.height as f64);
    let margin = MARGIN * scale;

    let width = (WIDTH * scale).min(ww - 2.0 * margin);
    let height = (wh * HEIGHT_RATIO).max(MIN_HEIGHT * scale).min(wh - 2.0 * margin);
    let _ = win.set_size(PhysicalSize::new(width.round() as u32, height.round() as u32));

    // 没有托盘位置（第一次从开始菜单打开）时，按 Windows 默认任务栏放在右下角。
    let (center_x, tray_top, tray_bottom) = match tray {
        Some((pos, size)) => (pos.x + size.width / 2.0, pos.y, pos.y + size.height),
        None => (wx + ww - width / 2.0 - margin, wy + wh, wy + wh),
    };
    let x = (center_x - width / 2.0).clamp(wx + margin, wx + ww - width - margin);
    let tray_below_middle = (tray_top + tray_bottom) / 2.0 > wy + wh / 2.0;
    let y = if tray_below_middle {
        (tray_top - height - margin).min(wy + wh - height - margin).max(wy + margin)
    } else {
        (tray_bottom + margin).min(wy + wh - height - margin)
    };
    let _ = win.set_position(PhysicalPosition::new(x.round() as i32, y.round() as i32));
}
