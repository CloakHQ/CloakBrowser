//! License validation and caching for CloakBrowser Pro.
//! Direct port of Python `cloakbrowser/license.py` / .NET `License.cs`.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::config;
use crate::error::{Error, Result};
use crate::log;
use crate::version::VERSION;

pub const VALIDATE_URL: &str = "https://cloakbrowser.dev/api/license/validate";
pub const PRO_VERSION_URL: &str = "https://cloakbrowser.dev/api/download/version";

const LICENSE_CACHE_TTL: f64 = 86400.0; // 24 hours
const PRO_VERSION_CHECK_INTERVAL: f64 = 3600.0; // 1 hour

/// Result of a CloakBrowser Pro license validation.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LicenseInfo {
    pub valid: bool,
    pub plan: String,
    pub expires: Option<String>,
}

/// Source of a resolved license key — determines env injection into the child process.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LicenseKeySource {
    /// Explicit `license_key` param.
    Param,
    /// `CLOAKBROWSER_LICENSE_KEY` env var.
    Env,
    /// Default `~/.cloakbrowser/license.key` (binary reads it directly).
    DefaultFile,
    /// Custom cache dir `license.key` (binary can't see it).
    CustomFile,
    /// No key resolved.
    None,
}

fn now_unix() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

fn sha256_hex(s: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(s.as_bytes());
    hex::encode(hasher.finalize())
}

fn http_client() -> Result<reqwest::Client> {
    Ok(reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .user_agent(format!("cloakbrowser-rust/{VERSION}"))
        .build()?)
}

/// Resolve license key with source tracking for env-injection decisions.
pub fn resolve_license_key_with_source(
    license_key: Option<&str>,
) -> (Option<String>, LicenseKeySource) {
    // 1. Explicit param
    if let Some(key) = license_key {
        let trimmed = key.trim();
        if !trimmed.is_empty() {
            return (Some(trimmed.to_string()), LicenseKeySource::Param);
        }
    }

    // 2. Environment variable
    if let Ok(env_key) = std::env::var("CLOAKBROWSER_LICENSE_KEY") {
        let env_key = env_key.trim().to_string();
        if !env_key.is_empty() {
            return (Some(env_key), LicenseKeySource::Env);
        }
    }

    // 3. File in the wrapper cache dir
    let cache_dir = config::get_cache_dir();
    let key_file = cache_dir.join("license.key");
    if let Ok(content) = std::fs::read_to_string(&key_file) {
        let content = content.trim().to_string();
        if !content.is_empty() {
            let home = dirs::home_dir().unwrap_or_else(|| PathBuf::from("."));
            let default_cache = home.join(".cloakbrowser");
            let source = match (
                std::fs::canonicalize(&cache_dir),
                std::fs::canonicalize(&default_cache),
            ) {
                (Ok(a), Ok(b)) if a == b => LicenseKeySource::DefaultFile,
                _ if cache_dir == default_cache => LicenseKeySource::DefaultFile,
                _ => LicenseKeySource::CustomFile,
            };
            return (Some(content), source);
        }
    }

    (None, LicenseKeySource::None)
}

/// Resolve the license key: explicit param > env var > file > None.
pub fn resolve_license_key(license_key: Option<&str>) -> Option<String> {
    resolve_license_key_with_source(license_key).0
}

/// Build a child-process env dict with any needed license key injection.
///
/// Returns `None` when no injection is needed and no custom `user_env` was
/// given — Playwright treats `env=None` as "inherit parent env".
pub fn build_launch_env(
    license_key: Option<&str>,
    user_env: Option<&HashMap<String, String>>,
) -> Option<HashMap<String, String>> {
    let (key, source) = resolve_license_key_with_source(license_key);

    // Default file: binary reads it directly — no env injection needed,
    // UNLESS the caller passes a custom env.
    if source == LicenseKeySource::DefaultFile && user_env.is_none() {
        return None;
    }

    // No key at all: pass through user env or None.
    if source == LicenseKeySource::None || key.is_none() {
        return user_env.cloned();
    }

    // Env source, no custom user env: child inherits parent env.
    if source == LicenseKeySource::Env && user_env.is_none() {
        return None;
    }

    let mut merged = if let Some(user) = user_env {
        user.clone()
    } else {
        std::env::vars().collect()
    };

    if let Some(k) = key {
        merged.insert("CLOAKBROWSER_LICENSE_KEY".into(), k);
    }

    Some(merged)
}

/// Validate a license key with the CloakBrowser server.
///
/// Checks a local file cache first (24h TTL). Falls back to a stale cache if the
/// server is unreachable. Returns `None` on total failure.
pub async fn validate_license(license_key: &str) -> Option<LicenseInfo> {
    let cache_path = config::get_cache_dir().join(".license_cache");
    let key_sha = sha256_hex(license_key);

    if let Some(cached) = read_cache(&cache_path, &key_sha, false) {
        return Some(cached);
    }

    match validate_license_http(license_key).await {
        Ok(info) => {
            if info.valid {
                write_cache(&cache_path, &key_sha, &info);
            }
            Some(info)
        }
        Err(e) => {
            log::warning(format!("License validation request failed: {e}"));
            if let Some(stale) = read_cache(&cache_path, &key_sha, true) {
                log::warning("Using cached license validation (server unreachable)");
                return Some(stale);
            }
            None
        }
    }
}

async fn validate_license_http(license_key: &str) -> Result<LicenseInfo> {
    let client = http_client()?;
    let body = serde_json::json!({ "license_key": license_key });
    let resp = client.post(VALIDATE_URL).json(&body).send().await?;
    let resp = resp.error_for_status()?;
    let data: serde_json::Value = resp.json().await?;

    Ok(LicenseInfo {
        valid: data
            .get("valid")
            .and_then(|v| v.as_bool())
            .unwrap_or(false),
        plan: data
            .get("plan")
            .and_then(|v| v.as_str())
            .unwrap_or("solo")
            .to_string(),
        expires: data
            .get("expires")
            .and_then(|v| v.as_str())
            .map(|s| s.to_string()),
    })
}

/// Get the latest Pro binary version from the server.
/// Rate-limited to 1 call per hour via a marker file.
pub async fn get_pro_latest_version() -> Option<String> {
    let tag = config::get_platform_tag().ok()?;
    let marker = config::get_cache_dir().join(format!(".last_pro_version_check_{tag}"));

    if marker.exists() {
        if let Ok(meta) = marker.metadata() {
            if let Ok(modified) = meta.modified() {
                if let Ok(age) = SystemTime::now().duration_since(modified) {
                    if age.as_secs_f64() < PRO_VERSION_CHECK_INTERVAL {
                        if let Ok(content) = std::fs::read_to_string(&marker) {
                            let content = content.trim();
                            return if content.is_empty() {
                                None
                            } else {
                                Some(content.to_string())
                            };
                        }
                    }
                }
            }
        }
    }

    match fetch_pro_version().await {
        Ok(version) => {
            let _ = std::fs::create_dir_all(marker.parent().unwrap_or(Path::new(".")));
            let tmp = marker.with_extension("tmp");
            if std::fs::write(&tmp, &version).is_ok() {
                let _ = std::fs::rename(&tmp, &marker);
            }
            Some(version)
        }
        Err(e) => {
            log::debug(format!("Pro version check failed: {e}"));
            None
        }
    }
}

async fn fetch_pro_version() -> Result<String> {
    let client = http_client()?;
    let tag = config::get_platform_tag()?;
    let resp = client
        .get(PRO_VERSION_URL)
        .header("X-Platform", tag)
        .send()
        .await?
        .error_for_status()?;
    let data: serde_json::Value = resp.json().await?;
    data.get("version")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .ok_or_else(|| Error::msg("Pro version response missing 'version' field"))
}

#[derive(Deserialize, Serialize)]
struct CacheData {
    key_sha256: String,
    valid: bool,
    plan: String,
    expires: Option<String>,
    validated_at: f64,
}

fn read_cache(cache_path: &Path, key_sha: &str, ignore_ttl: bool) -> Option<LicenseInfo> {
    let text = std::fs::read_to_string(cache_path).ok()?;
    let data: CacheData = serde_json::from_str(&text).ok()?;

    if data.key_sha256 != key_sha {
        return None;
    }

    if !ignore_ttl && now_unix() - data.validated_at > LICENSE_CACHE_TTL {
        return None;
    }

    // Expired license reported as invalid.
    if let Some(ref expires) = data.expires {
        if let Ok(exp) = chrono::DateTime::parse_from_rfc3339(expires) {
            if exp < chrono::Utc::now() {
                return Some(LicenseInfo {
                    valid: false,
                    plan: data.plan,
                    expires: data.expires,
                });
            }
        }
        // Also try ISO without timezone (Python isoformat).
        if let Ok(exp) = chrono::NaiveDateTime::parse_from_str(expires, "%Y-%m-%dT%H:%M:%S") {
            let exp = exp.and_utc();
            if exp < chrono::Utc::now() {
                return Some(LicenseInfo {
                    valid: false,
                    plan: data.plan,
                    expires: data.expires,
                });
            }
        }
    }

    Some(LicenseInfo {
        valid: data.valid,
        plan: data.plan,
        expires: data.expires,
    })
}

fn write_cache(cache_path: &Path, key_sha: &str, info: &LicenseInfo) {
    let _ = std::fs::create_dir_all(cache_path.parent().unwrap_or(Path::new(".")));
    let payload = CacheData {
        key_sha256: key_sha.to_string(),
        valid: info.valid,
        plan: info.plan.clone(),
        expires: info.expires.clone(),
        validated_at: now_unix(),
    };
    let tmp = cache_path.with_extension("tmp");
    if let Ok(json) = serde_json::to_string(&payload) {
        if std::fs::write(&tmp, json).is_ok() {
            let _ = std::fs::rename(&tmp, cache_path);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_param_wins() {
        // Ensure env doesn't interfere if already set — param still wins.
        let (key, source) = resolve_license_key_with_source(Some("  my-key  "));
        assert_eq!(key.as_deref(), Some("my-key"));
        assert_eq!(source, LicenseKeySource::Param);
    }

    #[test]
    fn resolve_empty_param_falls_through() {
        let (key, source) = resolve_license_key_with_source(Some("   "));
        // May be env/file/none depending on environment — just not Param.
        assert_ne!(source, LicenseKeySource::Param);
        let _ = key;
    }

    #[test]
    fn build_launch_env_param_injects() {
        let env = build_launch_env(Some("test-key-xyz"), None);
        assert!(env.is_some());
        assert_eq!(
            env.unwrap().get("CLOAKBROWSER_LICENSE_KEY").map(String::as_str),
            Some("test-key-xyz")
        );
    }
}
