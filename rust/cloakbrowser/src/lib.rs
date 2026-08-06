//! # CloakBrowser for Rust
//!
//! Stealth Chromium that passes bot-detection tests. Thin wrapper around a
//! closed-source, source-level patched Chromium binary, driven via
//! [`playwright-rs`](https://crates.io/crates/playwright-rs).
//!
//! Direct port of the Python / JavaScript / .NET wrappers in this monorepo.
//!
//! ## Quick start
//!
//! ```no_run
//! use cloakbrowser::{launch, LaunchOptions};
//!
//! #[tokio::main]
//! async fn main() -> cloakbrowser::Result<()> {
//!     let browser = launch(LaunchOptions {
//!         headless: true,
//!         ..Default::default()
//!     }).await?;
//!
//!     let page = browser.new_page().await?;
//!     let _ = page.goto("https://example.com", None).await;
//!     println!("{}", page.title().await.unwrap_or_default());
//!     browser.close().await?;
//!     Ok(())
//! }
//! ```
//!
//! ## Modules
//!
//! | Module | Python source |
//! |--------|---------------|
//! | [`config`] | `cloakbrowser/config.py` |
//! | [`download`] | `cloakbrowser/download.py` |
//! | [`license`] | `cloakbrowser/license.py` |
//! | [`proxy`] | proxy helpers in `browser.py` |
//! | [`geoip`] | `cloakbrowser/geoip.py` |
//! | [`launch`] | `cloakbrowser/browser.py` |
//! | [`human`] | `cloakbrowser/human/*` |

// Prefer working parity with Python/.NET over exhaustive rustdoc on every field.
#![allow(missing_docs)]

pub mod config;
pub mod diagnostics;
pub mod download;
pub mod error;
pub mod geoip;
pub mod human;
pub mod launch;
pub mod license;
pub mod log;
pub mod options;
pub mod proxy;
pub mod version;
pub mod widevine;

pub use config::{
    binary_supports_headless_no_viewport, binary_supports_http_proxy_inline_auth,
    binary_supports_maximized_window, get_binary_path, get_cache_dir, get_chromium_version,
    get_default_stealth_args, get_platform_tag, CHROMIUM_VERSION, IGNORE_DEFAULT_ARGS,
};
pub use download::{binary_info, check_for_update, clear_cache, ensure_binary, BinaryInfo};
pub use error::{Error, Result};
pub use human::{HumanActionOptions, HumanConfig, HumanPage, HumanPreset};
pub use launch::{
    build_args, launch, launch_default, launch_persistent_context, resolve_context_viewport,
    CloakBrowser, CloakContext,
};
pub use license::{resolve_license_key, validate_license, LicenseInfo};
pub use options::{LaunchContextOptions, LaunchOptions, ViewportOption};
pub use proxy::{Proxy, ProxySettings};
pub use version::VERSION;

// Re-export playwright types users need for day-to-day scripting.
pub use playwright_rs::{Browser, BrowserContext, Page, Playwright};
