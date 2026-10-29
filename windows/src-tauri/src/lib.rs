mod collector;
mod doubaowork_quota;
mod doubaowork_webview;
mod panel;
mod placement;
mod power;
mod privacy;
mod snapshot;
mod store;

use std::sync::{
    atomic::{AtomicBool, Ordering},
    Mutex,
};

use tauri::menu::{CheckMenuItem, Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Emitter, Manager, WindowEvent, Wry};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt};

struct StartupWindow {
    manual: bool,
    shown: AtomicBool,
}

/// 前端调采集脚本：`args` 如 `["--json"]`、`["--dashboard", "--period", "7d"]`。
#[tauri::command]
async fn run_collector(
    app: AppHandle,
    window: tauri::WebviewWindow,
    args: Vec<String>,
) -> Result<String, String> {
    if window.label() != panel::LABEL {
        return Err("Usage collection belongs to the main window".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        let env = if args.iter().any(|arg| arg == "--local-only") {
            Vec::new()
        } else {
            store::secret_environment()
        };
        collector::run(&app, &args, &env)
    })
    .await
    .map_err(|err| err.to_string())?
}

/// 设置页「诊断」：不管成败都交回退出状态和两路输出（Mac 版 runScriptRaw，超时 8 秒）。
#[tauri::command]
async fn run_collector_raw(
    app: AppHandle,
    window: tauri::WebviewWindow,
    args: Vec<String>,
) -> Result<collector::RawOutput, String> {
    if window.label() != panel::LABEL {
        return Err("Diagnostics belong to the main window".into());
    }
    tauri::async_runtime::spawn_blocking(move || {
        collector::run_raw(
            &app,
            &args,
            &store::secret_environment(),
            std::time::Duration::from_secs(8),
        )
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
    open: MenuItem<Wry>,
    quick: MenuItem<Wry>,
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
    open: String,
    quick: String,
    refresh: String,
    settings: String,
    autostart: String,
    quit: String,
) {
    let _ = menu.open.set_text(open);
    let _ = menu.quick.set_text(quick);
    let _ = menu.refresh.set_text(refresh);
    let _ = menu.settings.set_text(settings);
    let _ = menu.autostart.set_text(autostart);
    let _ = menu
        .autostart
        .set_checked(app.autolaunch().is_enabled().unwrap_or(false));
    let _ = menu.quit.set_text(quit);
}

#[tauri::command]
fn quit_app(app: AppHandle) {
    app.state::<privacy::ActivityState>().stop();
    app.state::<doubaowork_webview::QuotaState>().stop();
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
        // 再打开一次快捷方式时恢复主窗口。
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            panel::show(app);
        }))
        .plugin(tauri_plugin_autostart::init(
            MacosLauncher::LaunchAgent,
            Some(vec!["--autostart"]),
        ))
        .plugin(tauri_plugin_opener::init())
        .manage(Mutex::new(power::KeepAwake::default()))
        .manage(panel::SurfaceState::load())
        .manage(snapshot::SnapshotStore::default())
        .manage(privacy::ActivityState::default())
        .manage(doubaowork_webview::QuotaState::default())
        .manage(StartupWindow {
            manual: !std::env::args().any(|arg| arg == "--autostart"),
            shown: AtomicBool::new(false),
        })
        .on_page_load(|webview, payload| {
            if webview.label() == panel::LABEL
                && payload.event() == tauri::webview::PageLoadEvent::Finished
            {
                let app = webview.app_handle();
                let startup = app.state::<StartupWindow>();
                if startup.manual && !startup.shown.swap(true, Ordering::SeqCst) {
                    panel::show(app);
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            run_collector,
            run_collector_raw,
            set_tray_tooltip,
            set_tray_menu_labels,
            quit_app,
            set_keep_awake,
            keep_awake_active,
            privacy::start_activity_reporter,
            privacy::set_activity_statistics,
            privacy::grok_bot_authorization_status,
            privacy::authorize_grok_bot,
            doubaowork_webview::doubaowork_quota_state,
            doubaowork_webview::set_doubaowork_quota_enabled,
            doubaowork_webview::connect_doubaowork_quota,
            doubaowork_webview::refresh_doubaowork_quota,
            panel::open_main_window,
            panel::hide_quick_panel,
            panel::open_quick_panel,
            panel::quick_panel_visible,
            panel::get_tray_click_action,
            panel::set_tray_click_action,
            snapshot::get_usage_snapshot,
            snapshot::publish_usage_snapshot,
            snapshot::request_usage_refresh,
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
            doubaowork_webview::initialize(app.handle());

            if let Some(window) = app.get_webview_window(panel::LABEL) {
                let handle = app.handle().clone();
                window.on_window_event(move |event| {
                    if let WindowEvent::CloseRequested { api, .. } = event {
                        api.prevent_close();
                        panel::hide(&handle);
                    }
                });
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Tokei");
}

fn build_tray(app: &AppHandle) -> tauri::Result<()> {
    // 先用中文原文占位，前端起来后按界面语言换成译文。
    let open = MenuItem::with_id(app, "open", "打开主窗口", true, None::<&str>)?;
    let quick = MenuItem::with_id(app, "quick", "快捷面板", true, None::<&str>)?;
    let refresh = MenuItem::with_id(app, "refresh", "刷新", true, None::<&str>)?;
    let settings = MenuItem::with_id(app, "settings", "设置", true, None::<&str>)?;
    let autostart_on = app.autolaunch().is_enabled().unwrap_or(false);
    let autostart = CheckMenuItem::with_id(
        app,
        "autostart",
        "登录时启动",
        true,
        autostart_on,
        None::<&str>,
    )?;
    let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
    let separator = PredefinedMenuItem::separator(app)?;
    let menu = Menu::with_items(
        app,
        &[
            &open, &quick, &refresh, &settings, &autostart, &separator, &quit,
        ],
    )?;
    app.manage(TrayMenu {
        open,
        quick,
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
            "open" => {
                let _ = panel::open_main_window(app.clone(), None);
            }
            "quick" => {
                panel::show_quick(app, None);
            }
            "refresh" => {
                let _ = app.emit_to(panel::LABEL, "tokei://refresh", ());
            }
            "settings" => {
                panel::show(app);
                let _ = app.emit_to(panel::LABEL, "tokei://open-settings", ());
            }
            "autostart" => {
                let launcher = app.autolaunch();
                let enabled = launcher.is_enabled().unwrap_or(false);
                let _ = if enabled {
                    launcher.disable()
                } else {
                    launcher.enable()
                };
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
                panel::tray_click(tray.app_handle(), rect);
            }
        })
        .build(app)?;
    Ok(())
}
