//! An opt-in account owned by Tokei, separate from every installed browser.
use crate::{doubaowork_quota as quota, panel, store};
use serde::Serialize;
use serde_json::{json, Map};
use std::sync::{
    atomic::{AtomicBool, Ordering},
    Arc, Mutex,
};
use std::time::{Duration, Instant};
use tauri::{
    webview::NewWindowResponse, AppHandle, Emitter, Manager, Url, WebviewUrl, WebviewWindow,
    WebviewWindowBuilder, WindowEvent,
};

const LABEL: &str = "doubaowork-quota";
const PAGE: &str = "https://www.doubao.com/member/quota-management?platform=desktop&is_work=1&is_setting_iframe=1&locale=zh";
const CONFIG_KEY: &str = "doubaowork_quota_enabled";
const REFRESH_INTERVAL: Duration = Duration::from_secs(5 * 60);
const RESPONSE_TIMEOUT: Duration = Duration::from_secs(45);
const OBSERVER: &str = include_str!("../../../doubaowork-quota.js");

struct Session {
    enabled: bool,
    started: bool,
    nonce: Option<String>,
    pending: Option<Instant>,
    last_refresh: Option<Instant>,
    status: quota::Status,
}

impl Default for Session {
    fn default() -> Self {
        Self {
            enabled: false,
            started: false,
            nonce: None,
            pending: None,
            last_refresh: None,
            status: quota::Status::Unavailable,
        }
    }
}

#[derive(Clone, Default)]
pub struct QuotaState {
    session: Arc<Mutex<Session>>,
    stopped: Arc<AtomicBool>,
}

#[derive(Serialize)]
pub struct Connection {
    enabled: bool,
    status: &'static str,
}

impl QuotaState {
    fn connection(&self) -> Connection {
        let current = self.session.lock().unwrap_or_else(|e| e.into_inner());
        Connection {
            enabled: current.enabled,
            status: if current.pending.is_some() {
                "refreshing"
            } else {
                match current.status {
                    quota::Status::Connected => "connected",
                    quota::Status::LoginRequired => "login_required",
                    quota::Status::Unavailable => "unavailable",
                }
            },
        }
    }

    pub fn stop(&self) {
        self.stopped.store(true, Ordering::Relaxed);
    }
}

fn main_only(window: &WebviewWindow) -> Result<(), String> {
    if window.label() == panel::LABEL {
        Ok(())
    } else {
        Err("Doubao account controls belong to the main window".into())
    }
}

fn cache_path() -> Result<std::path::PathBuf, String> {
    Ok(store::tokei_dir()?.join(quota::CACHE_FILE))
}

fn changed(app: &AppHandle) {
    // Only local Tokei windows receive state changes. The account page has no IPC capability.
    let _ = app.emit_to(panel::LABEL, "tokei://doubaowork-quota", ());
    let _ = app.emit_to(panel::LABEL, "tokei://refresh", ());
}

fn failure(app: &AppHandle, status: quota::Status) {
    let state = app.state::<QuotaState>();
    let mut current = state.session.lock().unwrap_or_else(|e| e.into_inner());
    if !current.enabled {
        return;
    }
    current.pending = None;
    current.status = status;
    if let Ok(path) = cache_path() {
        let snapshot = quota::Snapshot::failure(quota::read_cache(&path), status);
        let _ = quota::write_cache(&path, &snapshot);
    }
    drop(current);
    changed(app);
}

fn report(app: &AppHandle, target: &Url) {
    let Some(source) = app
        .get_webview_window(LABEL)
        .and_then(|window| window.url().ok())
    else {
        return;
    };
    let state = app.state::<QuotaState>();
    let mut current = state.session.lock().unwrap_or_else(|e| e.into_inner());
    if !current.enabled {
        return;
    }
    let Some(nonce) = current.nonce.as_deref() else {
        return;
    };
    let Some(snapshot) = quota::accept_callback(target, &source, nonce, quota::now()) else {
        return;
    };
    let Ok(path) = cache_path() else {
        return;
    };
    if quota::write_cache(&path, &snapshot).is_err() {
        return;
    }
    current.pending = None;
    current.status = quota::Status::Connected;
    drop(current);
    if let Some(window) = app.get_webview_window(LABEL) {
        let _ = window.hide();
    }
    changed(app);
}

fn build_window(app: &AppHandle, nonce: &str) -> Result<WebviewWindow, String> {
    let directory = app
        .path()
        .app_local_data_dir()
        .map_err(|_| "Doubao profile directory unavailable")?
        .join("DoubaoWorkAccount");
    #[cfg(debug_assertions)]
    let directory = match std::env::var_os("TOKEI_TEST_STATE_DIR") {
        Some(path) => std::path::PathBuf::from(path).join("DoubaoWorkAccount"),
        None => directory,
    };
    std::fs::create_dir_all(&directory).map_err(|_| "Doubao profile directory unavailable")?;
    let nav_app = app.clone();
    let load_app = app.clone();
    let window = WebviewWindowBuilder::new(
        app,
        LABEL,
        WebviewUrl::External(PAGE.parse().map_err(|_| "Invalid quota page")?),
    )
    .title("Doubao Work · Tokei")
    .inner_size(980.0, 720.0)
    .min_inner_size(640.0, 480.0)
    .visible(false)
    .focused(false)
    .data_directory(directory)
    .devtools(false)
    .initialization_script(OBSERVER.replace("__TOKEI_DOUBAO_NONCE__", nonce))
    .on_navigation(move |url| {
        // Cancel every callback-host navigation, including malformed messages.
        // Cancellation happens before the browser can issue a network request.
        if url.host_str() == Some(quota::CALLBACK_HOST) {
            let report_app = nav_app.clone();
            let target = url.clone();
            // Cancel first; never do disk I/O or synchronous WebView getters in
            // a WebView2 navigation event. Read the native source after cancellation.
            tauri::async_runtime::spawn_blocking(move || report(&report_app, &target));
            return false;
        }
        let enabled = nav_app
            .state::<QuotaState>()
            .session
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .enabled;
        if url.as_str() == "about:blank" {
            return !enabled;
        }
        // Normal HTTPS login redirects remain in this isolated browser profile.
        // Local protocols and Tokei's application UI can never be loaded here.
        enabled && url.scheme() == "https" && url.username().is_empty() && url.password().is_none()
    })
    .on_new_window(|_, _| NewWindowResponse::Deny)
    .on_download(|_, _| false)
    .on_page_load(move |_, payload| {
        if quota::login_page(payload.url()) {
            failure(&load_app, quota::Status::LoginRequired);
        }
    })
    .build()
    .map_err(|_| "Unable to create Doubao account window")?;
    let close_window = window.clone();
    window.on_window_event(move |event| {
        if let WindowEvent::CloseRequested { api, .. } = event {
            api.prevent_close();
            let _ = close_window.hide();
        }
    });
    Ok(window)
}

fn refresh(app: &AppHandle, show: bool) -> Result<(), String> {
    let state = app.state::<QuotaState>();
    let mut current = state.session.lock().unwrap_or_else(|e| e.into_inner());
    if !current.enabled {
        return Err("Doubao quota queries are disabled".into());
    }
    if current.nonce.is_none() {
        current.nonce =
            Some(quota::random_nonce().map_err(|_| "Secure random source unavailable")?);
    }
    let nonce = current.nonce.clone().unwrap();
    // Repeated clicks only reveal the existing page; they do not restart login.
    let pending = current.pending.is_some();
    current.last_refresh = Some(Instant::now());
    if !pending {
        current.pending = Some(Instant::now());
    }
    drop(current);
    let existed = app.get_webview_window(LABEL);
    let window = if let Some(window) = existed {
        if !pending {
            window
                .navigate(PAGE.parse().map_err(|_| "Invalid quota page")?)
                .map_err(|_| "Unable to refresh Doubao quota")?;
        }
        window
    } else {
        build_window(app, &nonce)?
    };
    if show {
        window
            .show()
            .map_err(|_| "Unable to show Doubao account window")?;
        window
            .set_focus()
            .map_err(|_| "Unable to focus Doubao account window")?;
    }
    Ok(())
}

pub fn initialize(app: &AppHandle) {
    if !cfg!(windows) {
        return;
    }
    let state = app.state::<QuotaState>().inner().clone();
    {
        let mut current = state.session.lock().unwrap_or_else(|e| e.into_inner());
        if current.started {
            return;
        }
        current.started = true;
        current.enabled = store::read_tokei_config()
            .get(CONFIG_KEY)
            .and_then(|v| v.as_bool())
            .unwrap_or(false);
        if let Some(cache) = cache_path().ok().and_then(|path| quota::read_cache(&path)) {
            current.status = cache.status;
        }
    }
    let timer_app = app.clone();
    std::thread::spawn(move || {
        while !state.stopped.load(Ordering::Relaxed) {
            std::thread::sleep(Duration::from_secs(5));
            let (timed_out, due) = {
                let current = state.session.lock().unwrap_or_else(|e| e.into_inner());
                if !current.enabled {
                    continue;
                }
                (
                    current
                        .pending
                        .is_some_and(|start| start.elapsed() >= RESPONSE_TIMEOUT),
                    current.pending.is_none()
                        && current
                            .last_refresh
                            .is_none_or(|last| last.elapsed() >= REFRESH_INTERVAL),
                )
            };
            if !timed_out && !due {
                continue;
            }
            if timed_out {
                let login = timer_app
                    .get_webview_window(LABEL)
                    .and_then(|w| w.url().ok())
                    .is_some_and(|url| quota::login_page(&url));
                failure(
                    &timer_app,
                    if login {
                        quota::Status::LoginRequired
                    } else {
                        quota::Status::Unavailable
                    },
                );
            } else {
                // Never interrupt an account login that the user is completing.
                if timer_app
                    .get_webview_window(LABEL)
                    .is_some_and(|window| window.is_visible().unwrap_or(false))
                {
                    continue;
                }
                if refresh(&timer_app, false).is_err() {
                    failure(&timer_app, quota::Status::Unavailable);
                }
            }
        }
    });
}

async fn on_worker(
    app: AppHandle,
    operation: impl FnOnce(&AppHandle) -> Result<(), String> + Send + 'static,
) -> Result<Connection, String> {
    // Tauri/WebView2 requires building windows outside synchronous event handlers.
    tauri::async_runtime::spawn_blocking(move || {
        operation(&app).map(|_| app.state::<QuotaState>().connection())
    })
    .await
    .map_err(|_| "Account window unavailable")?
}

#[tauri::command]
pub fn doubaowork_quota_state(
    window: WebviewWindow,
    state: tauri::State<'_, QuotaState>,
) -> Result<Connection, String> {
    main_only(&window)?;
    Ok(state.connection())
}

#[tauri::command]
pub async fn set_doubaowork_quota_enabled(
    app: AppHandle,
    window: WebviewWindow,
    enabled: bool,
) -> Result<Connection, String> {
    main_only(&window)?;
    if enabled && !cfg!(windows) {
        return Err("Doubao account connection requires Windows".into());
    }
    let mut patch = Map::new();
    patch.insert(CONFIG_KEY.into(), json!(enabled));
    store::update_tokei_config(patch)?;
    on_worker(app, move |app| {
        let state = app.state::<QuotaState>();
        let changed = {
            let mut current = state.session.lock().unwrap_or_else(|e| e.into_inner());
            let changed = current.enabled != enabled;
            current.enabled = enabled;
            if !enabled {
                current.pending = None;
                current.last_refresh = None;
            }
            changed
        };
        if !enabled {
            if let Some(window) = app.get_webview_window(LABEL) {
                let _ = window.hide();
                window
                    .navigate("about:blank".parse().unwrap())
                    .map_err(|_| "Unable to stop Doubao quota queries")?;
            }
        } else if changed {
            refresh(app, false)?;
        }
        Ok(())
    })
    .await
}

#[tauri::command]
pub async fn connect_doubaowork_quota(
    app: AppHandle,
    window: WebviewWindow,
) -> Result<Connection, String> {
    main_only(&window)?;
    if !cfg!(windows) {
        return Err("Doubao account connection requires Windows".into());
    }
    let mut patch = Map::new();
    patch.insert(CONFIG_KEY.into(), json!(true));
    store::update_tokei_config(patch)?;
    on_worker(app, |app| {
        app.state::<QuotaState>()
            .session
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .enabled = true;
        refresh(app, true)
    })
    .await
}

#[tauri::command]
pub async fn refresh_doubaowork_quota(
    app: AppHandle,
    window: WebviewWindow,
) -> Result<Connection, String> {
    main_only(&window)?;
    if !cfg!(windows) {
        return Err("Doubao account connection requires Windows".into());
    }
    on_worker(app, |app| {
        app.state::<QuotaState>()
            .session
            .lock()
            .unwrap_or_else(|e| e.into_inner())
            .pending = None;
        refresh(app, false)
    })
    .await
}
