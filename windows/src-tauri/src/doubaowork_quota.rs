//! The only data allowed to leave Tokei's own Doubao WebView.
use serde::{Deserialize, Serialize};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::Url;

pub const CACHE_FILE: &str = "doubaowork_quota_cache.json";
pub const MAX_MESSAGE: usize = 64 * 1024;
pub const MAX_TIME_MS: u64 = 32_503_680_000_000;
pub const CALLBACK_HOST: &str = "tokei.invalid";
pub const CALLBACK_PATH: &str = "/doubaowork-quota";

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    Connected,
    LoginRequired,
    Unavailable,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct QuotaWindow {
    pub window_type: u8,
    pub used_percent: f64,
    pub start_time_ms: u64,
    pub end_time_ms: u64,
    pub less_than_one_percent: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Snapshot {
    pub version: u8,
    pub status: Status,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub updated: Option<u64>,
    #[serde(default)]
    pub windows: Vec<QuotaWindow>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Message {
    nonce: String,
    snapshot: Snapshot,
}

pub fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

pub fn random_nonce() -> io::Result<String> {
    let mut bytes = [0u8; 32];
    getrandom::fill(&mut bytes).map_err(|_| io::Error::other("Random source unavailable"))?;
    Ok(bytes.iter().map(|b| format!("{b:02x}")).collect())
}

pub fn official_origin(url: &Url) -> bool {
    url.scheme() == "https"
        && matches!(url.host_str(), Some("www.doubao.com" | "doubao.com"))
        && url.port_or_known_default() == Some(443)
        && url.username().is_empty()
        && url.password().is_none()
}

pub fn login_page(url: &Url) -> bool {
    official_origin(url)
        && url
            .path()
            .split('/')
            .any(|part| matches!(part, "login" | "passport" | "signin"))
}

impl Snapshot {
    pub fn failure(previous: Option<Self>, status: Status) -> Self {
        let mut snapshot = previous.filter(|value| value.valid()).unwrap_or(Self {
            version: 1,
            status,
            updated: None,
            windows: Vec::new(),
        });
        snapshot.status = status;
        snapshot
    }

    pub fn valid(&self) -> bool {
        if self.version != 1 {
            return false;
        }
        if self.updated == Some(0) || self.windows.len() > 2 {
            return false;
        }
        if self.windows.is_empty() {
            return self.status != Status::Connected;
        }
        if self.updated.is_none() {
            return false;
        }
        let mut seen = [false; 3];
        for window in &self.windows {
            let kind = window.window_type as usize;
            if !(1..=2).contains(&kind)
                || seen[kind]
                || !window.used_percent.is_finite()
                || !(0.0..=100.0).contains(&window.used_percent)
                || (window.less_than_one_percent && window.used_percent >= 1.0)
                || window.start_time_ms > MAX_TIME_MS
                || window.end_time_ms > MAX_TIME_MS
                || (window.end_time_ms > 0 && window.end_time_ms < window.start_time_ms)
            {
                return false;
            }
            seen[kind] = true;
        }
        true
    }
}

fn decode_fragment(fragment: &str) -> Option<Vec<u8>> {
    if fragment.len() > MAX_MESSAGE * 3 {
        return None;
    }
    let mut out = Vec::with_capacity(fragment.len().min(MAX_MESSAGE));
    let mut bytes = fragment.as_bytes().iter().copied();
    while let Some(byte) = bytes.next() {
        out.push(if byte == b'%' {
            let high = (bytes.next()? as char).to_digit(16)?;
            let low = (bytes.next()? as char).to_digit(16)?;
            ((high << 4) | low) as u8
        } else {
            byte
        });
        if out.len() > MAX_MESSAGE {
            return None;
        }
    }
    Some(out)
}

/// `source` is read from the native WebView, never supplied by the remote message.
pub fn accept_callback(url: &Url, source: &Url, nonce: &str, timestamp: u64) -> Option<Snapshot> {
    if !official_origin(source)
        || url.scheme() != "https"
        || url.host_str() != Some(CALLBACK_HOST)
        || url.path() != CALLBACK_PATH
        || url.port().is_some()
        || url.query().is_some()
        || !url.username().is_empty()
        || url.password().is_some()
        || nonce.len() != 64
    {
        return None;
    }
    let bytes = decode_fragment(url.fragment()?)?;
    let mut message: Message = serde_json::from_slice(&bytes).ok()?;
    if message.nonce.as_bytes().len() != nonce.len()
        || message
            .nonce
            .bytes()
            .zip(nonce.bytes())
            .fold(0u8, |difference, (a, b)| difference | (a ^ b))
            != 0
        || message.snapshot.status != Status::Connected
        || !message.snapshot.valid()
    {
        return None;
    }
    message.snapshot.updated = Some(timestamp);
    Some(message.snapshot)
}

pub fn read_cache(path: &Path) -> Option<Snapshot> {
    let mut bytes = Vec::new();
    File::open(path)
        .ok()?
        .take((MAX_MESSAGE + 1) as u64)
        .read_to_end(&mut bytes)
        .ok()?;
    if bytes.len() > MAX_MESSAGE {
        return None;
    }
    let snapshot: Snapshot = serde_json::from_slice(&bytes).ok()?;
    (snapshot.valid()
        && snapshot
            .updated
            .is_none_or(|updated| updated <= now().saturating_add(60)))
    .then_some(snapshot)
}

pub fn write_cache(path: &Path, snapshot: &Snapshot) -> io::Result<()> {
    if !snapshot.valid() {
        return Err(io::Error::other("Invalid quota snapshot"));
    }
    let bytes = serde_json::to_vec(snapshot).map_err(io::Error::other)?;
    if bytes.len() > MAX_MESSAGE {
        return Err(io::Error::other("Quota snapshot too large"));
    }
    let dir = path
        .parent()
        .ok_or_else(|| io::Error::other("Missing cache directory"))?;
    fs::create_dir_all(dir)?;
    let temp = dir.join(format!(".doubaowork-quota-{}.tmp", random_nonce()?));
    let result = (|| {
        let mut file = private_file(&temp)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
        drop(file);
        fs::rename(&temp, path)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp);
    }
    result
}

#[cfg(not(windows))]
fn private_file(path: &Path) -> io::Result<File> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    options.open(path)
}

// Windows has no POSIX mode 0600. A protected DACL grants full access only to
// this file's owner and SYSTEM, without inheriting broader directory grants.
#[cfg(windows)]
fn private_file(path: &Path) -> io::Result<File> {
    use std::ffi::c_void;
    use std::os::windows::{ffi::OsStrExt, io::FromRawHandle};
    #[repr(C)]
    struct SecurityAttributes {
        length: u32,
        descriptor: *mut c_void,
        inherit: i32,
    }
    #[link(name = "advapi32")]
    extern "system" {
        fn ConvertStringSecurityDescriptorToSecurityDescriptorW(
            text: *const u16,
            revision: u32,
            descriptor: *mut *mut c_void,
            size: *mut u32,
        ) -> i32;
    }
    #[link(name = "kernel32")]
    extern "system" {
        fn CreateFileW(
            path: *const u16,
            access: u32,
            sharing: u32,
            security: *const SecurityAttributes,
            disposition: u32,
            flags: u32,
            template: *mut c_void,
        ) -> *mut c_void;
        fn LocalFree(memory: *mut c_void) -> *mut c_void;
    }
    let descriptor_text: Vec<u16> = "D:P(A;;FA;;;SY)(A;;FA;;;OW)\0".encode_utf16().collect();
    let name: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    unsafe {
        let mut descriptor = std::ptr::null_mut();
        if ConvertStringSecurityDescriptorToSecurityDescriptorW(
            descriptor_text.as_ptr(),
            1,
            &mut descriptor,
            std::ptr::null_mut(),
        ) == 0
        {
            return Err(io::Error::last_os_error());
        }
        let security = SecurityAttributes {
            length: std::mem::size_of::<SecurityAttributes>() as u32,
            descriptor,
            inherit: 0,
        };
        let handle = CreateFileW(
            name.as_ptr(),
            0x40000000,
            0,
            &security,
            1,
            0x80,
            std::ptr::null_mut(),
        );
        let error = io::Error::last_os_error();
        LocalFree(descriptor);
        if handle as isize == -1 {
            return Err(error);
        }
        Ok(File::from_raw_handle(handle))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn message() -> serde_json::Value {
        json!({"nonce": "a".repeat(64), "snapshot": {"version":1,"status":"connected","updated":u64::MAX,
            "windows":[{"window_type":1,"used_percent":0,"start_time_ms":0,"end_time_ms":0,"less_than_one_percent":true},
                       {"window_type":2,"used_percent":20,"start_time_ms":1000,"end_time_ms":2000,"less_than_one_percent":false}]}})
    }
    fn callback(value: &serde_json::Value) -> Url {
        let encoded = serde_json::to_string(value)
            .unwrap()
            .bytes()
            .map(|b| format!("%{b:02X}"))
            .collect::<String>();
        Url::parse(&format!("https://{CALLBACK_HOST}{CALLBACK_PATH}#{encoded}")).unwrap()
    }
    fn accept(value: &serde_json::Value) -> Option<Snapshot> {
        accept_callback(
            &callback(value),
            &Url::parse("https://www.doubao.com/member/quota-management").unwrap(),
            &"a".repeat(64),
            123,
        )
    }

    #[test]
    fn only_expected_origin_nonce_and_callback_are_accepted() {
        let value = message();
        assert_eq!(accept(&value).unwrap().updated, Some(123));
        let url = callback(&value);
        for origin in [
            "https://doubao.com.evil.test/",
            "http://www.doubao.com/",
            "https://www.doubao.com:444/",
            "https://tokei.invalid/",
        ] {
            assert!(
                accept_callback(&url, &Url::parse(origin).unwrap(), &"a".repeat(64), 123).is_none()
            );
        }
        assert!(accept_callback(
            &url,
            &Url::parse("https://doubao.com/").unwrap(),
            &"b".repeat(64),
            123
        )
        .is_none());
        for prefix in [
            "http://tokei.invalid/doubaowork-quota",
            "https://tokei.invalid:444/doubaowork-quota",
            "https://tokei.invalid/other",
            "https://user@tokei.invalid/doubaowork-quota",
            "https://tokei.invalid/doubaowork-quota?bad=1",
        ] {
            let bad = Url::parse(&format!("{prefix}#{}", url.fragment().unwrap())).unwrap();
            assert!(accept_callback(
                &bad,
                &Url::parse("https://doubao.com/").unwrap(),
                &"a".repeat(64),
                123
            )
            .is_none());
        }
    }

    #[test]
    fn malformed_or_private_payloads_never_become_cache_data() {
        for (key, bad) in [
            ("window_type", json!(3)),
            ("used_percent", json!(101)),
            ("used_percent", json!(-0.1)),
            ("used_percent", json!("0")),
            ("start_time_ms", json!(-1)),
            ("end_time_ms", json!(MAX_TIME_MS + 1)),
            ("less_than_one_percent", json!("false")),
        ] {
            let mut value = message();
            value["snapshot"]["windows"][0][key] = bad;
            assert!(accept(&value).is_none(), "{key}");
        }
        for key in ["raw_response", "user_id", "token"] {
            let mut value = message();
            value["snapshot"][key] = json!("private");
            assert!(accept(&value).is_none());
        }
        let mut duplicate = message();
        duplicate["snapshot"]["windows"][1]["window_type"] = json!(1);
        assert!(accept(&duplicate).is_none());
        let mut empty = message();
        empty["snapshot"]["windows"] = json!([]);
        assert!(accept(&empty).is_none());
        let mut version = message();
        version["snapshot"]["version"] = json!(2);
        assert!(accept(&version).is_none());
        let mut too_big = message();
        too_big["nonce"] = json!("a".repeat(MAX_MESSAGE));
        assert!(accept(&too_big).is_none());
        assert!(decode_fragment("%ZZ").is_none());
        assert!(decode_fragment("%").is_none());
    }

    #[test]
    fn cache_replacement_is_private_and_contains_only_projected_data() {
        let dir =
            std::env::temp_dir().join(format!("tokei-doubao-test-{}", random_nonce().unwrap()));
        let path = dir.join(CACHE_FILE);
        let snapshot = accept(&message()).unwrap();
        write_cache(&path, &snapshot).unwrap();
        assert_eq!(read_cache(&path).unwrap().windows.len(), 2);
        write_cache(
            &path,
            &Snapshot::failure(read_cache(&path), Status::LoginRequired),
        )
        .unwrap();
        assert_eq!(read_cache(&path).unwrap().status, Status::LoginRequired);
        assert_eq!(read_cache(&path).unwrap().updated, Some(123));
        assert_eq!(read_cache(&path).unwrap().windows.len(), 2);
        let text = fs::read_to_string(&path).unwrap();
        assert!(!text.contains("nonce"));
        assert!(!text.contains("user_id"));
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(&path).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
        fs::write(&path, "broken").unwrap();
        assert!(read_cache(&path).is_none());
        fs::write(&path, vec![b' '; MAX_MESSAGE + 1]).unwrap();
        assert!(read_cache(&path).is_none());
        fs::remove_dir_all(dir).unwrap();
    }

    #[test]
    fn failures_keep_last_valid_reading_and_do_not_advance_its_timestamp() {
        let original = accept(&message()).unwrap();
        let failed = Snapshot::failure(Some(original), Status::Unavailable);
        assert!(failed.valid());
        assert_eq!(failed.updated, Some(123));
        assert_eq!(failed.windows[1].used_percent, 20.0);
        let expired = Snapshot::failure(Some(failed), Status::LoginRequired);
        assert!(expired.valid());
        assert_eq!(expired.updated, Some(123));
        assert_eq!(expired.windows.len(), 2);
        let no_cache = Snapshot::failure(None, Status::Unavailable);
        assert!(no_cache.valid());
        assert!(no_cache.updated.is_none());
        assert!(no_cache.windows.is_empty());
        assert!(!serde_json::to_string(&no_cache)
            .unwrap()
            .contains("updated"));
    }
}
