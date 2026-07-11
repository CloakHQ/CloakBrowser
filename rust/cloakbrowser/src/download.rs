//! Binary download and cache management for CloakBrowser.
//! Direct port of Python `cloakbrowser/download.py` / .NET `Download.cs`.

use std::collections::HashMap;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use base64::Engine;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use flate2::read::GzDecoder;
use sha2::{Digest, Sha256};
use tar::Archive;

use crate::config;
use crate::error::{Error, Result};
use crate::license;
use crate::log;
use crate::version::VERSION;

const UPDATE_CHECK_INTERVAL: u64 = 3600;
const WELCOME_FREE_INTERVAL: i64 = 3 * 24 * 3600;
const PRO_MAJOR: &str = "148";

static WRAPPER_UPDATE_CHECKED: AtomicBool = AtomicBool::new(false);

/// Info about the current binary installation.
#[derive(Debug, Clone, serde::Serialize)]
pub struct BinaryInfo {
    pub version: String,
    pub tier: String,
    pub bundled_version: String,
    pub platform: String,
    pub binary_path: String,
    pub installed: bool,
    pub cache_dir: String,
    pub download_url: String,
}

fn now_unix() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

fn http_client() -> Result<reqwest::Client> {
    Ok(reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(600))
        .user_agent(format!("cloakbrowser-rust/{VERSION}"))
        .build()?)
}

/// Whether the welcome banner should be shown.
pub fn welcome_due(marker: &Path, pro: bool) -> bool {
    if !marker.exists() {
        return true;
    }
    if pro {
        return false;
    }
    match std::fs::read_to_string(marker) {
        Ok(text) => match text.trim().parse::<i64>() {
            Ok(last) => now_unix() - last >= WELCOME_FREE_INTERVAL,
            Err(_) => true,
        },
        Err(_) => true,
    }
}

fn show_welcome(pro: bool) {
    let marker = config::get_cache_dir().join(".welcome_shown");
    if !welcome_due(&marker, pro) {
        return;
    }

    let mut msg = String::from("\n  CloakBrowser - stealth Chromium for automation\n");
    msg.push_str("  https://github.com/CloakHQ/CloakBrowser\n\n");
    if pro {
        msg.push_str(&format!(
            "  CloakBrowser Pro active (v{PRO_MAJOR}) - latest binary, newest patches.\n"
        ));
        msg.push_str("  Pro support -> support@cloakbrowser.dev\n");
    } else {
        let chromium_ver = config::get_chromium_version();
        let free_major = chromium_ver.split('.').next().unwrap_or("146");
        msg.push_str(&format!(
            "  Running free tier (v{free_major}). Pro = latest binary (v{PRO_MAJOR}) + newest anti-bot patches.\n"
        ));
        msg.push_str("  Try Pro free for 7 days -> https://cloakbrowser.dev\n");
    }
    msg.push_str("  Star us if CloakBrowser helps your project!\n\n");
    eprint!("{msg}");

    let _ = std::fs::create_dir_all(config::get_cache_dir());
    let _ = std::fs::write(&marker, now_unix().to_string());
}

/// Ensure the stealth Chromium binary is available. Download if needed.
/// Returns the path to the chrome executable.
pub async fn ensure_binary(
    license_key: Option<&str>,
    browser_version: Option<&str>,
) -> Result<PathBuf> {
    // Local override first.
    if let Some(local) = config::get_local_binary_override() {
        let path = PathBuf::from(&local);
        if !path.exists() {
            return Err(Error::BinaryNotFound(format!(
                "CLOAKBROWSER_BINARY_PATH set to '{local}' but file does not exist"
            )));
        }
        log::info(format!("Using local binary override: {local}"));
        return Ok(path);
    }

    let requested_version = config::normalize_requested_version(browser_version)?;

    // Pro license key check (custom CLOAKBROWSER_DOWNLOAD_URL overrides Pro path).
    let mut key = license::resolve_license_key(license_key);
    if std::env::var("CLOAKBROWSER_DOWNLOAD_URL")
        .map(|s| !s.is_empty())
        .unwrap_or(false)
    {
        key = None;
    }

    if let Some(ref k) = key {
        if let Some(info) = license::validate_license(k).await {
            if info.valid {
                return ensure_pro_binary(k, requested_version.as_deref())
                    .await
                    .map_err(|e| match e {
                        Error::BinaryVerification(_) => e,
                        other => Error::ProUnavailable(format!(
                            "{other}. Your license is valid but the Pro binary could not be \
                             downloaded right now. Retry in a moment. To use the free binary \
                             instead, unset CLOAKBROWSER_LICENSE_KEY."
                        )),
                    });
            } else {
                log::warning(format!(
                    "License validation failed (plan={}), using free tier",
                    info.plan
                ));
            }
        } else {
            log::warning("License validation unavailable, using free tier");
        }
    }

    config::check_platform_available()?;

    if let Some(ref pinned) = requested_version {
        let pinned_path = config::get_binary_path(Some(pinned), false);
        if config::is_executable_file(&pinned_path) {
            log::debug(format!(
                "Pinned binary found in cache: {} (version {pinned})",
                pinned_path.display()
            ));
            show_welcome(false);
            return Ok(pinned_path);
        }

        log::info(format!(
            "Stealth Chromium {pinned} not found. Downloading for {}...",
            config::get_platform_tag()?
        ));
        download_and_extract(Some(pinned)).await?;

        if !config::is_executable_file(&pinned_path) {
            return Err(Error::msg(format!(
                "Pinned download completed but binary not found at expected path: {}. \
                 This may indicate a packaging issue. Please report at \
                 https://github.com/CloakHQ/cloakbrowser/issues",
                pinned_path.display()
            )));
        }
        show_welcome(false);
        return Ok(pinned_path);
    }

    // Free tier never returns null (bundled base is the floor).
    let effective = config::get_effective_version(false)
        .unwrap_or_else(config::get_chromium_version);
    let binary_path = config::get_binary_path(Some(&effective), false);

    if config::is_executable_file(&binary_path) {
        log::debug(format!(
            "Binary found in cache: {} (version {effective})",
            binary_path.display()
        ));
        show_welcome(false);
        maybe_trigger_update_check();
        return Ok(binary_path);
    }

    let platform_version = config::get_chromium_version();
    if effective != platform_version {
        let fallback = config::get_binary_path(None, false);
        if config::is_executable_file(&fallback) {
            log::debug(format!("Binary found in cache: {}", fallback.display()));
            maybe_trigger_update_check();
            return Ok(fallback);
        }
    }

    log::info(format!(
        "Stealth Chromium {platform_version} not found. Downloading for {}...",
        config::get_platform_tag()?
    ));
    download_and_extract(None).await?;

    let binary_path = config::get_binary_path(None, false);
    if !binary_path.exists() {
        return Err(Error::msg(format!(
            "Download completed but binary not found at expected path: {}. \
             This may indicate a packaging issue. Please report at \
             https://github.com/CloakHQ/cloakbrowser/issues",
            binary_path.display()
        )));
    }

    maybe_trigger_update_check();
    Ok(binary_path)
}

async fn ensure_pro_binary(
    license_key: &str,
    requested_version: Option<&str>,
) -> Result<PathBuf> {
    if let Some(pinned) = requested_version {
        let pinned_path = config::get_binary_path(Some(pinned), true);
        if config::is_executable_file(&pinned_path) {
            log::debug(format!(
                "Pinned Pro binary found in cache: {} (version {pinned})",
                pinned_path.display()
            ));
            show_welcome(true);
            return Ok(pinned_path);
        }

        log::info(format!(
            "Downloading Pro Chromium {pinned} for {}...",
            config::get_platform_tag()?
        ));
        download_pro_binary(pinned, license_key).await?;

        let pinned_path = config::get_binary_path(Some(pinned), true);
        if !config::is_executable_file(&pinned_path) {
            return Err(Error::msg(format!(
                "Pro download completed but binary not found at: {}",
                pinned_path.display()
            )));
        }
        show_welcome(true);
        return Ok(pinned_path);
    }

    let effective = config::get_effective_version(true);
    let frozen = std::env::var("CLOAKBROWSER_AUTO_UPDATE")
        .map(|v| v.eq_ignore_ascii_case("false"))
        .unwrap_or(false);

    if frozen && pro_binary_ready(effective.as_deref()) {
        show_welcome(true);
        return Ok(config::get_binary_path(effective.as_deref(), true));
    }

    let latest = license::get_pro_latest_version().await;

    let version = if let Some(ref latest_v) = latest {
        if !pro_binary_ready(effective.as_deref())
            || effective
                .as_ref()
                .map(|e| config::version_newer(latest_v, e))
                .unwrap_or(true)
        {
            Some(latest_v.clone())
        } else {
            effective.clone()
        }
    } else {
        effective.clone()
    };

    let Some(version) = version else {
        return Err(Error::msg(
            "Could not determine latest Pro version from server",
        ));
    };

    let ready_path = config::get_binary_path(Some(&version), true);
    if config::is_executable_file(&ready_path) {
        if Some(&version) != effective.as_ref() {
            write_pro_version_marker(&version);
        }
        log::debug(format!(
            "Pro binary found in cache: {} (version {version})",
            ready_path.display()
        ));
        show_welcome(true);
        return Ok(ready_path);
    }

    match download_pro_binary(&version, license_key).await {
        Ok(()) => {}
        Err(e @ Error::BinaryVerification(_)) => return Err(e),
        Err(e) => {
            if pro_binary_ready(effective.as_deref()) {
                log::warning(format!(
                    "Pro update to {version} failed; launching cached Pro binary {}",
                    effective.as_deref().unwrap_or("?")
                ));
                show_welcome(true);
                return Ok(config::get_binary_path(effective.as_deref(), true));
            }
            return Err(e);
        }
    }

    let downloaded = config::get_binary_path(Some(&version), true);
    if !downloaded.exists() {
        return Err(Error::msg(format!(
            "Pro download completed but binary not found at: {}",
            downloaded.display()
        )));
    }

    write_pro_version_marker(&version);
    show_welcome(true);
    Ok(downloaded)
}

fn pro_binary_ready(version: Option<&str>) -> bool {
    match version {
        Some(v) if !v.is_empty() => {
            config::is_executable_file(&config::get_binary_path(Some(v), true))
        }
        _ => false,
    }
}

fn write_pro_version_marker(version: &str) {
    let Ok(tag) = config::get_platform_tag() else {
        return;
    };
    let marker = config::get_cache_dir().join(format!("latest_pro_version_{tag}"));
    let _ = std::fs::create_dir_all(config::get_cache_dir());
    let tmp = marker.with_extension("tmp");
    if std::fs::write(&tmp, version).is_ok() {
        let _ = std::fs::rename(&tmp, &marker);
    }
}

fn write_version_marker(version: &str) {
    let Ok(tag) = config::get_platform_tag() else {
        return;
    };
    let marker = config::get_cache_dir().join(format!("latest_version_{tag}"));
    let _ = std::fs::create_dir_all(config::get_cache_dir());
    let tmp = marker.with_extension("tmp");
    if std::fs::write(&tmp, version).is_ok() {
        let _ = std::fs::rename(&tmp, &marker);
    }
}

async fn download_and_extract(version: Option<&str>) -> Result<()> {
    let primary_url = config::get_download_url(version)?;
    let fallback_url = config::get_fallback_download_url(version)?;
    let binary_dir = config::get_binary_dir(version, false);
    let binary_path = config::get_binary_path(version, false);

    if let Some(parent) = binary_dir.parent() {
        std::fs::create_dir_all(parent)?;
    }

    let tmp_path = std::env::temp_dir().join(format!(
        "cloakbrowser-{}{}",
        uuid_like(),
        config::get_archive_ext()
    ));

    let result = async {
        match download_file(&primary_url, &tmp_path, None).await {
            Ok(()) => {}
            Err(primary_err) => {
                if std::env::var("CLOAKBROWSER_DOWNLOAD_URL").is_ok() {
                    return Err(primary_err);
                }
                log::warning(format!(
                    "Primary download failed ({primary_err}), trying GitHub Releases..."
                ));
                download_file(&fallback_url, &tmp_path, None).await?;
            }
        }

        verify_download_checksum(&tmp_path, version).await?;
        extract_archive(&tmp_path, &binary_dir, Some(&binary_path))?;
        show_welcome(false);
        Ok(())
    }
    .await;

    let _ = std::fs::remove_file(&tmp_path);
    result
}

async fn download_pro_binary(version: &str, license_key: &str) -> Result<()> {
    let download_url = config::get_pro_download_url(version);
    let binary_dir = config::get_binary_dir(Some(version), true);
    let binary_path = config::get_binary_path(Some(version), true);
    let platform_tag = config::get_platform_tag()?;

    if let Some(parent) = binary_dir.parent() {
        std::fs::create_dir_all(parent)?;
    }

    let tmp_path = std::env::temp_dir().join(format!(
        "cloakbrowser-{}{}",
        uuid_like(),
        config::get_archive_ext()
    ));

    let mut headers = HashMap::new();
    headers.insert("Authorization".into(), format!("Bearer {license_key}"));
    headers.insert("X-Platform".into(), platform_tag);

    let result = async {
        download_file(&download_url, &tmp_path, Some(&headers)).await?;
        verify_pro_download(&tmp_path, version).await?;
        extract_archive(&tmp_path, &binary_dir, Some(&binary_path))?;
        Ok(())
    }
    .await;

    let _ = std::fs::remove_file(&tmp_path);
    result
}

fn uuid_like() -> String {
    format!("{:x}", rand::random::<u128>())
}

async fn download_file(
    url: &str,
    dest: &Path,
    headers: Option<&HashMap<String, String>>,
) -> Result<()> {
    log::info(format!("Downloading from {url}"));
    let client = http_client()?;
    let mut req = client.get(url);
    if let Some(h) = headers {
        for (k, v) in h {
            req = req.header(k.as_str(), v.as_str());
        }
    }
    let resp = req.send().await?;
    if !resp.status().is_success() {
        return Err(Error::msg(format!(
            "Download failed: HTTP {} {}",
            resp.status().as_u16(),
            resp.status().canonical_reason().unwrap_or("")
        )));
    }

    let total = resp.content_length().unwrap_or(0);
    let bytes = resp.bytes().await?;
    let mut file = std::fs::File::create(dest)?;
    file.write_all(&bytes)?;

    if total > 0 {
        log::info(format!(
            "Download progress: 100% ({}/{} MB)",
            bytes.len() as u64 / (1024 * 1024),
            total / (1024 * 1024)
        ));
    }

    log::info(format!(
        "Download complete: {} MB",
        dest.metadata().map(|m| m.len() / (1024 * 1024)).unwrap_or(0)
    ));
    Ok(())
}

// ---------------------------------------------------------------------------
// Verification
// ---------------------------------------------------------------------------

/// Verify free-tier download integrity and authenticity.
pub async fn verify_download_checksum(file_path: &Path, version: Option<&str>) -> Result<()> {
    let tarball_name = config::get_archive_name(None)?;

    if std::env::var("CLOAKBROWSER_DOWNLOAD_URL").is_ok() {
        // Self-hosted: plain same-origin checksum; skippable.
        if std::env::var("CLOAKBROWSER_SKIP_CHECKSUM")
            .map(|v| v.eq_ignore_ascii_case("true"))
            .unwrap_or(false)
        {
            log::warning(
                "CLOAKBROWSER_SKIP_CHECKSUM set - skipping verification for custom download URL",
            );
            return Ok(());
        }
        let Some(checksums) = fetch_checksums(version).await else {
            log::warning(
                "SHA256SUMS not available from custom URL - skipping checksum verification",
            );
            return Ok(());
        };
        let Some(expected) = checksums.get(&tarball_name) else {
            log::warning(format!(
                "SHA256SUMS found but no entry for {tarball_name} - skipping verification"
            ));
            return Ok(());
        };
        return verify_checksum(file_path, expected);
    }

    // Official path: non-bypassable Ed25519 signature.
    let Some((manifest_bytes, sig_bytes)) = fetch_signed_manifest(version).await else {
        return Err(Error::msg(
            "Could not fetch a signed SHA256SUMS (SHA256SUMS + SHA256SUMS.sig) \
             for this release - refusing to use an unverified binary. \
             Retry, or report at https://github.com/CloakHQ/cloakbrowser/issues",
        ));
    };

    verify_signature(&manifest_bytes, &sig_bytes)?;
    let manifest_text = String::from_utf8_lossy(&manifest_bytes);

    let requested = version
        .map(|s| s.to_string())
        .unwrap_or_else(config::get_chromium_version);
    let declared = parse_manifest_version(&manifest_text);
    if declared.as_deref() != Some(requested.as_str()) {
        return Err(Error::msg(format!(
            "Version mismatch in signed SHA256SUMS: requested {requested}, \
             manifest declares {}. Refusing (possible downgrade).",
            declared.as_deref().unwrap_or("none")
        )));
    }

    let checksums = parse_checksums(&manifest_text);
    let Some(expected) = checksums.get(&tarball_name) else {
        return Err(Error::msg(format!(
            "Signature-verified SHA256SUMS has no entry for {tarball_name} - \
             cannot confirm binary integrity."
        )));
    };
    verify_checksum(file_path, expected)
}

/// Verify a Pro archive with the same non-bypassable Ed25519 signature check.
pub async fn verify_pro_download(file_path: &Path, version: &str) -> Result<()> {
    let base_url = config::get_pro_manifest_base_url(version);
    let client = http_client()?;

    let (manifest_bytes, sig_bytes) = match async {
        let manifest = client
            .get(format!("{base_url}/SHA256SUMS"))
            .send()
            .await?
            .error_for_status()?
            .bytes()
            .await?;
        let sig = client
            .get(format!("{base_url}/SHA256SUMS.sig"))
            .send()
            .await?
            .error_for_status()?
            .bytes()
            .await?;
        Ok::<_, Error>((manifest.to_vec(), sig.to_vec()))
    }
    .await
    {
        Ok(pair) => pair,
        Err(e) => {
            return Err(Error::msg(format!(
                "Could not fetch the signed SHA256SUMS for Pro {version} ({e})"
            )));
        }
    };

    if let Err(e) = verify_signature(&manifest_bytes, &sig_bytes) {
        return Err(Error::BinaryVerification(e.to_string()));
    }

    let manifest_text = String::from_utf8_lossy(&manifest_bytes);
    let declared = parse_manifest_version(&manifest_text);
    if declared.as_deref() != Some(version) {
        return Err(Error::BinaryVerification(format!(
            "Version mismatch in signed Pro SHA256SUMS: requested {version}, \
             manifest declares {}. Refusing (possible downgrade).",
            declared.as_deref().unwrap_or("none")
        )));
    }

    let tarball_name = config::get_archive_name(None)?;
    let checksums = parse_checksums(&manifest_text);
    let Some(expected) = checksums.get(&tarball_name) else {
        return Err(Error::BinaryVerification(format!(
            "Signature-verified Pro SHA256SUMS has no entry for {tarball_name} - \
             cannot confirm binary integrity."
        )));
    };
    verify_checksum(file_path, expected).map_err(|e| Error::BinaryVerification(e.to_string()))
}

async fn fetch_signed_manifest(version: Option<&str>) -> Option<(Vec<u8>, Vec<u8>)> {
    let v = version
        .map(|s| s.to_string())
        .unwrap_or_else(config::get_chromium_version);
    let bases = [
        format!("{}/chromium-v{v}", config::download_base_url()),
        format!("{}/chromium-v{v}", config::GITHUB_DOWNLOAD_BASE_URL),
    ];
    let client = http_client().ok()?;
    for b in bases {
        let Ok(manifest_resp) = client.get(format!("{b}/SHA256SUMS")).send().await else {
            continue;
        };
        if !manifest_resp.status().is_success() {
            continue;
        }
        let Ok(manifest_bytes) = manifest_resp.bytes().await else {
            continue;
        };
        let Ok(sig_resp) = client.get(format!("{b}/SHA256SUMS.sig")).send().await else {
            continue;
        };
        if !sig_resp.status().is_success() {
            continue;
        }
        let Ok(sig_bytes) = sig_resp.bytes().await else {
            continue;
        };
        return Some((manifest_bytes.to_vec(), sig_bytes.to_vec()));
    }
    None
}

async fn fetch_checksums(version: Option<&str>) -> Option<HashMap<String, String>> {
    let v = version
        .map(|s| s.to_string())
        .unwrap_or_else(config::get_chromium_version);
    let has_custom = std::env::var("CLOAKBROWSER_DOWNLOAD_URL").is_ok();
    let mut urls = vec![format!(
        "{}/chromium-v{v}/SHA256SUMS",
        config::download_base_url()
    )];
    if !has_custom {
        urls.push(format!(
            "{}/chromium-v{v}/SHA256SUMS",
            config::GITHUB_DOWNLOAD_BASE_URL
        ));
    }
    let client = http_client().ok()?;
    for url in urls {
        let Ok(resp) = client.get(&url).send().await else {
            continue;
        };
        if !resp.status().is_success() {
            continue;
        }
        let Ok(text) = resp.text().await else {
            continue;
        };
        return Some(parse_checksums(&text));
    }
    None
}

/// Read the `version=<v>` line from a signed manifest.
pub fn parse_manifest_version(text: &str) -> Option<String> {
    for line in text.replace("\r\n", "\n").split('\n') {
        let line = line.trim();
        if let Some(rest) = line.strip_prefix("version=") {
            return Some(rest.trim().to_string());
        }
    }
    None
}

/// Parse SHA256SUMS format: `<64-hex sha256>  filename` per line.
pub fn parse_checksums(text: &str) -> HashMap<String, String> {
    let mut result = HashMap::new();
    for raw_line in text.trim().replace("\r\n", "\n").split('\n') {
        let parts: Vec<&str> = raw_line.split_whitespace().collect();
        if parts.len() < 2 {
            continue;
        }
        let hash_val = parts[0].to_lowercase();
        if hash_val.len() != 64 || !hash_val.chars().all(|c| c.is_ascii_hexdigit()) {
            continue;
        }
        let name = parts[1].trim_start_matches('*');
        result.insert(name.to_string(), hash_val);
    }
    result
}

/// Verify a detached Ed25519 signature over the raw manifest bytes.
/// `sig_b64` is base64 of the 64-byte raw signature (as stored in SHA256SUMS.sig).
pub fn verify_signature(manifest_bytes: &[u8], sig_b64: &[u8]) -> Result<()> {
    let sig_text = String::from_utf8_lossy(sig_b64).trim().to_string();
    let signature = base64::engine::general_purpose::STANDARD
        .decode(sig_text.as_bytes())
        .map_err(|e| Error::msg(format!("Malformed SHA256SUMS.sig (not valid base64): {e}")))?;

    let sig = Signature::from_slice(&signature).map_err(|_| {
        Error::msg(
            "SHA256SUMS signature verification failed - malformed signature. \
             Report at https://github.com/CloakHQ/cloakbrowser/issues",
        )
    })?;

    for pubkey_b64 in config::BINARY_SIGNING_PUBKEYS {
        let Ok(pub_bytes) = base64::engine::general_purpose::STANDARD.decode(pubkey_b64.as_bytes())
        else {
            continue;
        };
        if pub_bytes.len() != 32 {
            continue;
        }
        let Ok(key_bytes): std::result::Result<[u8; 32], _> = pub_bytes.try_into() else {
            continue;
        };
        let Ok(vk) = VerifyingKey::from_bytes(&key_bytes) else {
            continue;
        };
        if vk.verify(manifest_bytes, &sig).is_ok() {
            log::info("SHA256SUMS signature verified: Ed25519 OK");
            return Ok(());
        }
    }

    Err(Error::msg(
        "SHA256SUMS signature verification failed - no pinned key validated the \
         manifest. The binary's authenticity could not be confirmed. \
         Report at https://github.com/CloakHQ/cloakbrowser/issues",
    ))
}

fn verify_checksum(file_path: &Path, expected_hash: &str) -> Result<()> {
    let mut file = std::fs::File::open(file_path)?;
    let mut hasher = Sha256::new();
    let mut buf = [0u8; 8192];
    loop {
        let n = file.read(&mut buf)?;
        if n == 0 {
            break;
        }
        hasher.update(&buf[..n]);
    }
    let actual = hex::encode(hasher.finalize());
    if actual != expected_hash.to_lowercase() {
        return Err(Error::msg(format!(
            "Checksum verification failed!\n  Expected: {expected_hash}\n  Got:      {actual}\n  \
             File may be corrupted or tampered with. Please retry or report at \
             https://github.com/CloakHQ/cloakbrowser/issues"
        )));
    }
    log::info("Checksum verified: SHA-256 OK");
    Ok(())
}

// ---------------------------------------------------------------------------
// Extraction
// ---------------------------------------------------------------------------

fn extract_archive(archive_path: &Path, dest_dir: &Path, binary_path: Option<&Path>) -> Result<()> {
    log::info(format!("Extracting to {}", dest_dir.display()));

    if dest_dir.exists() {
        std::fs::remove_dir_all(dest_dir)?;
    }
    std::fs::create_dir_all(dest_dir)?;

    if archive_path
        .extension()
        .and_then(|e| e.to_str())
        .map(|e| e.eq_ignore_ascii_case("zip"))
        .unwrap_or(false)
        || archive_path
            .to_string_lossy()
            .ends_with(".zip")
    {
        extract_zip(archive_path, dest_dir)?;
    } else {
        extract_tar(archive_path, dest_dir)?;
    }

    flatten_single_subdir(dest_dir)?;

    let bp = binary_path
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| config::get_binary_path(None, false));
    if bp.exists() {
        make_executable(&bp)?;
    }

    #[cfg(target_os = "macos")]
    remove_quarantine(dest_dir);

    if bp.exists() {
        log::info(format!("Binary ready: {}", bp.display()));
    }
    Ok(())
}

/// Resolve an archive entry to an absolute path under `destination_dir`,
/// guarding against path-traversal / zip-slip.
pub fn resolve_safe_entry_path(destination_dir: &Path, entry_name: &str) -> Result<PathBuf> {
    let dest_full = std::fs::canonicalize(destination_dir).unwrap_or_else(|_| {
        if destination_dir.is_absolute() {
            destination_dir.to_path_buf()
        } else {
            std::env::current_dir()
                .unwrap_or_else(|_| PathBuf::from("."))
                .join(destination_dir)
        }
    });
    // Normalize without requiring the path to exist yet for members.
    let dest_full = path_clean(&dest_full);
    let dest_prefix = if dest_full.as_os_str().to_string_lossy().ends_with('/') {
        dest_full.clone()
    } else {
        PathBuf::from(format!(
            "{}{}",
            dest_full.display(),
            std::path::MAIN_SEPARATOR
        ))
    };

    let member = path_clean(&dest_full.join(entry_name));
    let member_str = member.to_string_lossy();
    let dest_str = dest_full.to_string_lossy();
    let prefix_str = dest_prefix.to_string_lossy();

    if member_str != dest_str && !member_str.starts_with(prefix_str.as_ref()) {
        return Err(Error::msg(format!(
            "Archive contains path traversal: {entry_name}"
        )));
    }
    Ok(member)
}

fn path_clean(path: &Path) -> PathBuf {
    let mut out = PathBuf::new();
    for comp in path.components() {
        match comp {
            std::path::Component::ParentDir => {
                out.pop();
            }
            std::path::Component::CurDir => {}
            other => out.push(other.as_os_str()),
        }
    }
    out
}

fn extract_tar(archive_path: &Path, dest_dir: &Path) -> Result<()> {
    let file = std::fs::File::open(archive_path)?;
    let gz = GzDecoder::new(file);
    let mut archive = Archive::new(gz);

    for entry in archive.entries()? {
        let mut entry = entry?;
        let path = entry.path()?.into_owned();
        let name = path.to_string_lossy().to_string();

        // Symlinks — allow relative only (macOS .app bundles need them).
        if entry.header().entry_type().is_symlink() {
            if let Ok(Some(link)) = entry.link_name() {
                let link = link.to_string_lossy();
                if link.starts_with('/') || link.split('/').any(|p| p == "..") {
                    log::warning(format!("Skipping suspicious symlink: {name} -> {link}"));
                    continue;
                }
            }
            let link_path = dest_dir.join(&path);
            if let Some(parent) = link_path.parent() {
                std::fs::create_dir_all(parent)?;
            }
            entry.unpack(&link_path)?;
            continue;
        }

        let member_path = resolve_safe_entry_path(dest_dir, &name)?;
        if entry.header().entry_type().is_dir() {
            std::fs::create_dir_all(&member_path)?;
            continue;
        }
        if let Some(parent) = member_path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        entry.unpack(&member_path)?;
    }
    Ok(())
}

fn extract_zip(archive_path: &Path, dest_dir: &Path) -> Result<()> {
    let file = std::fs::File::open(archive_path)?;
    let mut archive = zip::ZipArchive::new(file)
        .map_err(|e| Error::msg(format!("Failed to open zip archive: {e}")))?;

    // Validate all entries first.
    for i in 0..archive.len() {
        let entry = archive
            .by_index(i)
            .map_err(|e| Error::msg(format!("zip entry error: {e}")))?;
        let name = entry.name().to_string();
        resolve_safe_entry_path(dest_dir, &name)?;
    }

    for i in 0..archive.len() {
        let mut entry = archive
            .by_index(i)
            .map_err(|e| Error::msg(format!("zip entry error: {e}")))?;
        let name = entry.name().to_string();
        let outpath = resolve_safe_entry_path(dest_dir, &name)?;
        if entry.is_dir() {
            std::fs::create_dir_all(&outpath)?;
        } else {
            if let Some(parent) = outpath.parent() {
                std::fs::create_dir_all(parent)?;
            }
            let mut outfile = std::fs::File::create(&outpath)?;
            std::io::copy(&mut entry, &mut outfile)?;
        }
    }
    Ok(())
}

fn flatten_single_subdir(dest_dir: &Path) -> Result<()> {
    let entries: Vec<_> = std::fs::read_dir(dest_dir)?
        .filter_map(|e| e.ok())
        .collect();
    if entries.len() != 1 {
        return Ok(());
    }
    let entry = &entries[0];
    let path = entry.path();
    if !path.is_dir() {
        return Ok(());
    }
    let name = path
        .file_name()
        .and_then(|n| n.to_str())
        .unwrap_or("")
        .to_string();
    if name.ends_with(".app") {
        log::debug(format!("Keeping .app bundle intact: {name}"));
        return Ok(());
    }
    log::debug(format!("Flattening single subdirectory: {name}"));
    for item in std::fs::read_dir(&path)? {
        let item = item?;
        let target = dest_dir.join(item.file_name());
        std::fs::rename(item.path(), target)?;
    }
    std::fs::remove_dir_all(&path)?;
    Ok(())
}

fn make_executable(path: &Path) -> Result<()> {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = std::fs::metadata(path)?.permissions();
        perms.set_mode(perms.mode() | 0o111);
        std::fs::set_permissions(path, perms)?;
    }
    let _ = path;
    Ok(())
}

#[cfg(target_os = "macos")]
fn remove_quarantine(path: &Path) {
    let _ = std::process::Command::new("xattr")
        .args(["-cr"])
        .arg(path)
        .output();
    log::debug(format!(
        "Removed quarantine attributes from {}",
        path.display()
    ));
}

/// Remove all cached binaries. Forces re-download on next launch.
pub fn clear_cache() -> Result<()> {
    let cache_dir = config::get_cache_dir();
    if cache_dir.exists() {
        std::fs::remove_dir_all(&cache_dir)?;
        log::info(format!("Cache cleared: {}", cache_dir.display()));
    }
    Ok(())
}

/// Return info about the current binary installation.
pub fn binary_info(browser_version: Option<&str>) -> Result<BinaryInfo> {
    let requested = config::normalize_requested_version(browser_version)?;
    let pro_version = requested
        .clone()
        .or_else(|| config::get_effective_version(true));
    let pro = pro_binary_ready(pro_version.as_deref());

    let (effective, binary_path, cache_pro) = if pro {
        let v = pro_version.clone().unwrap_or_default();
        (
            v.clone(),
            config::get_binary_path(Some(&v), true),
            true,
        )
    } else {
        let v = requested
            .clone()
            .or_else(|| config::get_effective_version(false))
            .unwrap_or_else(config::get_chromium_version);
        (v.clone(), config::get_binary_path(Some(&v), false), false)
    };

    Ok(BinaryInfo {
        version: effective.clone(),
        tier: if pro { "pro" } else { "free" }.into(),
        bundled_version: config::CHROMIUM_VERSION.into(),
        platform: config::get_platform_tag()?,
        binary_path: binary_path.display().to_string(),
        installed: binary_path.exists(),
        cache_dir: config::get_binary_dir(Some(&effective), cache_pro)
            .display()
            .to_string(),
        download_url: if pro {
            config::get_pro_latest_download_url()
        } else {
            config::get_download_url(Some(&effective))?
        },
    })
}

/// Manually check for a newer Chromium version. Returns new version or null.
pub async fn check_for_update() -> Result<Option<String>> {
    let latest = get_latest_chromium_version().await?;
    let Some(latest) = latest else {
        return Ok(None);
    };
    if !config::version_newer(&latest, &config::get_chromium_version()) {
        return Ok(None);
    }

    let binary_dir = config::get_binary_dir(Some(&latest), false);
    if binary_dir.exists() {
        write_version_marker(&latest);
        return Ok(Some(latest));
    }

    log::info(format!("Downloading update: Chromium {latest}..."));
    download_and_extract(Some(&latest)).await?;
    write_version_marker(&latest);
    Ok(Some(latest))
}

async fn get_latest_chromium_version() -> Result<Option<String>> {
    let client = http_client()?;
    // Prefer cloakbrowser.dev version endpoint when available.
    let url = format!(
        "{}/api/download/version?tier=free",
        config::download_base_url()
    );
    if let Ok(resp) = client
        .get(&url)
        .header("X-Platform", config::get_platform_tag()?)
        .send()
        .await
    {
        if resp.status().is_success() {
            if let Ok(data) = resp.json::<serde_json::Value>().await {
                if let Some(v) = data.get("version").and_then(|v| v.as_str()) {
                    return Ok(Some(v.to_string()));
                }
            }
        }
    }

    // GitHub releases fallback: find newest chromium-v* tag.
    let resp = client
        .get(config::GITHUB_API_URL)
        .header("Accept", "application/vnd.github+json")
        .send()
        .await?;
    if !resp.status().is_success() {
        return Ok(None);
    }
    let releases: Vec<serde_json::Value> = resp.json().await?;
    let mut best: Option<String> = None;
    for rel in releases {
        if let Some(tag) = rel.get("tag_name").and_then(|t| t.as_str()) {
            if let Some(v) = tag.strip_prefix("chromium-v") {
                if best
                    .as_ref()
                    .map(|b| config::version_newer(v, b))
                    .unwrap_or(true)
                {
                    best = Some(v.to_string());
                }
            }
        }
    }
    Ok(best)
}

fn maybe_trigger_update_check() {
    if WRAPPER_UPDATE_CHECKED.swap(true, Ordering::SeqCst) {
        return;
    }
    if std::env::var("CLOAKBROWSER_AUTO_UPDATE")
        .map(|v| v.eq_ignore_ascii_case("false"))
        .unwrap_or(false)
    {
        return;
    }
    // Fire-and-forget background check.
    tokio::spawn(async {
        // Rate-limit via marker mtime.
        let Ok(tag) = config::get_platform_tag() else {
            return;
        };
        let marker = config::get_cache_dir().join(format!(".last_update_check_{tag}"));
        if marker.exists() {
            if let Ok(meta) = marker.metadata() {
                if let Ok(modified) = meta.modified() {
                    if let Ok(age) = SystemTime::now().duration_since(modified) {
                        if age.as_secs() < UPDATE_CHECK_INTERVAL {
                            return;
                        }
                    }
                }
            }
        }
        let _ = std::fs::create_dir_all(config::get_cache_dir());
        let _ = std::fs::write(&marker, now_unix().to_string());

        if let Ok(Some(latest)) = check_for_update().await {
            log::info(format!("Auto-updated stealth Chromium to {latest}"));
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_checksums_basic() {
        let text = "\
abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789  cloakbrowser-linux-x64.tar.gz
version=146.0.7680.177.5
# comment
";
        let map = parse_checksums(text);
        assert_eq!(
            map.get("cloakbrowser-linux-x64.tar.gz").map(String::as_str),
            Some("abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789")
        );
    }

    #[test]
    fn parse_manifest_version_line() {
        let text = "version=146.0.7680.177.5\nabc  file.tar.gz\n";
        assert_eq!(
            parse_manifest_version(text).as_deref(),
            Some("146.0.7680.177.5")
        );
    }

    #[test]
    fn zip_slip_blocked() {
        let dest = std::env::temp_dir().join("cloak-zipslip-test");
        let _ = std::fs::create_dir_all(&dest);
        let err = resolve_safe_entry_path(&dest, "../evil").unwrap_err();
        assert!(err.to_string().contains("path traversal"));
        let _ = std::fs::remove_dir_all(&dest);
    }

    #[test]
    fn welcome_due_missing_marker() {
        let p = std::env::temp_dir().join("cloak-welcome-missing");
        let _ = std::fs::remove_file(&p);
        assert!(welcome_due(&p, false));
        assert!(welcome_due(&p, true));
    }
}
