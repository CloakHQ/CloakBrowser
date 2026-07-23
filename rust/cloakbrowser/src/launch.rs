//! Core browser launch functions for CloakBrowser.
//! Thin wrappers around Playwright that use the patched stealth Chromium binary.
//! Direct port of Python `cloakbrowser/browser.py` / .NET `CloakLauncher.cs`.

use std::collections::HashMap;
use std::path::{Path, PathBuf};

use playwright_rs::api::launch_options::{IgnoreDefaultArgs, LaunchOptions as PwLaunchOptions};
use playwright_rs::protocol::browser_context::{BrowserContextOptions, Viewport};
use playwright_rs::protocol::proxy::ProxySettings as PwProxy;
use playwright_rs::{Browser, BrowserContext, Playwright};

use crate::config;
use crate::download;
use crate::error::{Error, Result};
use crate::geoip;
use crate::human::{HumanConfig, HumanPage};
use crate::license;
use crate::log;
use crate::options::{LaunchContextOptions, LaunchOptions, ViewportOption};
use crate::proxy::{self, Proxy};
use crate::widevine;

/// Handle that owns both the Playwright driver and the launched Browser.
///
/// Dropping this does **not** auto-close the browser (Playwright has no async Drop).
/// Call [`CloakBrowser::close`] explicitly.
pub struct CloakBrowser {
    playwright: Playwright,
    browser: Browser,
    pub headless: bool,
    pub headless_no_viewport: bool,
    /// Humanize config when `humanize=true` at launch; `None` otherwise.
    human_config: Option<HumanConfig>,
}

impl CloakBrowser {
    /// Borrow the underlying Playwright `Browser`.
    pub fn browser(&self) -> &Browser {
        &self.browser
    }

    /// Mutable borrow of the underlying Playwright `Browser`.
    pub fn browser_mut(&mut self) -> &mut Browser {
        &mut self.browser
    }

    /// Whether headless can use `no_viewport` on this binary.
    pub fn headless_no_viewport(&self) -> bool {
        self.headless_no_viewport
    }

    /// Whether humanize was requested at launch.
    pub fn humanize_enabled(&self) -> bool {
        self.human_config.is_some()
    }

    /// Resolved humanize config (if `humanize=true` at launch).
    pub fn human_config(&self) -> Option<&HumanConfig> {
        self.human_config.as_ref()
    }

    /// Create a new raw Playwright page.
    pub async fn new_page(&self) -> Result<playwright_rs::Page> {
        self.browser
            .new_page()
            .await
            .map_err(|e| Error::Playwright(e.to_string()))
    }

    /// Create a new [`HumanPage`] with the launch humanize config (or default config
    /// if humanize was not enabled at launch).
    ///
    /// Prefer this over raw Playwright click/fill when you want human-like motion.
    pub async fn new_human_page(&self) -> Result<HumanPage> {
        let page = self.new_page().await?;
        let cfg = self
            .human_config
            .clone()
            .unwrap_or_default();
        HumanPage::create(page, cfg).await
    }

    /// Wrap an existing Playwright page with humanize (uses launch config or default).
    pub async fn wrap_page(&self, page: playwright_rs::Page) -> Result<HumanPage> {
        let cfg = self.human_config.clone().unwrap_or_default();
        HumanPage::create(page, cfg).await
    }

    /// Close the browser and stop the Playwright driver.
    pub async fn close(self) -> Result<()> {
        if let Err(e) = self.browser.close().await {
            log::warning(format!("browser.close failed: {e}"));
        }
        // Playwright driver cleanup happens when `playwright` drops.
        let _ = self.playwright;
        Ok(())
    }
}

/// A launched stealth browser context (persistent profile or standalone context).
///
/// Owns the Playwright driver. For persistent contexts there is no separate
/// `Browser` handle — closing the context closes Chromium.
pub struct CloakContext {
    playwright: Playwright,
    context: BrowserContext,
    human_config: Option<HumanConfig>,
    /// Profile directory when launched via `launch_persistent_context`.
    user_data_dir: Option<PathBuf>,
}

impl CloakContext {
    /// The underlying Playwright `BrowserContext`.
    pub fn context(&self) -> &BrowserContext {
        &self.context
    }

    /// Mutable access to the context.
    pub fn context_mut(&mut self) -> &mut BrowserContext {
        &mut self.context
    }

    /// Profile directory (persistent launches only).
    pub fn user_data_dir(&self) -> Option<&Path> {
        self.user_data_dir.as_deref()
    }

    /// Whether humanize was requested at launch.
    pub fn humanize_enabled(&self) -> bool {
        self.human_config.is_some()
    }

    /// Create a new raw Playwright page on this context.
    pub async fn new_page(&self) -> Result<playwright_rs::Page> {
        self.context
            .new_page()
            .await
            .map_err(|e| Error::Playwright(e.to_string()))
    }

    /// Create a humanized page (uses launch humanize config or default).
    pub async fn new_human_page(&self) -> Result<HumanPage> {
        let page = self.new_page().await?;
        let cfg = self.human_config.clone().unwrap_or_default();
        HumanPage::create(page, cfg).await
    }

    /// Wrap an existing page with humanize.
    pub async fn wrap_page(&self, page: playwright_rs::Page) -> Result<HumanPage> {
        let cfg = self.human_config.clone().unwrap_or_default();
        HumanPage::create(page, cfg).await
    }

    /// Close the context (and browser process for persistent launches) and stop Playwright.
    pub async fn close(self) -> Result<()> {
        if let Err(e) = self.context.close().await {
            log::warning(format!("context.close failed: {e}"));
        }
        let _ = self.playwright;
        Ok(())
    }
}

/// Launch a stealth Chromium browser.
///
/// Returns a [`CloakBrowser`] wrapping a standard Playwright `Browser`.
///
/// # Example
///
/// ```no_run
/// use cloakbrowser::{launch, LaunchOptions};
///
/// #[tokio::main]
/// async fn main() -> cloakbrowser::Result<()> {
///     let browser = launch(LaunchOptions::default()).await?;
///     let page = browser.new_page().await?;
///     page.goto("https://example.com", None).await.ok();
///     browser.close().await?;
///     Ok(())
/// }
/// ```
pub async fn launch(options: LaunchOptions) -> Result<CloakBrowser> {
    let human_config = if options.humanize {
        Some(HumanConfig::resolve(options.human_preset))
    } else {
        None
    };

    let binary_path = download::ensure_binary(
        options.license_key.as_deref(),
        options.browser_version.as_deref(),
    )
    .await?;

    let (timezone, locale, exit_ip) = geoip::maybe_resolve_geoip(
        options.geoip,
        options.proxy.as_ref(),
        options.timezone.clone(),
        options.locale.clone(),
    )
    .await;

    let proxy_resolution = proxy::resolve(
        options.proxy.as_ref(),
        options.browser_version.as_deref(),
        options.license_key.as_deref(),
    )?;

    let mut args = resolve_webrtc_args(options.args.clone(), options.proxy.as_ref()).await;
    args = append_webrtc_exit_ip(args, exit_ip.as_deref());

    let mut combined: Vec<String> = args.unwrap_or_default();
    combined.extend(proxy_resolution.extra_args);

    let start_maximized = config::binary_supports_maximized_window(
        options.license_key.as_deref(),
        options.browser_version.as_deref(),
    ) && !options.suppress_maximize;

    let chrome_args = build_args(
        options.stealth_args,
        Some(combined),
        timezone.as_deref(),
        locale.as_deref(),
        options.headless,
        options.extension_paths.as_deref(),
        start_maximized,
    );

    maybe_warn_windows_fonts(&chrome_args);

    log::debug(format!(
        "Launching stealth Chromium (headless={}, args={})",
        options.headless,
        chrome_args.len()
    ));

    let launch_env =
        license::build_launch_env(options.license_key.as_deref(), options.env.as_ref());

    let mut pw_opts = PwLaunchOptions::default()
        .executable_path(binary_path.display().to_string())
        .headless(options.headless)
        .args(chrome_args)
        .ignore_default_args(IgnoreDefaultArgs::Array(
            config::IGNORE_DEFAULT_ARGS
                .iter()
                .map(|s| s.to_string())
                .collect(),
        ));

    if let Some(env) = launch_env {
        pw_opts = pw_opts.env(env);
    }

    if let Some(ps) = proxy_resolution.playwright_proxy {
        let mut pw_proxy = PwProxy::new(ps.server);
        if let Some(b) = ps.bypass {
            pw_proxy = pw_proxy.bypass(b);
        }
        if let Some(u) = ps.username {
            pw_proxy = pw_proxy.username(u);
        }
        if let Some(p) = ps.password {
            pw_proxy = pw_proxy.password(p);
        }
        pw_opts = pw_opts.proxy(pw_proxy);
    }

    let playwright = Playwright::launch()
        .await
        .map_err(|e| Error::Playwright(e.to_string()))?;

    let browser = playwright
        .chromium()
        .launch_with_options(pw_opts)
        .await
        .map_err(|e| Error::Playwright(e.to_string()))?;

    let headless_no_viewport = config::binary_supports_headless_no_viewport(
        options.license_key.as_deref(),
        options.browser_version.as_deref(),
    );

    Ok(CloakBrowser {
        playwright,
        browser,
        headless: options.headless,
        headless_no_viewport,
        human_config,
    })
}

/// Convenience: launch with default options.
pub async fn launch_default() -> Result<CloakBrowser> {
    launch(LaunchOptions::default()).await
}

/// Launch stealth Chromium with a **persistent profile** and return a
/// [`CloakContext`].
///
/// Persists cookies, localStorage, cache, and other browser state in
/// `user_data_dir`. Reuse the same path across sessions to restore state.
/// Also avoids incognito-mode detection on some fingerprint scanners.
///
/// Timezone/locale go through binary fingerprint flags (not CDP emulation).
///
/// # Example
///
/// ```no_run
/// use cloakbrowser::{launch_persistent_context, LaunchContextOptions};
///
/// #[tokio::main]
/// async fn main() -> cloakbrowser::Result<()> {
///     let ctx = launch_persistent_context(
///         "./my-profile",
///         LaunchContextOptions {
///             headless: false,
///             humanize: true,
///             ..Default::default()
///         },
///     )
///     .await?;
///
///     let mut page = ctx.new_human_page().await?;
///     page.goto("https://example.com").await?;
///     ctx.close().await?;
///     Ok(())
/// }
/// ```
pub async fn launch_persistent_context(
    user_data_dir: impl AsRef<Path>,
    options: LaunchContextOptions,
) -> Result<CloakContext> {
    let user_data_dir = user_data_dir.as_ref().to_path_buf();
    std::fs::create_dir_all(&user_data_dir)?;

    let human_config = if options.humanize {
        Some(HumanConfig::resolve(options.human_preset))
    } else {
        None
    };

    let binary_path = download::ensure_binary(
        options.license_key.as_deref(),
        options.browser_version.as_deref(),
    )
    .await?;

    let (timezone, locale, exit_ip) = geoip::maybe_resolve_geoip(
        options.geoip,
        options.proxy.as_ref(),
        options.timezone.clone(),
        options.locale.clone(),
    )
    .await;

    let proxy_resolution = proxy::resolve(
        options.proxy.as_ref(),
        options.browser_version.as_deref(),
        options.license_key.as_deref(),
    )?;

    let mut args = resolve_webrtc_args(options.args.clone(), options.proxy.as_ref()).await;
    args = append_webrtc_exit_ip(args, exit_ip.as_deref());

    let mut combined: Vec<String> = args.unwrap_or_default();
    combined.extend(proxy_resolution.extra_args);

    // Don't auto-maximize when the caller chose a viewport geometry.
    let suppress_maximize = matches!(
        options.viewport,
        ViewportOption::Size { .. } | ViewportOption::NoViewport
    );
    let start_maximized = config::binary_supports_maximized_window(
        options.license_key.as_deref(),
        options.browser_version.as_deref(),
    ) && !suppress_maximize;

    let chrome_args = build_args(
        options.stealth_args,
        Some(combined),
        timezone.as_deref(),
        locale.as_deref(),
        options.headless,
        options.extension_paths.as_deref(),
        start_maximized,
    );

    maybe_warn_windows_fonts(&chrome_args);

    log::debug(format!(
        "Launching persistent stealth Chromium (headless={}, user_data_dir={})",
        options.headless,
        user_data_dir.display()
    ));

    // Seed Widevine CDM hint (Linux-only; no-op elsewhere).
    widevine::seed_widevine_hint(&user_data_dir, &binary_path);

    // License: ensure key is visible to the child when it must be injected.
    // BrowserContextOptions has no env map; inject into process env when needed.
    let _license_guard = LicenseEnvGuard::apply(options.license_key.as_deref());

    // BrowserContextOptions is #[non_exhaustive] — start from Default and set fields.
    let mut ctx_opts = BrowserContextOptions::default();
    ctx_opts.executable_path = Some(binary_path.display().to_string());
    ctx_opts.headless = Some(options.headless);
    ctx_opts.args = Some(chrome_args);
    ctx_opts.ignore_default_args = Some(IgnoreDefaultArgs::Array(
        config::IGNORE_DEFAULT_ARGS
            .iter()
            .map(|s| s.to_string())
            .collect(),
    ));
    ctx_opts.user_agent = options.user_agent.clone();
    ctx_opts.color_scheme = options.color_scheme.clone();
    ctx_opts.storage_state_path = options.storage_state_path.clone();
    // locale / timezone via binary flags only — not CDP (detectable).
    ctx_opts.locale = None;
    ctx_opts.timezone_id = None;

    apply_context_viewport(
        &mut ctx_opts,
        &options.viewport,
        options.headless,
        options.license_key.as_deref(),
        options.browser_version.as_deref(),
    );

    if let Some(ps) = proxy_resolution.playwright_proxy {
        let mut pw_proxy = PwProxy::new(ps.server);
        if let Some(b) = ps.bypass {
            pw_proxy = pw_proxy.bypass(b);
        }
        if let Some(u) = ps.username {
            pw_proxy = pw_proxy.username(u);
        }
        if let Some(p) = ps.password {
            pw_proxy = pw_proxy.password(p);
        }
        ctx_opts.proxy = Some(pw_proxy);
    }

    let playwright = Playwright::launch()
        .await
        .map_err(|e| Error::Playwright(e.to_string()))?;

    let context = match playwright
        .chromium()
        .launch_persistent_context_with_options(user_data_dir.display().to_string(), ctx_opts)
        .await
    {
        Ok(ctx) => ctx,
        Err(e) => {
            return Err(Error::Playwright(e.to_string()));
        }
    };

    Ok(CloakContext {
        playwright,
        context,
        human_config,
        user_data_dir: Some(user_data_dir),
    })
}

/// Resolve viewport / no_viewport for a context launch.
///
/// Port of Python `_resolve_context_viewport` / .NET `ResolveContextViewport`.
pub fn resolve_context_viewport(
    viewport: &ViewportOption,
    headless: bool,
    license_key: Option<&str>,
    browser_version: Option<&str>,
) -> (Option<Viewport>, Option<bool>) {
    match viewport {
        ViewportOption::NoViewport => (None, Some(true)),
        ViewportOption::Size { width, height } => (
            Some(Viewport {
                width: *width,
                height: *height,
            }),
            None,
        ),
        ViewportOption::Auto => {
            let headless_no_viewport =
                headless && config::binary_supports_headless_no_viewport(license_key, browser_version);
            if headless && !headless_no_viewport {
                (
                    Some(Viewport {
                        width: config::DEFAULT_VIEWPORT_WIDTH as u32,
                        height: config::DEFAULT_VIEWPORT_HEIGHT as u32,
                    }),
                    None,
                )
            } else {
                (None, Some(true))
            }
        }
    }
}

fn apply_context_viewport(
    opts: &mut BrowserContextOptions,
    viewport: &ViewportOption,
    headless: bool,
    license_key: Option<&str>,
    browser_version: Option<&str>,
) {
    let (vp, no_vp) = resolve_context_viewport(viewport, headless, license_key, browser_version);
    opts.viewport = vp;
    opts.no_viewport = no_vp;
}

/// Temporarily inject `CLOAKBROWSER_LICENSE_KEY` into the process environment
/// when Playwright can't receive a custom env map (persistent context path).
struct LicenseEnvGuard {
    injected: bool,
    previous: Option<String>,
}

impl LicenseEnvGuard {
    fn apply(license_key: Option<&str>) -> Self {
        let (key, source) = license::resolve_license_key_with_source(license_key);
        // Only inject when the binary would not otherwise see the key.
        use license::LicenseKeySource;
        let needs_inject = matches!(
            source,
            LicenseKeySource::Param | LicenseKeySource::CustomFile
        );
        if !needs_inject {
            return Self {
                injected: false,
                previous: None,
            };
        }
        let Some(key) = key else {
            return Self {
                injected: false,
                previous: None,
            };
        };
        let previous = std::env::var("CLOAKBROWSER_LICENSE_KEY").ok();
        // SAFETY: single-threaded at launch; restores on drop.
        unsafe {
            std::env::set_var("CLOAKBROWSER_LICENSE_KEY", &key);
        }
        Self {
            injected: true,
            previous,
        }
    }
}

impl Drop for LicenseEnvGuard {
    fn drop(&mut self) {
        if !self.injected {
            return;
        }
        unsafe {
            match &self.previous {
                Some(v) => std::env::set_var("CLOAKBROWSER_LICENSE_KEY", v),
                None => std::env::remove_var("CLOAKBROWSER_LICENSE_KEY"),
            }
        }
    }
}

/// Combine stealth args with user-provided args and locale flags.
///
/// Deduplicates by flag key (everything before `=`).
/// Priority: stealth defaults < user args < dedicated params (timezone/locale).
pub fn build_args(
    stealth_args: bool,
    extra_args: Option<Vec<String>>,
    timezone: Option<&str>,
    locale: Option<&str>,
    headless: bool,
    extension_paths: Option<&[String]>,
    start_maximized: bool,
) -> Vec<String> {
    let mut seen: HashMap<String, String> = HashMap::new();

    if stealth_args {
        for arg in config::get_default_stealth_args() {
            let key = arg.split('=').next().unwrap_or(&arg).to_string();
            seen.insert(key, arg);
        }
    }

    // GPU blocklist bypass:
    // - Headed mode (all platforms)
    // - Windows (all modes)
    if !headless || cfg!(target_os = "windows") {
        seen.insert(
            "--ignore-gpu-blocklist".into(),
            "--ignore-gpu-blocklist".into(),
        );
    }

    if let Some(extra) = extra_args {
        for arg in extra {
            let key = arg.split('=').next().unwrap_or(&arg).to_string();
            if let Some(old) = seen.get(&key) {
                log::debug(format!("Arg override: {old} -> {arg}"));
            }
            seen.insert(key, arg);
        }
    }

    if let Some(tz) = timezone {
        let key = "--fingerprint-timezone";
        let flag = format!("{key}={tz}");
        if let Some(old) = seen.get(key) {
            log::debug(format!("Arg override: {old} -> {flag}"));
        }
        seen.insert(key.into(), flag);
    }

    if let Some(loc) = locale {
        for key in ["--lang", "--fingerprint-locale"] {
            let flag = format!("{key}={loc}");
            if let Some(old) = seen.get(key) {
                log::debug(format!("Arg override: {old} -> {flag}"));
            }
            seen.insert(key.into(), flag);
        }
    }

    if let Some(paths) = extension_paths {
        if !paths.is_empty() {
            let abs: Vec<String> = paths
                .iter()
                .map(|p| {
                    PathBuf::from(p)
                        .canonicalize()
                        .unwrap_or_else(|_| PathBuf::from(p))
                        .display()
                        .to_string()
                })
                .collect();
            let ext_val = abs.join(",");
            seen.insert(
                "--load-extension".into(),
                format!("--load-extension={ext_val}"),
            );
            seen.insert(
                "--disable-extensions-except".into(),
                format!("--disable-extensions-except={ext_val}"),
            );
        }
    }

    if start_maximized
        && !seen.contains_key("--start-maximized")
        && !seen.contains_key("--window-size")
        && !seen.contains_key("--window-position")
    {
        seen.insert("--start-maximized".into(), "--start-maximized".into());
    }

    seen.into_values().collect()
}

async fn resolve_webrtc_args(
    args: Option<Vec<String>>,
    proxy: Option<&Proxy>,
) -> Option<Vec<String>> {
    let mut args = args?;
    let idx = args.iter().position(|a| a == "--fingerprint-webrtc-ip=auto");
    let Some(idx) = idx else {
        return Some(args);
    };

    let proxy_url = proxy::extract_proxy_url(proxy);
    let Some(proxy_url) = proxy_url else {
        log::warning("--fingerprint-webrtc-ip=auto requires a proxy; removing flag");
        args.remove(idx);
        return Some(args);
    };

    match geoip::resolve_proxy_exit_ip(Some(&proxy_url)).await {
        Some(exit_ip) => {
            args[idx] = format!("--fingerprint-webrtc-ip={exit_ip}");
        }
        None => {
            log::warning(
                "Could not resolve proxy exit IP for WebRTC spoofing; removing --fingerprint-webrtc-ip=auto",
            );
            args.remove(idx);
        }
    }
    Some(args)
}

fn append_webrtc_exit_ip(
    args: Option<Vec<String>>,
    exit_ip: Option<&str>,
) -> Option<Vec<String>> {
    let Some(exit_ip) = exit_ip else {
        return args;
    };
    let mut args = args.unwrap_or_default();
    if !args.iter().any(|a| a.starts_with("--fingerprint-webrtc-ip")) {
        args.push(format!("--fingerprint-webrtc-ip={exit_ip}"));
    }
    Some(args)
}

// ---------------------------------------------------------------------------
// Windows-font mismatch warning (Linux only)
// ---------------------------------------------------------------------------

const WINDOWS_FONT_TELLS: &[&str] = &[
    "Segoe UI",
    "Segoe UI Light",
    "Calibri",
    "Marlett",
    "MS UI Gothic",
    "Franklin Gothic",
    "Consolas",
    "Courier New",
];

static FONT_WARNING_CHECKED: std::sync::atomic::AtomicBool =
    std::sync::atomic::AtomicBool::new(false);

fn maybe_warn_windows_fonts(chrome_args: &[String]) {
    if !cfg!(target_os = "linux") {
        return;
    }
    if FONT_WARNING_CHECKED.swap(true, std::sync::atomic::Ordering::SeqCst) {
        return;
    }
    // Only warn when spoofing Windows.
    let spoofing_windows = chrome_args
        .iter()
        .any(|a| a == "--fingerprint-platform=windows");
    if !spoofing_windows {
        return;
    }

    let n = count_fonts_present(WINDOWS_FONT_TELLS);
    match n {
        Some(n) if n < WINDOWS_FONT_TELLS.len() => {
            log::warning(format!(
                "Windows platform spoof is active but only {n}/{} Windows fonts are installed. \
                 Font fingerprinting anti-bot systems may flag the mismatch. \
                 Install fonts (e.g. ttf-mscorefonts-installer) or set --fingerprint-platform=linux.",
                WINDOWS_FONT_TELLS.len()
            ));
        }
        _ => {}
    }
}

fn count_fonts_present(tells: &[&str]) -> Option<usize> {
    let output = std::process::Command::new("fc-list")
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let listing = String::from_utf8_lossy(&output.stdout).to_lowercase();
    Some(
        tells
            .iter()
            .filter(|f| listing.contains(&f.to_lowercase()))
            .count(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_args_stealth_and_timezone() {
        let args = build_args(
            true,
            Some(vec!["--foo=bar".into()]),
            Some("America/New_York"),
            Some("en-US"),
            true,
            None,
            false,
        );
        assert!(args.iter().any(|a| a.starts_with("--fingerprint=")));
        assert!(args.iter().any(|a| a == "--fingerprint-timezone=America/New_York"));
        assert!(args.iter().any(|a| a == "--lang=en-US"));
        assert!(args.iter().any(|a| a == "--fingerprint-locale=en-US"));
        assert!(args.iter().any(|a| a == "--foo=bar"));
    }

    #[test]
    fn build_args_user_overrides_stealth() {
        let args = build_args(
            true,
            Some(vec!["--fingerprint=99999".into()]),
            None,
            None,
            true,
            None,
            false,
        );
        assert!(args.iter().any(|a| a == "--fingerprint=99999"));
        assert_eq!(
            args.iter()
                .filter(|a| a.starts_with("--fingerprint="))
                .count(),
            1
        );
    }

    #[test]
    fn append_webrtc_once() {
        let args = append_webrtc_exit_ip(None, Some("1.2.3.4"));
        assert_eq!(
            args.unwrap(),
            vec!["--fingerprint-webrtc-ip=1.2.3.4".to_string()]
        );

        let args = append_webrtc_exit_ip(
            Some(vec!["--fingerprint-webrtc-ip=9.9.9.9".into()]),
            Some("1.2.3.4"),
        );
        assert_eq!(
            args.unwrap(),
            vec!["--fingerprint-webrtc-ip=9.9.9.9".to_string()]
        );
    }

    #[test]
    fn context_viewport_headed_is_no_viewport() {
        let (vp, no) = resolve_context_viewport(&ViewportOption::Auto, false, None, None);
        assert!(vp.is_none());
        assert_eq!(no, Some(true));
    }

    #[test]
    fn context_viewport_explicit_size() {
        let (vp, no) = resolve_context_viewport(
            &ViewportOption::Size {
                width: 800,
                height: 600,
            },
            true,
            None,
            None,
        );
        assert!(vp.is_some());
        assert_eq!(vp.unwrap().width, 800);
        assert!(no.is_none());
    }

    #[test]
    fn context_viewport_no_viewport_flag() {
        let (vp, no) =
            resolve_context_viewport(&ViewportOption::NoViewport, true, None, None);
        assert!(vp.is_none());
        assert_eq!(no, Some(true));
    }
}
