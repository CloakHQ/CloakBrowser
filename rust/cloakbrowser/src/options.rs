//! Launch option records (mirrors Python keyword args / .NET LaunchOptions).

use crate::human::HumanPreset;
use crate::proxy::Proxy;

/// Options for [`crate::launch::launch`].
#[derive(Debug, Clone)]
pub struct LaunchOptions {
    /// Run in headless mode (default true).
    pub headless: bool,
    /// Proxy URL string or structured settings.
    pub proxy: Option<Proxy>,
    /// Additional Chromium CLI arguments.
    pub args: Option<Vec<String>>,
    /// Include the default stealth fingerprint args (default true).
    pub stealth_args: bool,
    /// IANA timezone, e.g. `America/New_York`.
    pub timezone: Option<String>,
    /// BCP 47 locale, e.g. `en-US`.
    pub locale: Option<String>,
    /// Auto-detect timezone/locale (and WebRTC exit IP) from the proxy IP.
    pub geoip: bool,
    /// Enable human-like behavior layer. Use [`crate::CloakBrowser::new_human_page`].
    pub humanize: bool,
    /// Humanize preset when `humanize` is true (default / careful).
    pub human_preset: HumanPreset,
    /// Chrome extension paths to load.
    pub extension_paths: Option<Vec<String>>,
    /// CloakBrowser Pro license key.
    pub license_key: Option<String>,
    /// Exact Chromium version pin.
    pub browser_version: Option<String>,
    /// Suppress auto `--start-maximized` (set by context launchers).
    pub suppress_maximize: bool,
    /// Extra env vars for the browser process (Playwright `env`).
    pub env: Option<std::collections::HashMap<String, String>>,
}

impl Default for LaunchOptions {
    fn default() -> Self {
        Self {
            headless: true,
            proxy: None,
            args: None,
            stealth_args: true,
            timezone: None,
            locale: None,
            geoip: false,
            humanize: false,
            human_preset: HumanPreset::Default,
            extension_paths: None,
            license_key: None,
            browser_version: None,
            suppress_maximize: false,
            env: None,
        }
    }
}

impl LaunchOptions {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn headless(mut self, v: bool) -> Self {
        self.headless = v;
        self
    }

    pub fn proxy(mut self, proxy: impl Into<Proxy>) -> Self {
        self.proxy = Some(proxy.into());
        self
    }

    pub fn args(mut self, args: Vec<String>) -> Self {
        self.args = Some(args);
        self
    }

    pub fn stealth_args(mut self, v: bool) -> Self {
        self.stealth_args = v;
        self
    }

    pub fn timezone(mut self, tz: impl Into<String>) -> Self {
        self.timezone = Some(tz.into());
        self
    }

    pub fn locale(mut self, locale: impl Into<String>) -> Self {
        self.locale = Some(locale.into());
        self
    }

    pub fn geoip(mut self, v: bool) -> Self {
        self.geoip = v;
        self
    }

    pub fn humanize(mut self, v: bool) -> Self {
        self.humanize = v;
        self
    }

    pub fn human_preset(mut self, preset: HumanPreset) -> Self {
        self.human_preset = preset;
        self
    }

    pub fn extension_paths(mut self, paths: Vec<String>) -> Self {
        self.extension_paths = Some(paths);
        self
    }

    pub fn license_key(mut self, key: impl Into<String>) -> Self {
        self.license_key = Some(key.into());
        self
    }

    pub fn browser_version(mut self, version: impl Into<String>) -> Self {
        self.browser_version = Some(version.into());
        self
    }
}

/// Viewport resolution for context launchers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ViewportOption {
    /// Use CloakBrowser defaults (fixed 1920×947 headless, no_viewport headed /
    /// modern headless).
    Auto,
    /// Explicit emulated size.
    Size { width: u32, height: u32 },
    /// Disable viewport emulation (track the real OS window).
    NoViewport,
}

impl Default for ViewportOption {
    fn default() -> Self {
        Self::Auto
    }
}

/// Options for context-producing launchers (`launch_persistent_context`, etc.).
///
/// Mirrors .NET `LaunchContextOptions` / Python kwargs on `launch_persistent_context`.
#[derive(Debug, Clone)]
pub struct LaunchContextOptions {
    /// Run in headless mode (default true).
    pub headless: bool,
    /// Proxy URL string or structured settings.
    pub proxy: Option<Proxy>,
    /// Additional Chromium CLI arguments.
    pub args: Option<Vec<String>>,
    /// Include the default stealth fingerprint args (default true).
    pub stealth_args: bool,
    /// IANA timezone — sets binary `--fingerprint-timezone` (not CDP).
    pub timezone: Option<String>,
    /// BCP 47 locale — sets binary `--lang` / `--fingerprint-locale`.
    pub locale: Option<String>,
    /// Auto-detect timezone/locale from proxy IP.
    pub geoip: bool,
    /// Enable humanize layer for pages from this context.
    pub humanize: bool,
    /// Humanize preset.
    pub human_preset: HumanPreset,
    /// Chrome extension paths.
    pub extension_paths: Option<Vec<String>>,
    /// Pro license key.
    pub license_key: Option<String>,
    /// Chromium version pin.
    pub browser_version: Option<String>,
    /// Custom user agent string.
    pub user_agent: Option<String>,
    /// Viewport handling (default: Auto).
    pub viewport: ViewportOption,
    /// Color scheme: `light`, `dark`, or `no-preference`.
    pub color_scheme: Option<String>,
    /// Path to a Playwright storage-state JSON.
    pub storage_state_path: Option<String>,
}

impl Default for LaunchContextOptions {
    fn default() -> Self {
        Self {
            headless: true,
            proxy: None,
            args: None,
            stealth_args: true,
            timezone: None,
            locale: None,
            geoip: false,
            humanize: false,
            human_preset: HumanPreset::Default,
            extension_paths: None,
            license_key: None,
            browser_version: None,
            user_agent: None,
            viewport: ViewportOption::Auto,
            color_scheme: None,
            storage_state_path: None,
        }
    }
}

impl LaunchContextOptions {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn headless(mut self, v: bool) -> Self {
        self.headless = v;
        self
    }

    pub fn proxy(mut self, proxy: impl Into<Proxy>) -> Self {
        self.proxy = Some(proxy.into());
        self
    }

    pub fn humanize(mut self, v: bool) -> Self {
        self.humanize = v;
        self
    }

    pub fn human_preset(mut self, preset: HumanPreset) -> Self {
        self.human_preset = preset;
        self
    }

    pub fn geoip(mut self, v: bool) -> Self {
        self.geoip = v;
        self
    }

    pub fn user_agent(mut self, ua: impl Into<String>) -> Self {
        self.user_agent = Some(ua.into());
        self
    }

    pub fn viewport_size(mut self, width: u32, height: u32) -> Self {
        self.viewport = ViewportOption::Size { width, height };
        self
    }

    pub fn no_viewport(mut self) -> Self {
        self.viewport = ViewportOption::NoViewport;
        self
    }

    pub fn color_scheme(mut self, scheme: impl Into<String>) -> Self {
        self.color_scheme = Some(scheme.into());
        self
    }

    pub fn timezone(mut self, tz: impl Into<String>) -> Self {
        self.timezone = Some(tz.into());
        self
    }

    pub fn locale(mut self, locale: impl Into<String>) -> Self {
        self.locale = Some(locale.into());
        self
    }

    pub fn license_key(mut self, key: impl Into<String>) -> Self {
        self.license_key = Some(key.into());
        self
    }

    pub fn browser_version(mut self, version: impl Into<String>) -> Self {
        self.browser_version = Some(version.into());
        self
    }

    pub fn storage_state_path(mut self, path: impl Into<String>) -> Self {
        self.storage_state_path = Some(path.into());
        self
    }

    /// Convert shared launch fields into a [`LaunchOptions`] (for shared helpers).
    pub fn as_launch_options(&self) -> LaunchOptions {
        // start_maximized is suppressed when the caller chose a viewport geometry.
        let suppress_maximize = matches!(
            self.viewport,
            ViewportOption::Size { .. } | ViewportOption::NoViewport
        );
        LaunchOptions {
            headless: self.headless,
            proxy: self.proxy.clone(),
            args: self.args.clone(),
            stealth_args: self.stealth_args,
            timezone: self.timezone.clone(),
            locale: self.locale.clone(),
            geoip: self.geoip,
            humanize: self.humanize,
            human_preset: self.human_preset,
            extension_paths: self.extension_paths.clone(),
            license_key: self.license_key.clone(),
            browser_version: self.browser_version.clone(),
            suppress_maximize,
            env: None,
        }
    }
}
