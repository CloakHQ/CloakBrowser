//! Stealth configuration and platform detection for CloakBrowser.
//! Direct port of Python `cloakbrowser/config.py` / .NET `Config.cs`.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::OnceLock;

use regex::Regex;

use crate::error::{Error, Result};
use crate::license;

// ---------------------------------------------------------------------------
// Chromium version shipped with this release.
// Different platforms may ship different versions during transition periods.
// CHROMIUM_VERSION is the latest across all platforms (for display/reference).
// Use get_chromium_version() for the current platform's actual version.
// ---------------------------------------------------------------------------
pub const CHROMIUM_VERSION: &str = "146.0.7680.177.5";

/// Ed25519 public keys for verifying downloaded binaries (base64 of 32-byte raw keys).
pub const BINARY_SIGNING_PUBKEYS: &[&str] = &["MKFKwIhUcKWq5xTuNA0Ovg99njcDEcEJvmWYYhApvaU="];

/// Playwright default args to suppress — these leak automation signals.
pub const IGNORE_DEFAULT_ARGS: &[&str] = &["--enable-automation", "--enable-unsafe-swiftshader"];

/// Default viewport — HEADLESS only (headed uses no_viewport).
pub const DEFAULT_VIEWPORT_WIDTH: i32 = 1920;
pub const DEFAULT_VIEWPORT_HEIGHT: i32 = 947;

/// First Chromium build that reports coherent headless dimensions without viewport emulation.
pub const HEADLESS_NO_VIEWPORT_MIN_VERSION: Option<&str> = Some("148.0.7778.215.4");

/// GitHub Releases API.
pub const GITHUB_API_URL: &str = "https://api.github.com/repos/CloakHQ/cloakbrowser/releases";

/// GitHub Releases download base.
pub const GITHUB_DOWNLOAD_BASE_URL: &str =
    "https://github.com/CloakHQ/cloakbrowser/releases/download";

fn platform_chromium_versions() -> &'static HashMap<&'static str, &'static str> {
    static MAP: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    MAP.get_or_init(|| {
        HashMap::from([
            ("linux-x64", "146.0.7680.177.5"),
            ("linux-arm64", "146.0.7680.177.3"),
            ("darwin-arm64", "145.0.7632.109.2"),
            ("darwin-x64", "145.0.7632.109.2"),
            ("windows-x64", "146.0.7680.177.5"),
        ])
    })
}

fn http_proxy_inline_auth_min_version() -> &'static HashMap<&'static str, &'static str> {
    static MAP: OnceLock<HashMap<&'static str, &'static str>> = OnceLock::new();
    MAP.get_or_init(|| {
        HashMap::from([
            ("linux-x64", "146.0.7680.177.5"),
            ("windows-x64", "146.0.7680.177.5"),
            ("linux-arm64", "148.0.7778.215.3"),
            ("darwin-arm64", "148.0.7778.215.3"),
            ("darwin-x64", "148.0.7778.215.3"),
        ])
    })
}

/// Build stealth args with a random fingerprint seed per launch.
///
/// On macOS, skips platform/GPU spoofing — runs as a native Mac browser.
pub fn get_default_stealth_args() -> Vec<String> {
    let seed = rand::random::<u32>() % 90000 + 10000;
    let mut base = vec![
        "--no-sandbox".to_string(),
        format!("--fingerprint={seed}"),
    ];

    if cfg!(target_os = "macos") {
        base.push("--fingerprint-platform=macos".to_string());
    } else {
        // Linux/Windows: Windows fingerprint profile.
        base.push("--fingerprint-platform=windows".to_string());
    }
    base
}

/// Platforms with pre-built binaries available for download.
pub fn available_platforms() -> Vec<&'static str> {
    let mut keys: Vec<_> = platform_chromium_versions().keys().copied().collect();
    keys.sort_unstable();
    keys
}

/// Return the Chromium version for the current platform.
pub fn get_chromium_version() -> String {
    let tag = match get_platform_tag() {
        Ok(t) => t,
        Err(_) => return CHROMIUM_VERSION.to_string(),
    };
    platform_chromium_versions()
        .get(tag.as_str())
        .copied()
        .unwrap_or(CHROMIUM_VERSION)
        .to_string()
}

fn version_pin_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"^[0-9]+(?:\.[0-9]+){3,4}$").unwrap())
}

/// Return an explicit Chromium version pin from arg/env, or None.
///
/// The explicit argument wins over `CLOAKBROWSER_VERSION`. Only numeric dotted
/// versions are accepted because the value is interpolated into cache paths and
/// download URLs.
pub fn normalize_requested_version(version: Option<&str>) -> Result<Option<String>> {
    let raw = match version {
        Some(v) => Some(v.to_string()),
        None => std::env::var("CLOAKBROWSER_VERSION").ok(),
    };
    let Some(raw) = raw else {
        return Ok(None);
    };
    let normalized = raw.trim();
    if normalized.is_empty() {
        return Ok(None);
    }
    if !version_pin_re().is_match(normalized) {
        return Err(Error::InvalidVersion(
            "Invalid browser version pin. Use a full numeric Chromium version, \
             e.g. '148.0.7778.215.2'."
                .into(),
        ));
    }
    Ok(Some(normalized.to_string()))
}

/// Return the platform tag for binary download (e.g. `linux-x64`, `darwin-arm64`).
pub fn get_platform_tag() -> Result<String> {
    let arch = std::env::consts::ARCH;
    let os = std::env::consts::OS;

    let tag = match (os, arch) {
        ("linux", "x86_64") => "linux-x64",
        ("linux", "aarch64") => "linux-arm64",
        ("macos", "aarch64") => "darwin-arm64",
        ("macos", "x86_64") => "darwin-x64",
        ("windows", "x86_64") => "windows-x64",
        _ => {
            return Err(Error::UnsupportedPlatform(format!(
                "{os} {arch}. Supported: linux-x64, linux-arm64, darwin-arm64, darwin-x64, windows-x64"
            )));
        }
    };
    Ok(tag.to_string())
}

/// Return the cache directory for downloaded binaries.
/// Override with `CLOAKBROWSER_CACHE_DIR`. Default: `~/.cloakbrowser/`.
pub fn get_cache_dir() -> PathBuf {
    if let Ok(custom) = std::env::var("CLOAKBROWSER_CACHE_DIR") {
        if !custom.is_empty() {
            return PathBuf::from(custom);
        }
    }
    dirs::home_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join(".cloakbrowser")
}

/// Return the directory for a Chromium version binary.
pub fn get_binary_dir(version: Option<&str>, pro: bool) -> PathBuf {
    let v = version
        .map(|s| s.to_string())
        .unwrap_or_else(get_chromium_version);
    let suffix = if pro { "-pro" } else { "" };
    get_cache_dir().join(format!("chromium-{v}{suffix}"))
}

/// Return the expected path to the chrome executable.
pub fn get_binary_path(version: Option<&str>, pro: bool) -> PathBuf {
    let binary_dir = get_binary_dir(version, pro);
    if cfg!(target_os = "macos") {
        binary_dir
            .join("Chromium.app")
            .join("Contents")
            .join("MacOS")
            .join("Chromium")
    } else if cfg!(target_os = "windows") {
        binary_dir.join("chrome.exe")
    } else {
        binary_dir.join("chrome")
    }
}

/// Raise a clear error if no pre-built binary exists for this platform.
/// Skipped when `CLOAKBROWSER_BINARY_PATH` is set.
pub fn check_platform_available() -> Result<()> {
    if get_local_binary_override().is_some() {
        return Ok(());
    }
    let tag = get_platform_tag()?;
    if !platform_chromium_versions().contains_key(tag.as_str()) {
        let available = available_platforms().join(", ");
        return Err(Error::msg(format!(
            "\nCloakBrowser — Pre-built binaries are currently only available for: {available}.\n\n\
             To use CloakBrowser now, set CLOAKBROWSER_BINARY_PATH to a local Chromium binary."
        )));
    }
    Ok(())
}

/// True when a binary exists and is executable.
pub fn is_executable_file(path: &Path) -> bool {
    if !path.is_file() {
        return false;
    }
    if cfg!(target_os = "windows") {
        return true;
    }
    use std::os::unix::fs::PermissionsExt;
    path.metadata()
        .map(|m| m.permissions().mode() & 0o111 != 0)
        .unwrap_or(false)
}

/// Return the best available version: auto-updated if available, else platform default.
///
/// When `pro=true`, returns `None` when no cached Pro binary matches — a valid
/// Pro license must NEVER fall back to the free binary.
pub fn get_effective_version(pro: bool) -> Option<String> {
    let base = get_chromium_version();
    let cache = get_cache_dir();
    let tag = get_platform_tag().ok()?;

    if pro {
        let marker = cache.join(format!("latest_pro_version_{tag}"));
        if marker.exists() {
            if let Ok(version) = std::fs::read_to_string(&marker) {
                let version = version.trim().to_string();
                if !version.is_empty() {
                    let binary = get_binary_path(Some(&version), true);
                    if is_executable_file(&binary) {
                        return Some(version);
                    }
                }
            }
        }
        return None;
    }

    for name in [format!("latest_version_{tag}"), "latest_version".into()] {
        let marker = cache.join(&name);
        if marker.exists() {
            if let Ok(version) = std::fs::read_to_string(&marker) {
                let version = version.trim().to_string();
                if !version.is_empty() && version_newer(&version, &base) {
                    let binary = get_binary_path(Some(&version), false);
                    if binary.exists() {
                        return Some(version);
                    }
                }
            }
        }
    }
    Some(base)
}

/// Parse `"145.0.7718.0"` into component ints for comparison.
pub fn version_tuple(v: &str) -> Result<Vec<i64>> {
    v.split('.')
        .map(|x| {
            x.parse::<i64>()
                .map_err(|_| Error::InvalidVersion(format!("bad version component in {v}")))
        })
        .collect()
}

/// Return true if version `a` is strictly newer than version `b`.
pub fn version_newer(a: &str, b: &str) -> bool {
    let Ok(ta) = version_tuple(a) else {
        return false;
    };
    let Ok(tb) = version_tuple(b) else {
        return false;
    };
    let len = ta.len().max(tb.len());
    for i in 0..len {
        let va = ta.get(i).copied().unwrap_or(0);
        let vb = tb.get(i).copied().unwrap_or(0);
        if va != vb {
            return va > vb;
        }
    }
    false
}

/// Download base URL (override with `CLOAKBROWSER_DOWNLOAD_URL`).
pub fn download_base_url() -> String {
    std::env::var("CLOAKBROWSER_DOWNLOAD_URL").unwrap_or_else(|_| "https://cloakbrowser.dev".into())
}

/// Archive extension for the current platform.
pub fn get_archive_ext() -> &'static str {
    if cfg!(target_os = "windows") {
        ".zip"
    } else {
        ".tar.gz"
    }
}

/// Archive filename for a platform tag.
pub fn get_archive_name(tag: Option<&str>) -> Result<String> {
    let t = match tag {
        Some(t) => t.to_string(),
        None => get_platform_tag()?,
    };
    Ok(format!("cloakbrowser-{t}{}", get_archive_ext()))
}

/// Full download URL for the current platform's binary archive.
pub fn get_download_url(version: Option<&str>) -> Result<String> {
    let v = version
        .map(|s| s.to_string())
        .unwrap_or_else(get_chromium_version);
    Ok(format!(
        "{}/chromium-v{v}/{}",
        download_base_url(),
        get_archive_name(None)?
    ))
}

/// GitHub Releases fallback URL for the binary archive.
pub fn get_fallback_download_url(version: Option<&str>) -> Result<String> {
    let v = version
        .map(|s| s.to_string())
        .unwrap_or_else(get_chromium_version);
    Ok(format!(
        "{GITHUB_DOWNLOAD_BASE_URL}/chromium-v{v}/{}",
        get_archive_name(None)?
    ))
}

/// Pro binary download URL for an explicit version.
pub fn get_pro_download_url(version: &str) -> String {
    format!("{}/api/download/{version}", download_base_url())
}

/// Base URL for the Pro signed manifest of a version.
pub fn get_pro_manifest_base_url(version: &str) -> String {
    format!(
        "{}/releases/pro/chromium-v{version}",
        download_base_url()
    )
}

/// "Latest Pro" display download URL.
pub fn get_pro_latest_download_url() -> String {
    format!("{}/api/download/latest", download_base_url())
}

/// Local binary override via `CLOAKBROWSER_BINARY_PATH`.
pub fn get_local_binary_override() -> Option<String> {
    std::env::var("CLOAKBROWSER_BINARY_PATH")
        .ok()
        .filter(|s| !s.is_empty())
}

/// Whether headless can launch with `no_viewport` on the resolved binary.
pub fn binary_supports_headless_no_viewport(
    license_key: Option<&str>,
    browser_version: Option<&str>,
) -> bool {
    let Some(floor) = HEADLESS_NO_VIEWPORT_MIN_VERSION else {
        return false;
    };
    let declared = normalize_requested_version(browser_version).ok().flatten();
    let version = if let Some(d) = declared {
        d
    } else if get_local_binary_override().is_some() {
        return false;
    } else {
        let pro = license::resolve_license_key(license_key).is_some();
        match get_effective_version(pro) {
            Some(v) => v,
            None => return false,
        }
    };
    !version_newer(floor, &version)
}

/// Whether the resolved binary accepts inline HTTP proxy credentials.
pub fn binary_supports_http_proxy_inline_auth(
    license_key: Option<&str>,
    browser_version: Option<&str>,
) -> bool {
    let Ok(tag) = get_platform_tag() else {
        return false;
    };
    let Some(&floor) = http_proxy_inline_auth_min_version().get(tag.as_str()) else {
        return false;
    };
    let declared = normalize_requested_version(browser_version).ok().flatten();
    let version = if let Some(d) = declared {
        Some(d)
    } else if get_local_binary_override().is_some() {
        return false;
    } else {
        let pro = license::resolve_license_key(license_key).is_some();
        get_effective_version(pro)
    };
    match version {
        // Pro with no cached marker => resolve latest Pro from server, which
        // always ships the patch.
        None => true,
        Some(v) => !version_newer(floor, &v),
    }
}

/// Whether the wrapper may auto-add `--start-maximized`.
pub fn binary_supports_maximized_window(
    license_key: Option<&str>,
    browser_version: Option<&str>,
) -> bool {
    binary_supports_headless_no_viewport(license_key, browser_version)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn version_newer_basic() {
        assert!(version_newer("146.0.7680.177.5", "145.0.0.0"));
        assert!(!version_newer("145.0.0.0", "146.0.7680.177.5"));
        assert!(!version_newer("146.0.7680.177.5", "146.0.7680.177.5"));
    }

    #[test]
    fn normalize_version_valid() {
        assert_eq!(
            normalize_requested_version(Some("148.0.7778.215.2"))
                .unwrap()
                .as_deref(),
            Some("148.0.7778.215.2")
        );
    }

    #[test]
    fn normalize_version_invalid() {
        assert!(normalize_requested_version(Some("latest")).is_err());
        assert!(normalize_requested_version(Some("148")).is_err());
    }

    #[test]
    fn stealth_args_have_fingerprint() {
        let args = get_default_stealth_args();
        assert!(args.iter().any(|a| a.starts_with("--fingerprint=")));
        assert!(args.iter().any(|a| a == "--no-sandbox"));
    }

    #[test]
    fn archive_name_contains_platform() {
        let name = get_archive_name(Some("linux-x64")).unwrap();
        assert!(name.starts_with("cloakbrowser-linux-x64"));
    }
}
