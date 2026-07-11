//! Environment + binary diagnostics for the CLI (`info` / `doctor`).
//! Simplified port of .NET `Diagnostics.cs` / Python CLI info.

use std::collections::HashMap;

use crate::config;
use crate::download;
use crate::license;
use crate::version::VERSION;

/// Collect a diagnostics snapshot (no browser launch by default).
pub fn collect(quick: bool) -> HashMap<String, serde_json::Value> {
    let mut root = HashMap::new();

    let mut env = serde_json::Map::new();
    env.insert("rust".into(), VERSION.into());
    env.insert("os".into(), std::env::consts::OS.into());
    env.insert("arch".into(), std::env::consts::ARCH.into());
    env.insert(
        "platform_tag".into(),
        config::get_platform_tag()
            .map(|t| t.into())
            .unwrap_or(serde_json::Value::Null),
    );
    root.insert("environment".into(), serde_json::Value::Object(env));

    let mut binary = serde_json::Map::new();
    match download::binary_info(None) {
        Ok(info) => {
            binary.insert("version".into(), info.version.into());
            binary.insert("tier".into(), info.tier.into());
            binary.insert("path".into(), info.binary_path.into());
            binary.insert("installed".into(), info.installed.into());
            binary.insert("cache_dir".into(), info.cache_dir.into());
            binary.insert("bundled_version".into(), info.bundled_version.into());
            binary.insert("platform".into(), info.platform.into());
            binary.insert("download_url".into(), info.download_url.into());
            if let Some(ov) = config::get_local_binary_override() {
                binary.insert("override".into(), ov.into());
                binary.insert("tier".into(), "override".into());
            }
            if config::normalize_requested_version(None)
                .ok()
                .flatten()
                .is_some()
            {
                binary.insert("pinned".into(), true.into());
            }
        }
        Err(e) => {
            binary.insert("error".into(), e.to_string().into());
        }
    }
    root.insert("binary".into(), serde_json::Value::Object(binary));

    let mut launch = serde_json::Map::new();
    if quick {
        launch.insert("tested".into(), false.into());
        launch.insert("reason".into(), "skipped (--quick)".into());
    } else {
        launch.insert("tested".into(), false.into());
        launch.insert(
            "reason".into(),
            "launch probe not run (use without --quick after install)".into(),
        );
    }
    root.insert("launch".into(), serde_json::Value::Object(launch));

    let mut license_map = serde_json::Map::new();
    match license::resolve_license_key(None) {
        Some(_) => {
            license_map.insert("present".into(), true.into());
            license_map.insert("source".into(), "resolved".into());
        }
        None => {
            license_map.insert("present".into(), false.into());
        }
    }
    root.insert("license".into(), serde_json::Value::Object(license_map));

    root
}
