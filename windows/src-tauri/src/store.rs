//! 和采集脚本共用的本机状态：`~/.tokei` 下的文件，以及存在系统凭据库里的 Key。
//!
//! - `config.json`：采集脚本读的开关（额度查询、同步目录等），按键合并写入，不整份覆盖，
//!   和 Mac 版 SyncManager.setConfigValue 一样。
//! - 其他文件（额度曲线的历史等）：只允许读写 `~/.tokei` 下的单层文件名，防止前端拼出别的路径。
//! - Key：由系统密钥库保存。Windows/macOS 通过环境变量传给采集器，
//!   Linux 从已解锁的条目读取，再通过管道传给采集器。

use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::sync::Mutex;

use serde_json::{Map, Value};

const KEYRING_SERVICE: &str = "com.tokei.windows.provider-api-key";

/// 命令在各自线程里跑，两次按键合并同时读改写会丢掉一边（Mac 版用 config.lock 串行）。
static CONFIG_LOCK: Mutex<()> = Mutex::new(());

/// 与 Mac 版 ProviderCredentialStore.environmentOverrides 同一张表。
pub(crate) const SECRETS: &[(&str, &str)] = &[
    ("sub2api", "SUB2API_API_KEY"),
    ("zai", "Z_AI_API_KEY"),
    ("minimax", "TOKEI_MINIMAX_API_KEY"),
];

pub fn tokei_dir() -> Result<PathBuf, String> {
    // 本机原生窗口测试使用独立目录，避免写入维护者的真实配置和额度历史。
    #[cfg(debug_assertions)]
    if let Some(dir) = std::env::var_os("TOKEI_TEST_STATE_DIR") {
        let dir = PathBuf::from(dir);
        if dir.is_absolute() { return Ok(dir); }
        return Err("TOKEI_TEST_STATE_DIR must be an absolute path".into());
    }
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

/// 文件不存在算空配置；内容坏了报错，免得合并写入时把用户其他配置整份冲掉。
fn read_config() -> Result<Map<String, Value>, String> {
    match fs::read(tokei_dir()?.join("config.json")) {
        Ok(bytes) => match serde_json::from_slice::<Value>(&bytes) {
            Ok(Value::Object(map)) => Ok(map),
            _ => Err("config.json 不是有效的 JSON 对象".to_string()),
        },
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => Ok(Map::new()),
        Err(err) => Err(err.to_string()),
    }
}

#[tauri::command]
pub fn read_tokei_config() -> Value {
    Value::Object(read_config().unwrap_or_default())
}

/// 按键合并：值为 null 的键删掉，其余覆盖；没提到的键原样保留。
#[tauri::command]
pub fn update_tokei_config(patch: Map<String, Value>) -> Result<Value, String> {
    let _guard = CONFIG_LOCK.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    let mut config = read_config()?;
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

fn check_provider(provider: &str) -> Result<(), String> {
    if !SECRETS.iter().any(|(name, _)| *name == provider) {
        return Err(format!("未知的 Provider：{provider}"));
    }
    Ok(())
}

fn secret_entry(provider: &str) -> Result<keyring::Entry, String> {
    check_provider(provider)?;
    keyring::Entry::new(KEYRING_SERVICE, provider).map_err(|e| e.to_string())
}

#[cfg(target_os = "linux")]
fn linux_secret_service() -> Result<dbus_secret_service::SecretService, dbus_secret_service::Error> {
    use dbus_secret_service::{EncryptionType, SecretService};

    SecretService::connect_with_max_prompt_timeout(EncryptionType::Dh, 0)
}

#[cfg(target_os = "linux")]
fn linux_secret_items<'a>(
    service: &'a dbus_secret_service::SecretService,
    provider: &str,
) -> Result<
    dbus_secret_service::SearchItemsResult<dbus_secret_service::Item<'a>>,
    dbus_secret_service::Error,
> {
    // Match the attributes used by keyring::Entry to save the credential.
    service.search_items(std::collections::HashMap::from([
        ("service", KEYRING_SERVICE),
        ("username", provider),
        ("target", "default"),
    ]))
}

#[cfg(target_os = "linux")]
fn linux_secret_value(service: &dbus_secret_service::SecretService, provider: &str) -> Option<String> {
    let items = linux_secret_items(service, provider).ok()?;
    if !items.locked.is_empty() || items.unlocked.len() != 1 {
        return None;
    }
    // GetSecret can fail if the item locks after SearchItems. Never call Unlock.
    String::from_utf8(items.unlocked[0].get_secret().ok()?).ok()
}

/// 只回答有没有存，不把 Key 本身交给前端。
#[tauri::command]
pub async fn has_secret(provider: String) -> Result<bool, String> {
    tauri::async_runtime::spawn_blocking(move || {
        #[cfg(target_os = "linux")]
        {
            check_provider(&provider)?;
            let service = linux_secret_service().map_err(|e| e.to_string())?;
            let items = linux_secret_items(&service, &provider).map_err(|e| e.to_string())?;
            return Ok(!items.locked.is_empty() || !items.unlocked.is_empty());
        }
        #[cfg(not(target_os = "linux"))]
        match secret_entry(&provider)?.get_password() {
            Ok(value) => Ok(!value.is_empty()),
            Err(keyring::Error::NoEntry) => Ok(false),
            Err(err) => Err(err.to_string()),
        }
    }).await.map_err(|err| err.to_string())?
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

/// Read credentials for the current collector invocation.
pub fn collector_credentials(args: &[String]) -> Vec<(String, String)> {
    if args.iter().any(|arg| arg == "--local-only") {
        return Vec::new();
    }
    #[cfg(target_os = "linux")]
    {
        if !args.iter().any(|arg| arg == "--json") {
            return Vec::new();
        }
        let config = read_config().unwrap_or_default();
        let enabled = SECRETS
            .iter()
            .filter(|(provider, _)| {
                let env = format!("TOKEI_{}_QUOTA", provider.to_ascii_uppercase());
                match std::env::var(env).as_deref() {
                    Ok("0") => false,
                    Ok("1") => true,
                    _ => config.get(&format!("{provider}_quota_enabled")).and_then(Value::as_bool)
                        == Some(true),
                }
            })
            .collect::<Vec<_>>();
        if enabled.is_empty() {
            return Vec::new();
        }
        let service = linux_secret_service().ok();
        return enabled
            .into_iter()
            .filter_map(|(provider, name)| {
                let value = service
                    .as_ref()
                    .and_then(|service| linux_secret_value(service, provider))
                    .filter(|value| !value.is_empty())
                    .or_else(|| std::env::var(name).ok().filter(|value| !value.is_empty()))?;
                Some((name.to_string(), value))
            })
            .collect();
    }
    #[cfg(not(target_os = "linux"))]
    SECRETS
        .iter()
        .filter_map(|(provider, env)| {
            let value = keyring::Entry::new(KEYRING_SERVICE, provider).ok()?.get_password().ok()?;
            (!value.is_empty()).then(|| (env.to_string(), value))
        })
        .collect()
}

#[cfg(all(test, target_os = "linux"))]
mod linux_tests {
    use super::*;

    #[test]
    #[ignore = "requires the disposable Secret Service session used by Linux CI"]
    fn linux_keyring_skips_locked_credentials() {
        assert_eq!(std::env::var("TOKEI_TEST_LINUX_KEYRING").as_deref(), Ok("1"));
        set_secret("sub2api".into(), "synthetic-enabled-key".into()).unwrap();
        set_secret("zai".into(), "synthetic-disabled-key".into()).unwrap();
        let config = serde_json::json!({"sub2api_quota_enabled": true, "zai_quota_enabled": false});
        update_tokei_config(config.as_object().unwrap().clone()).unwrap();

        let refresh = vec!["--json".into()];
        assert_eq!(
            collector_credentials(&refresh),
            vec![("SUB2API_API_KEY".into(), "synthetic-enabled-key".into())]
        );
        assert!(collector_credentials(&["--json".into(), "--local-only".into()]).is_empty());

        let service = linux_secret_service().unwrap();
        let collection = service.get_default_collection().unwrap();
        collection.lock().unwrap();
        let items = linux_secret_items(&service, "sub2api").unwrap();
        assert!(items.unlocked.is_empty());
        assert_eq!(items.locked.len(), 1);
        assert!(collector_credentials(&refresh).is_empty());
        assert!(collection.is_locked().unwrap());
    }
}
