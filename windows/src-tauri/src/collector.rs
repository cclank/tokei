//! 跑采集脚本 `usage.30s.py`，把它打印的 JSON 原样交给前端。
//!
//! Windows 安装包自带 Python，Linux 安装包使用系统 Python。开发时脚本取仓库根目录那份。
//! 两样都可以用环境变量 `TOKEI_PYTHON`、`TOKEI_SCRIPT` 指定。

use std::io::Read;
#[cfg(target_os = "linux")]
use std::io::Write;
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

fn authorization_marker(app: &AppHandle) -> Result<PathBuf, String> {
    #[cfg(debug_assertions)]
    if std::env::var_os("TOKEI_TEST_STATE_DIR").is_some() {
        return Ok(crate::store::tokei_dir()?.join("Grants/grok-bot.json"));
    }
    app.path()
        .app_local_data_dir()
        .map(|path| path.join("Grants/grok-bot.json"))
        .map_err(|_| "Authorization directory unavailable".into())
}

pub fn resolve(app: &AppHandle) -> Result<Runtime, String> {
    let env_path = |key: &str| {
        std::env::var_os(key)
            .map(PathBuf::from)
            .filter(|p| p.exists())
    };

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
    let python = python.unwrap_or_else(|| {
        PathBuf::from(if cfg!(windows) {
            "python"
        } else if cfg!(target_os = "linux") {
            "/usr/bin/python3"
        } else {
            "python3"
        })
    });
    Ok(Runtime { python, script })
}

/// 一次运行的原始结果，设置页「诊断」照 Mac 版 formatDiagnostics 拼文本用。
#[derive(serde::Serialize)]
pub struct RawOutput {
    pub python: String,
    pub script: String,
    pub script_exists: bool,
    pub script_size: u64,
    /// 超时被杀或被信号结束时没有退出码。
    pub exit_code: Option<i32>,
    pub timed_out: bool,
    pub elapsed: f64,
    pub stdout: String,
    pub stderr: String,
}

/// 跑一次采集脚本，返回 stdout（UTF-8）。
pub fn run(app: &AppHandle, args: &[String], env: &[(String, String)]) -> Result<String, String> {
    let raw = run_raw(app, args, env, TIMEOUT)?;
    if raw.timed_out {
        return Err("采集超时".to_string());
    }
    if raw.exit_code != Some(0) {
        let tail: String = raw
            .stderr
            .chars()
            .rev()
            .take(1500)
            .collect::<Vec<_>>()
            .into_iter()
            .rev()
            .collect();
        return Err(format!("采集脚本退出码 {:?}\n{tail}", raw.exit_code));
    }
    Ok(raw.stdout)
}

/// 跑一次采集脚本，不管成败都把退出状态和两路输出交回来。
pub fn run_raw(
    app: &AppHandle,
    args: &[String],
    env: &[(String, String)],
    timeout: Duration,
) -> Result<RawOutput, String> {
    let runtime = resolve(app)?;
    run_runtime(app, runtime, args, env, timeout)
}

pub fn bridge_command(app: &AppHandle) -> Result<Command, String> {
    let mut runtime = resolve(app)?;
    let bundled = app
        .path()
        .resource_dir()
        .ok()
        .map(|dir| dir.join("collector/windows_native.py"));
    runtime.script = bundled
        .filter(|path| path.is_file())
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../native_bridge.py"));
    if !runtime.script.is_file() {
        return Err("Windows integration helper is missing".into());
    }
    let mut command = Command::new(&runtime.python);
    command
        .arg(&runtime.script)
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .env("TOKEI_WINDOWS_STATE_DIR", crate::store::tokei_dir()?)
        .env("TOKEI_GROK_BOT_AUTH_MARKER", authorization_marker(app)?)
        .stdin(Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(CREATE_NO_WINDOW);
    }
    Ok(command)
}

#[cfg(not(target_os = "linux"))]
pub fn run_bridge(app: &AppHandle, mode: &str) -> Result<String, String> {
    let mut command = bridge_command(app)?;
    command
        .arg(mode)
        .stdout(Stdio::piped())
        .stderr(Stdio::null());
    let mut child = command
        .spawn()
        .map_err(|_| "Windows integration helper failed to start".to_string())?;
    let mut stdout = child.stdout.take().ok_or("Windows helper has no output")?;
    let reader = std::thread::spawn(move || {
        let mut output = Vec::new();
        let _ = stdout.by_ref().take(4097).read_to_end(&mut output);
        output
    });
    let started = Instant::now();
    let ok = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status.success(),
            Ok(None) if started.elapsed() < Duration::from_secs(8) => {
                std::thread::sleep(Duration::from_millis(25))
            }
            _ => {
                let _ = child.kill();
                let _ = child.wait();
                break false;
            }
        }
    };
    let output = reader.join().unwrap_or_default();
    if !ok || output.len() > 4096 {
        return Err("Windows integration helper unavailable".into());
    }
    String::from_utf8(output).map_err(|_| "Invalid Windows helper response".into())
}

#[cfg(target_os = "linux")]
fn credential_pipe(command: &mut Command, credentials: &[(String, String)]) -> Option<Vec<u8>> {
    for (_, name) in crate::store::SECRETS {
        command.env_remove(name);
    }
    command.env_remove("TOKEI_PROVIDER_KEYS_STDIN");
    command.env("TOKEI_GROK_BOT_QUOTA", "0");
    if credentials.is_empty() {
        return None;
    }
    let payload = serde_json::to_vec(credentials).ok()?;
    if payload.len() > 64 * 1024 {
        return None;
    }
    command.env("TOKEI_PROVIDER_KEYS_STDIN", "1").stdin(Stdio::piped());
    Some(payload)
}

fn run_runtime(
    app: &AppHandle,
    runtime: Runtime,
    args: &[String],
    credentials: &[(String, String)],
    timeout: Duration,
) -> Result<RawOutput, String> {
    let mut command = Command::new(&runtime.python);
    command
        .arg(&runtime.script)
        .args(args)
        .env("PYTHONUTF8", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .env("TOKEI_HOST", "tauri")
        .env("TOKEI_WINDOWS_STATE_DIR", crate::store::tokei_dir()?)
        .env("TOKEI_GROK_BOT_AUTH_MARKER", authorization_marker(app)?)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(target_os = "linux")]
    let credential_input = credential_pipe(&mut command, credentials);
    #[cfg(not(target_os = "linux"))]
    for (key, value) in credentials {
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

    #[cfg(target_os = "linux")]
    let credential_writer = credential_input.zip(child.stdin.take()).map(|(payload, mut pipe)| {
        std::thread::spawn(move || {
            let _ = pipe.write_all(&payload);
        })
    });

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
    let mut timed_out = false;
    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) if started.elapsed() > timeout => {
                let _ = child.kill();
                let _ = child.wait();
                timed_out = true;
                break None;
            }
            Ok(None) => std::thread::sleep(Duration::from_millis(50)),
            Err(err) => return Err(format!("等待采集进程失败：{err}")),
        }
    };
    let elapsed = started.elapsed().as_secs_f64();

    #[cfg(target_os = "linux")]
    if let Some(writer) = credential_writer {
        let _ = writer.join();
    }

    let stdout = out_reader.join().unwrap_or_default();
    let stderr = err_reader.join().unwrap_or_default();
    let stdout = String::from_utf8(stdout).map_err(|err| format!("采集输出不是 UTF-8：{err}"))?;
    let metadata = std::fs::metadata(&runtime.script).ok();
    Ok(RawOutput {
        python: runtime.python.display().to_string(),
        script: runtime.script.display().to_string(),
        script_exists: metadata.is_some(),
        script_size: metadata.map(|m| m.len()).unwrap_or(0),
        exit_code: status.and_then(|status| status.code()),
        timed_out,
        elapsed,
        stdout,
        stderr: String::from_utf8_lossy(&stderr).into_owned(),
    })
}

#[cfg(all(test, target_os = "linux"))]
mod linux_tests {
    use super::*;

    #[test]
    fn provider_key_reaches_collector_without_reaching_child_environment() {
        let script = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../usage.30s.py");
        let mut command = Command::new("/usr/bin/python3");
        command
            .args(["-B", "-c", r#"
import importlib.util
import os
import subprocess
import sys
import tempfile

with tempfile.TemporaryDirectory() as fixture:
    os.environ["HOME"] = fixture
    spec = importlib.util.spec_from_file_location("collector_fixture", sys.argv[1])
    collector = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = collector
    spec.loader.exec_module(collector)
    collector._PIPED_PROVIDER_KEYS = collector._read_provider_keys_from_stdin()
    assert collector._provider_config_string("SUB2API_API_KEY", "sub2api_api_key") == "fixture-only"
    assert "SUB2API_API_KEY" not in os.environ
    subprocess.run(
        [sys.executable, "-c", "import os; assert 'SUB2API_API_KEY' not in os.environ"],
        check=True,
    )
"#])
            .arg(script)
            .env("TOKEI_HOST", "tauri")
            .env("SUB2API_API_KEY", "inherited-fixture");
        let credentials = vec![("SUB2API_API_KEY".into(), "fixture-only".into())];
        let payload = credential_pipe(&mut command, &credentials).unwrap();
        let mut child = command.spawn().unwrap();
        child.stdin.take().unwrap().write_all(&payload).unwrap();
        assert!(child.wait().unwrap().success());
    }
}
