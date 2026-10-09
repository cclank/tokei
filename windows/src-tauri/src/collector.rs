//! 跑采集脚本 `usage.30s.py`，把它打印的 JSON 原样交给前端。
//!
//! 安装版：Python 和脚本都在安装目录的资源里（`python/python.exe`、`collector/usage.30s.py`），
//! 用户不需要自己装 Python。开发时：脚本取仓库根目录那份，Python 用系统里的。
//! 两样都可以用环境变量 `TOKEI_PYTHON`、`TOKEI_SCRIPT` 指定。

use std::io::Read;
use std::path::PathBuf;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use tauri::{AppHandle, Manager};

/// 一轮采集正常一两秒；第一次扫完整历史可能要几十秒，再长就是卡住了。
const TIMEOUT: Duration = Duration::from_secs(180);

#[cfg(windows)]
const CREATE_NO_WINDOW: u32 = 0x0800_0000;

pub struct Runtime {
    pub python: PathBuf,
    pub script: PathBuf,
}

pub fn resolve(app: &AppHandle) -> Result<Runtime, String> {
    let env_path = |key: &str| std::env::var_os(key).map(PathBuf::from).filter(|p| p.exists());

    let mut script = env_path("TOKEI_SCRIPT");
    let mut python = env_path("TOKEI_PYTHON");

    if let Ok(resources) = app.path().resource_dir() {
        if script.is_none() {
            let bundled = resources.join("collector").join("usage.30s.py");
            if bundled.exists() {
                script = Some(bundled);
            }
        }
        if python.is_none() {
            let bundled = if cfg!(windows) {
                resources.join("python").join("python.exe")
            } else {
                resources.join("python").join("bin").join("python3")
            };
            if bundled.exists() {
                python = Some(bundled);
            }
        }
    }

    if script.is_none() {
        // 开发构建：src-tauri 在 windows/ 下，仓库根目录再往上两级。
        let dev = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../usage.30s.py");
        if dev.exists() {
            script = Some(dev);
        }
    }

    let script = script.ok_or_else(|| "找不到采集脚本 usage.30s.py".to_string())?;
    let python = python.unwrap_or_else(|| PathBuf::from(if cfg!(windows) { "python" } else { "python3" }));
    Ok(Runtime { python, script })
}

/// 跑一次采集脚本，返回 stdout（UTF-8）。`env` 用来传 Key 这类只给脚本看的值。
pub fn run(app: &AppHandle, args: &[String], env: &[(String, String)]) -> Result<String, String> {
    let runtime = resolve(app)?;
    let mut command = Command::new(&runtime.python);
    command
        .arg(&runtime.script)
        .args(args)
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .env("TOKEI_HOST", "tauri")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    for (key, value) in env {
        command.env(key, value);
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    let mut child = command
        .spawn()
        .map_err(|err| format!("启动 Python 失败（{}）：{err}", runtime.python.display()))?;

    // 先把输出管道读走，否则输出大于管道缓冲时子进程会卡在写上。
    let mut stdout = child.stdout.take().expect("piped stdout");
    let mut stderr = child.stderr.take().expect("piped stderr");
    let out_reader = std::thread::spawn(move || {
        let mut buf = Vec::new();
        let _ = stdout.read_to_end(&mut buf);
        buf
    });
    let err_reader = std::thread::spawn(move || {
        let mut buf = Vec::new();
        let _ = stderr.read_to_end(&mut buf);
        buf
    });

    let started = Instant::now();
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) if started.elapsed() > TIMEOUT => {
                let _ = child.kill();
                let _ = child.wait();
                return Err("采集超时".to_string());
            }
            Ok(None) => std::thread::sleep(Duration::from_millis(50)),
            Err(err) => return Err(format!("等待采集进程失败：{err}")),
        }
    };

    let stdout = out_reader.join().unwrap_or_default();
    let stderr = err_reader.join().unwrap_or_default();
    if !status.success() {
        let tail = String::from_utf8_lossy(&stderr);
        let tail: String = tail.chars().rev().take(1500).collect::<Vec<_>>().into_iter().rev().collect();
        return Err(format!("采集脚本退出码 {:?}\n{tail}", status.code()));
    }
    String::from_utf8(stdout).map_err(|err| format!("采集输出不是 UTF-8：{err}"))
}
