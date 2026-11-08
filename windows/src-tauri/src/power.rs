//! 「防休眠」：开着时系统和屏幕都不进入睡眠。
//!
//! Windows 的 SetThreadExecutionState 只对调用它的线程有效，线程一退出就失效，
//! 所以放在一个常驻线程里设置，关掉时让这个线程恢复默认再退出。
//! macOS（开发调试用）起一个 `caffeinate -di` 子进程。
//! Linux 持有 logind 返回的文件描述符，关闭开关或进程退出时释放锁。

#[derive(Default)]
pub struct KeepAwake {
    #[cfg(windows)]
    stop: Option<std::sync::mpsc::Sender<()>>,
    #[cfg(all(not(windows), not(target_os = "linux")))]
    child: Option<std::process::Child>,
    #[cfg(target_os = "linux")]
    inhibitor: Option<dbus::arg::OwnedFd>,
}

impl KeepAwake {
    pub fn active(&self) -> bool {
        #[cfg(windows)]
        return self.stop.is_some();
        #[cfg(all(not(windows), not(target_os = "linux")))]
        return self.child.is_some();
        #[cfg(target_os = "linux")]
        return self.inhibitor.is_some();
    }

    /// 打开或关闭，返回之后的状态。
    pub fn set(&mut self, on: bool) -> bool {
        if on == self.active() {
            return on;
        }
        if on {
            self.start();
        } else {
            self.stop();
        }
        self.active()
    }

    #[cfg(windows)]
    fn start(&mut self) {
        use windows_sys::Win32::System::Power::{
            SetThreadExecutionState, ES_CONTINUOUS, ES_DISPLAY_REQUIRED, ES_SYSTEM_REQUIRED,
        };
        let (tx, rx) = std::sync::mpsc::channel::<()>();
        std::thread::spawn(move || unsafe {
            SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED);
            let _ = rx.recv();
            SetThreadExecutionState(ES_CONTINUOUS);
        });
        self.stop = Some(tx);
    }

    #[cfg(windows)]
    fn stop(&mut self) {
        if let Some(tx) = self.stop.take() {
            let _ = tx.send(());
        }
    }

    #[cfg(all(not(windows), not(target_os = "linux")))]
    fn start(&mut self) {
        self.child = std::process::Command::new("caffeinate").arg("-di").spawn().ok();
    }

    #[cfg(target_os = "linux")]
    fn start(&mut self) {
        let Ok(bus) = dbus::blocking::Connection::new_system() else {
            return;
        };
        let logind = bus.with_proxy(
            "org.freedesktop.login1",
            "/org/freedesktop/login1",
            std::time::Duration::from_secs(2),
        );
        let result: Result<(dbus::arg::OwnedFd,), _> = logind.method_call(
            "org.freedesktop.login1.Manager",
            "Inhibit",
            ("idle:sleep", "Tokei", "Keep awake is enabled", "block"),
        );
        self.inhibitor = result.ok().map(|(fd,)| fd);
    }

    #[cfg(target_os = "linux")]
    fn stop(&mut self) {
        self.inhibitor = None;
    }

    #[cfg(all(not(windows), not(target_os = "linux")))]
    fn stop(&mut self) {
        if let Some(mut child) = self.child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }
}

impl Drop for KeepAwake {
    fn drop(&mut self) {
        self.stop();
    }
}
