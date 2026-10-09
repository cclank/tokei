//! 和采集脚本共用的本机状态：`~/.tokei` 下的文件，以及存在系统凭据库里的 Key。
//!
//! - `config.json`：采集脚本读的开关（额度查询、同步目录等），按键合并写入，不整份覆盖，
//!   和 Mac 版 SyncManager.setConfigValue 一样。
//! - 其他文件（额度曲线的历史等）：只允许读写 `~/.tokei` 下的单层文件名，防止前端拼出别的路径。
//! - Key：Windows 存「凭据管理器」，macOS（开发调试）存钥匙串；采集时作为环境变量传给脚本，
//!   不写进 config.json，也不进同步快照。

use std::fs;
use std::io::Write;
use std::path::PathBuf;

use serde_json::{Map, Value};

const KEYRING_SERVICE: &str = "com.tokei.windows.provider-api-key";

/// 与 Mac 版 ProviderCredentialStore.environmentOverrides 同一张表。
const SECRETS: &[(&str, &str)] = &[
    ("sub2api", "SUB2API_API_KEY"),
    ("zai", "Z_AI_API_KEY"),
    ("minimax", "TOKEI_MINIMAX_API_KEY"),
];

pub fn tokei_dir() -> Result<PathBuf, String> {
    let home = dirs::home_dir().ok_or_else(|| "找不到用户目录".to_string())?;
    Ok(home.join(".tokei"))
}

fn checked_name(name: &str) -> Result<&str, String> {
    let ok = !name.is_empty()
        && name.len() <= 80
        && !name.starts_with('.')
        && name.chars().all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-'));
    if ok {
        Ok(name)
    } else {
        Err(format!("不允许的文件名：{name}"))
    }
}

fn atomic_write(path: &PathBuf, content: &[u8]) -> Result<(), String> {
    let dir = path.parent().ok_or_else(|| "路径没有上级目录".to_string())?;
    fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    let tmp = dir.join(format!(".{}.tmp-{}", path.file_name().and_then(|n| n.to_str()).unwrap_or("file"), std::process::id()));
    {
        let mut file = fs::File::create(&tmp).map_err(|e| e.to_string())?;
        file.write_all(content).map_err(|e| e.to_string())?;
        file.sync_all().ok();
    }
    fs::rename(&tmp, path).map_err(|e| {
        let _ = fs::remove_file(&tmp);
        e.to_string()
    })
}

#[tauri::command]
pub fn read_tokei_file(name: String) -> Result<Option<String>, String> {
    let path = tokei_dir()?.join(checked_name(&name)?);
    match fs::read(&path) {
        Ok(bytes) => Ok(Some(String::from_utf8_lossy(&bytes).into_owned())),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(err) => Err(err.to_string()),
    }
}

#[tauri::command]
pub fn write_tokei_file(name: String, content: String) -> Result<(), String> {
    let path = tokei_dir()?.join(checked_name(&name)?);
    atomic_write(&path, content.as_bytes())
}

fn read_config() -> Map<String, Value> {
    let Ok(dir) = tokei_dir() else { return Map::new() };
    fs::read(dir.join("config.json"))
        .ok()
        .and_then(|bytes| serde_json::from_slice::<Value>(&bytes).ok())
        .and_then(|value| value.as_object().cloned())
        .unwrap_or_default()
}

#[tauri::command]
pub fn read_tokei_config() -> Value {
    Value::Object(read_config())
}

/// 按键合并：值为 null 的键删掉，其余覆盖；没提到的键原样保留。
#[tauri::command]
pub fn update_tokei_config(patch: Map<String, Value>) -> Result<Value, String> {
    let mut config = read_config();
    for (key, value) in patch {
        if value.is_null() {
            config.remove(&key);
        } else {
            config.insert(key, value);
        }
    }
    let text = serde_json::to_string_pretty(&Value::Object(config.clone())).map_err(|e| e.to_string())?;
    atomic_write(&tokei_dir()?.join("config.json"), text.as_bytes())?;
    Ok(Value::Object(config))
}

fn secret_entry(provider: &str) -> Result<keyring::Entry, String> {
    if !SECRETS.iter().any(|(name, _)| *name == provider) {
        return Err(format!("未知的 Provider：{provider}"));
    }
    keyring::Entry::new(KEYRING_SERVICE, provider).map_err(|e| e.to_string())
}

/// 只回答有没有存，不把 Key 本身交给前端。
#[tauri::command]
pub fn has_secret(provider: String) -> Result<bool, String> {
    match secret_entry(&provider)?.get_password() {
        Ok(value) => Ok(!value.is_empty()),
        Err(keyring::Error::NoEntry) => Ok(false),
        Err(err) => Err(err.to_string()),
    }
}

#[tauri::command]
pub fn set_secret(provider: String, value: String) -> Result<(), String> {
    let value = value.trim();
    if value.is_empty() {
        return delete_secret(provider);
    }
    secret_entry(&provider)?.set_password(value).map_err(|e| e.to_string())
}

#[tauri::command]
pub fn delete_secret(provider: String) -> Result<(), String> {
    match secret_entry(&provider)?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(err) => Err(err.to_string()),
    }
}

/// 采集时传给脚本的环境变量（Mac 版 environmentOverrides）。
pub fn secret_environment() -> Vec<(String, String)> {
    SECRETS
        .iter()
        .filter_map(|(provider, env)| {
            let value = keyring::Entry::new(KEYRING_SERVICE, provider).ok()?.get_password().ok()?;
            (!value.is_empty()).then(|| (env.to_string(), value))
        })
        .collect()
}
