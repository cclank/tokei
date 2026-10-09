mod collector;
mod panel;
mod power;
mod store;

use std::sync::Mutex;

use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, WindowEvent, Wry};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt};

/// 前端调采集脚本：`args` 如 `["--json"]`、`["--dashboard", "--period", "7d"]`。
#[tauri::command]
async fn run_collector(app: AppHandle, args: Vec<String>) -> Result<String, String> {
    tauri::async_runtime::spawn_blocking(move || collector::run(&app, &args, &store::secret_environment()))
        .await
        .map_err(|err| err.to_string())?
}

/// 设置页「诊断」：不管成败都交回退出状态和两路输出（Mac 版 runScriptRaw，超时 8 秒）。
#[tauri::command]
async fn run_collector_raw(app: AppHandle, args: Vec<String>) -> Result<collector::RawOutput, String> {
    tauri::async_runtime::spawn_blocking(move || {
        collector::run_raw(&app, &args, &store::secret_environment(), std::time::Duration::from_secs(8))
    })
    .await
    .map_err(|err| err.to_string())?
}

/// 托盘悬停提示，前端每次刷新后写一份当前额度摘要。
#[tauri::command]
fn set_tray_tooltip(app: AppHandle, text: String) {
    if let Some(tray) = app.tray_by_id("main") {
        let _ = tray.set_tooltip(Some(text));
    }
}

/// 托盘右键菜单的几项；文字由前端按界面语言推过来（`set_tray_menu_labels`）。
struct TrayMenu {
    refresh: MenuItem<Wry>,
    settings: MenuItem<Wry>,
    autostart: CheckMenuItem<Wry>,
    quit: MenuItem<Wry>,
}

/// 顺带按实际状态重设「登录时启动」的勾（设置页里改了开关也会调这里）。
#[tauri::command]
fn set_tray_menu_labels(
    app: AppHandle,
    menu: tauri::State<'_, TrayMenu>,
    refresh: String,
    settings: String,
    autostart: String,
    quit: String,
) {
    let _ = menu.refresh.set_text(refresh);
    let _ = menu.settings.set_text(settings);
    let _ = menu.autostart.set_text(autostart);
    let _ = menu.autostart.set_checked(app.autolaunch().is_enabled().unwrap_or(false));
    let _ = menu.quit.set_text(quit);
}

#[tauri::command]
fn hide_panel(app: AppHandle) {
    panel::hide(&app);
}

#[tauri::command]
fn quit_app(app: AppHandle) {
    app.exit(0);
}

#[tauri::command]
fn set_keep_awake(state: tauri::State<'_, Mutex<power::KeepAwake>>, on: bool) -> bool {
    state.lock().map(|mut keep| keep.set(on)).unwrap_or(false)
}

#[tauri::command]
fn keep_awake_active(state: tauri::State<'_, Mutex<power::KeepAwake>>) -> bool {
    state.lock().map(|keep| keep.active()).unwrap_or(false)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        // 再打开一次 Tokei（开始菜单、桌面快捷方式）就直接唤出面板，而不是起第二个进程。
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            panel::show_near_tray(app, None);
        }))
        .plugin(tauri_plugin_autostart::init(MacosLauncher::LaunchAgent, Some(vec!["--autostart"])))
        .plugin(tauri_plugin_opener::init())
        .manage(Mutex::new(power::KeepAwake::default()))
        .manage(panel::PanelState::default())
        .invoke_handler(tauri::generate_handler![
            run_collector,
            run_collector_raw,
            set_tray_tooltip,
            set_tray_menu_labels,
            hide_panel,
            quit_app,
            set_keep_awake,
            keep_awake_active,
            store::read_tokei_file,
            store::write_tokei_file,
            store::read_tokei_config,
            store::update_tokei_config,
            store::has_secret,
            store::set_secret,
            store::delete_secret,
        ])
        .setup(|app| {
            #[cfg(target_os = "macos")]
            app.set_activation_policy(tauri::ActivationPolicy::Accessory);

            build_tray(app.handle())?;

            if let Some(window) = app.get_webview_window(panel::LABEL) {
                let handle = app.handle().clone();
                window.on_window_event(move |event| {
                    if let WindowEvent::Focused(false) = event {
                        panel::on_blur(&handle);
                    }
                });
            }
            // 手动启动（不是开机自启）时直接打开面板，让用户知道 Tokei 在托盘里。
            if !std::env::args().any(|arg| arg == "--autostart") {
                panel::show_near_tray(app.handle(), None);
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Tokei");
}

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    // 先用中文原文占位，前端起来后按界面语言换成译文。
    let refresh = MenuItem::with_id(app, "refresh", "刷新", true, None::<&str>)?;
    let settings = MenuItem::with_id(app, "settings", "设置", true, None::<&str>)?;
    let autostart_on = app.autolaunch().is_enabled().unwrap_or(false);
    let autostart = CheckMenuItem::with_id(app, "autostart", "登录时启动", true, autostart_on, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(app, &[&refresh, &settings, &autostart, &separator, &quit])?;
    app.manage(TrayMenu {
        refresh: refresh.clone(),
        settings: settings.clone(),
        autostart: autostart.clone(),
        quit: quit.clone(),
    });

    let icon = app.default_window_icon().cloned().expect("bundle icon");
    TrayIconBuilder::with_id("main")
        .icon(icon)
        .tooltip("Tokei")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(move |app, event| match event.id().as_ref() {
            "refresh" => {
                let _ = app.emit("tokei://refresh", ());
            }
            "settings" => {
                panel::show_near_tray(app, None);
                let _ = app.emit("tokei://open-settings", ());
            }
            "autostart" => {
                let launcher = app.autolaunch();
                let enabled = launcher.is_enabled().unwrap_or(false);
                let _ = if enabled { launcher.disable() } else { launcher.enable() };
                let _ = autostart.set_checked(launcher.is_enabled().unwrap_or(false));
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                rect,
                ..
            } = event
            {
                panel::toggle(tray.app_handle(), rect);
            }
        })
        .build(app)?;
    Ok(())
}
