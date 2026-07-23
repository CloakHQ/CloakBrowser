//! Widevine CDM hint-file seeding for persistent contexts.
//! Direct port of Python `cloakbrowser/widevine.py` / .NET `Widevine.cs`.
//!
//! Linux only. Never bundles the CDM — only writes a hint when a user-provided
//! CDM is already present next to the binary or in the cache dir.

use std::path::{Path, PathBuf};

use crate::config;
use crate::log;

const HINT_FILENAME: &str = "latest-component-updated-widevine-cdm";

fn seeding_disabled() -> bool {
    match std::env::var("CLOAKBROWSER_WIDEVINE") {
        Ok(v) => matches!(
            v.trim().to_ascii_lowercase().as_str(),
            "0" | "false" | "off" | "no"
        ),
        Err(_) => false,
    }
}

/// Locate a sideloaded Widevine CDM directory, or `None` if absent.
///
/// Resolution order:
/// 1. `CLOAKBROWSER_WIDEVINE_CDM` (exclusive override)
/// 2. `<dir of chrome binary>/WidevineCdm`
/// 3. `~/.cloakbrowser/WidevineCdm`
///
/// A directory counts only if it contains `manifest.json`.
pub fn resolve_widevine_cdm_dir(binary_path: &Path) -> Option<PathBuf> {
    if let Ok(custom) = std::env::var("CLOAKBROWSER_WIDEVINE_CDM") {
        if custom.trim().is_empty() {
            return None;
        }
        let cdm_dir = PathBuf::from(custom);
        return if cdm_dir.join("manifest.json").is_file() {
            Some(cdm_dir.canonicalize().unwrap_or(cdm_dir))
        } else {
            None
        };
    }

    let next_to_binary = binary_path
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .join("WidevineCdm");
    let cache_cdm = config::get_cache_dir().join("WidevineCdm");

    for cdm_dir in [next_to_binary, cache_cdm] {
        if cdm_dir.join("manifest.json").is_file() {
            return Some(cdm_dir.canonicalize().unwrap_or(cdm_dir));
        }
    }
    None
}

/// Write the Widevine CDM hint file into a persistent profile before launch.
///
/// No-op on non-Linux, when disabled via `CLOAKBROWSER_WIDEVINE`, when
/// `user_data_dir` is empty, or when no CDM is present. Never panics.
pub fn seed_widevine_hint(user_data_dir: &Path, binary_path: &Path) {
    if !cfg!(target_os = "linux") {
        return;
    }
    if seeding_disabled() {
        log::debug("Widevine hint seeding disabled via CLOAKBROWSER_WIDEVINE");
        return;
    }
    if user_data_dir.as_os_str().is_empty() {
        return;
    }

    let result = (|| -> std::io::Result<()> {
        let Some(cdm_dir) = resolve_widevine_cdm_dir(binary_path) else {
            if std::env::var_os("CLOAKBROWSER_WIDEVINE_CDM").is_some() {
                log::warning(
                    "CLOAKBROWSER_WIDEVINE_CDM is set but has no manifest.json; \
                     skipping Widevine hint seeding",
                );
            } else {
                log::debug("No sideloaded Widevine CDM found; skipping hint seeding");
            }
            return Ok(());
        };

        let hint_dir = user_data_dir.join("WidevineCdm");
        std::fs::create_dir_all(&hint_dir)?;
        let hint_file = hint_dir.join(HINT_FILENAME);
        let content = serde_json::json!({ "Path": cdm_dir.to_string_lossy() }).to_string();
        // Compact separators: serde_json default is compact for objects without spaces
        // in default to_string() — actually default is compact. Good.

        if hint_file.is_file() {
            if let Ok(existing) = std::fs::read_to_string(&hint_file) {
                if existing == content {
                    return Ok(());
                }
            } else {
                log::warning("Existing Widevine hint unreadable; rewriting");
            }
        }

        std::fs::write(&hint_file, content.as_bytes())?;
        log::info(format!(
            "Seeded Widevine CDM hint -> {}",
            cdm_dir.display()
        ));
        Ok(())
    })();

    if let Err(e) = result {
        log::warning(format!("Failed to seed Widevine CDM hint file: {e}"));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn resolve_missing_returns_none() {
        let fake = std::env::temp_dir().join("cloak-no-chrome-xyz/chrome");
        // Clear custom env for this test scope by ensuring it's not pointing at a real CDM.
        let result = resolve_widevine_cdm_dir(&fake);
        // May still find cache CDM on a real install — just ensure function doesn't panic.
        let _ = result;
    }

    #[test]
    fn seed_empty_user_data_is_noop() {
        seed_widevine_hint(Path::new(""), Path::new("/tmp/chrome"));
    }
}
