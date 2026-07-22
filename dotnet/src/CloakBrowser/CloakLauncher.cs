using System.Diagnostics;
using System.Runtime.InteropServices;
using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser;

/// <summary>
/// Core browser launch functions for CloakBrowser - thin wrappers around Playwright
/// that use the patched stealth Chromium binary instead of stock Chromium.
///
/// Direct port of Python <c>cloakbrowser/browser.py</c>. Because .NET Playwright is
/// async-only, only the async launch surface is provided.
/// </summary>
public static class CloakLauncher
{
    // -----------------------------------------------------------------------
    // launch - returns a Browser handle
    // -----------------------------------------------------------------------

    /// <summary>Launch a stealth Chromium browser. Returns a <see cref="CloakBrowserHandle"/>.</summary>
    public static async Task<CloakBrowserHandle> LaunchAsync(LaunchOptions? options = null)
    {
        options ??= new LaunchOptions();

        string binaryPath = await Download.EnsureBinaryAsync(options.LicenseKey, options.BrowserVersion).ConfigureAwait(false);
        var (timezone, locale, exitIp) = await MaybeResolveGeoIpAsync(
            options.GeoIp, options.Proxy, options.Timezone, options.Locale, options.Args).ConfigureAwait(false);
        var proxyResolution = ProxyResolver.Resolve(options.Proxy, options.BrowserVersion, options.LicenseKey);
        var args = await ResolveWebRtcArgsAsync(options.Args, options.Proxy).ConfigureAwait(false);
        args = MaybeAppendWebRtcExitIp(args, exitIp);

        var combined = new List<string>(args ?? new List<string>());
        combined.AddRange(proxyResolution.ExtraArgs);
        var chromeArgs = BuildArgs(options.StealthArgs, combined, timezone, locale, options.Headless, options.ExtensionPaths,
            startMaximized: Config.BinarySupportsMaximizedWindow(options.LicenseKey, options.BrowserVersion)
                && !options.SuppressMaximize);
        MaybeWarnWindowsFonts(chromeArgs);

        CloakLog.Debug($"Launching stealth Chromium (headless={options.Headless}, args={chromeArgs.Count})");

        var playwright = await Playwright.CreateAsync().ConfigureAwait(false);
        // Only the launch is wrapped for license-error mapping (mirrors Python/JS).
        IBrowser browser;
        try
        {
            browser = await playwright.Chromium.LaunchAsync(new BrowserTypeLaunchOptions
            {
                ExecutablePath = binaryPath,
                Headless = options.Headless,
                Args = chromeArgs,
                IgnoreDefaultArgs = Config.IgnoreDefaultArgs,
                Proxy = proxyResolution.PlaywrightProxy,
                Env = License.BuildLaunchEnv(options.LicenseKey),
            }).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            playwright.Dispose();
            var lic = License.LicenseErrorFrom(ex);
            if (lic is not null) throw lic;
            throw;
        }

        // Post-launch handle construction: a failure here is not a license issue,
        // but the browser + Playwright still need tearing down.
        try
        {
            var humanCfg = options.Humanize
                ? HumanConfigFactory.Resolve(options.HumanPreset, options.HumanConfig)
                : null;
            // Pass headless so headed handles default new pages/contexts to NoViewport
            // (track the real window - see CloakBrowserHandle.ApplyDefaultNoViewport).
            // headlessNoViewport extends that default to headless on newer binaries.
            bool headlessNoViewport =
                Config.BinarySupportsHeadlessNoViewport(options.LicenseKey, options.BrowserVersion);
            return new CloakBrowserHandle(
                playwright, browser, options.Humanize, humanCfg, options.Headless, headlessNoViewport);
        }
        catch
        {
            try { await browser.CloseAsync().ConfigureAwait(false); }
            catch (Exception closeEx) { CloakLog.Warning($"browser cleanup after post-launch failure failed: {closeEx.Message}"); }
            playwright.Dispose();
            throw;
        }
    }

    // -----------------------------------------------------------------------
    // connect - attach to an already-running instance over CDP
    // -----------------------------------------------------------------------

    /// <summary>
    /// Connect to an already-running CloakBrowser instance over CDP (e.g. one started
    /// via cloakserve in Docker) and apply the same conveniences <see cref="LaunchAsync"/>
    /// provides — the no-viewport default and, optionally, the humanize behavioral layer.
    /// The C++ fingerprint patches live in the running binary and persist across the
    /// connection, so select a fingerprint/timezone/locale via the endpoint URL's query
    /// string (e.g. <c>http://host:9222?fingerprint=12345</c>), which is forwarded verbatim.
    /// <see cref="CloakBrowserHandle.CloseAsync"/> detaches from the remote instance; it
    /// does not terminate it.
    /// </summary>
    public static async Task<CloakBrowserHandle> ConnectAsync(string endpointUrl, ConnectOptions? options = null)
    {
        options ??= new ConnectOptions();

        CloakLog.Debug($"Connecting to CloakBrowser over CDP ({endpointUrl})");

        var playwright = await Playwright.CreateAsync().ConfigureAwait(false);
        IBrowser browser;
        try
        {
            browser = await playwright.Chromium.ConnectOverCDPAsync(endpointUrl).ConfigureAwait(false);
        }
        catch
        {
            playwright.Dispose();
            throw;
        }

        try
        {
            var humanCfg = options.Humanize
                ? HumanConfigFactory.Resolve(options.HumanPreset, options.HumanConfig)
                : null;
            // Map DefaultNoViewport onto the handle's headed/headlessNoViewport gate:
            // ApplyHeadedNoViewport applies NoViewport unless (headless && !headlessNoViewport),
            // so headless=false forces the no-viewport default; headless=true keeps the
            // emulated viewport. (We can't know the remote's real headless state.)
            return new CloakBrowserHandle(
                playwright, browser, options.Humanize, humanCfg,
                headless: !options.DefaultNoViewport, headlessNoViewport: false);
        }
        catch
        {
            try { await browser.CloseAsync().ConfigureAwait(false); }
            catch (Exception closeEx) { CloakLog.Warning($"browser cleanup after connect failure failed: {closeEx.Message}"); }
            playwright.Dispose();
            throw;
        }
    }

    // -----------------------------------------------------------------------
    // launch_context - returns a Context handle (browser owned)
    // -----------------------------------------------------------------------

    /// <summary>Launch a stealth browser and return a <see cref="CloakContextHandle"/> with common options pre-set.</summary>
    public static async Task<CloakContextHandle> LaunchContextAsync(LaunchContextOptions? options = null)
    {
        options ??= new LaunchContextOptions();

        // Resolve geoip before launch so resolved values flow to binary flags.
        var (timezone, locale, exitIp) = await MaybeResolveGeoIpAsync(
            options.GeoIp, options.Proxy, options.Timezone, options.Locale, options.Args).ConfigureAwait(false);
        var args = options.Args;
        args = MaybeAppendWebRtcExitIp(args, exitIp);

        var browserHandle = await LaunchAsync(new LaunchOptions
        {
            Headless = options.Headless,
            Proxy = options.Proxy,
            Args = args,
            StealthArgs = options.StealthArgs,
            Timezone = timezone,
            Locale = locale,
            ExtensionPaths = options.ExtensionPaths,
            LicenseKey = options.LicenseKey,
            BrowserVersion = options.BrowserVersion,
            // geoip already resolved above; don't re-resolve.
            GeoIp = false,
            // Caller chose a viewport geometry → don't also auto-maximize the
            // window (mirrors the persistent-context path + Python/JS).
            SuppressMaximize = options.Viewport != null || options.NoViewport,
        }).ConfigureAwait(false);

        try
        {
            var ctxOptions = BuildContextOptions(options);
            var context = await browserHandle.Browser.NewContextAsync(ctxOptions).ConfigureAwait(false);

            var humanCfg = options.Humanize
                ? HumanConfigFactory.Resolve(options.HumanPreset, options.HumanConfig)
                : null;

            // The context handle owns the browser; reuse the same Playwright instance.
            return new CloakContextHandle(
                GetPlaywright(browserHandle), browserHandle.Browser, context, options.Humanize, humanCfg);
        }
        catch
        {
            await browserHandle.CloseAsync().ConfigureAwait(false);
            throw;
        }
    }

    // -----------------------------------------------------------------------
    // launch_persistent_context - returns a Context handle (no separate browser)
    // -----------------------------------------------------------------------

    /// <summary>Launch a stealth browser with a persistent profile; returns a <see cref="CloakContextHandle"/>.</summary>
    public static async Task<CloakContextHandle> LaunchPersistentContextAsync(
        string userDataDir, LaunchContextOptions? options = null)
    {
        options ??= new LaunchContextOptions();

        string binaryPath = await Download.EnsureBinaryAsync(options.LicenseKey, options.BrowserVersion).ConfigureAwait(false);
        var (timezone, locale, exitIp) = await MaybeResolveGeoIpAsync(
            options.GeoIp, options.Proxy, options.Timezone, options.Locale, options.Args).ConfigureAwait(false);
        var proxyResolution = ProxyResolver.Resolve(options.Proxy, options.BrowserVersion, options.LicenseKey);
        var args = await ResolveWebRtcArgsAsync(options.Args, options.Proxy).ConfigureAwait(false);
        args = MaybeAppendWebRtcExitIp(args, exitIp);

        var combined = new List<string>(args ?? new List<string>());
        combined.AddRange(proxyResolution.ExtraArgs);
        var chromeArgs = BuildArgs(options.StealthArgs, combined, timezone, locale, options.Headless, options.ExtensionPaths,
            startMaximized: Config.BinarySupportsMaximizedWindow(options.LicenseKey, options.BrowserVersion)
                && !options.NoViewport && options.Viewport == null);
        MaybeWarnWindowsFonts(chromeArgs);

        CloakLog.Debug($"Launching persistent stealth Chromium (headless={options.Headless}, user_data_dir={userDataDir})");

        // Seed the Widevine CDM hint (Linux-only; no-op elsewhere).
        Widevine.SeedWidevineHint(userDataDir, binaryPath);

        var playwright = await Playwright.CreateAsync().ConfigureAwait(false);
        // Only the launch is wrapped for license-error mapping (mirrors Python/JS).
        IBrowserContext context;
        try
        {
            var ctxLaunchOptions = new BrowserTypeLaunchPersistentContextOptions
            {
                ExecutablePath = binaryPath,
                Headless = options.Headless,
                Args = chromeArgs,
                IgnoreDefaultArgs = Config.IgnoreDefaultArgs,
                Proxy = proxyResolution.PlaywrightProxy,
                Env = License.BuildLaunchEnv(options.LicenseKey),
            };
            ApplyContextEmulation(ctxLaunchOptions, options);

            context = await playwright.Chromium.LaunchPersistentContextAsync(
                userDataDir, ctxLaunchOptions).ConfigureAwait(false);
        }
        catch (Exception ex)
        {
            playwright.Dispose();
            var lic = License.LicenseErrorFrom(ex);
            if (lic is not null) throw lic;
            throw;
        }

        // Post-launch handle construction: a failure here is not a license issue,
        // but the context + Playwright still need tearing down.
        try
        {
            var humanCfg = options.Humanize
                ? HumanConfigFactory.Resolve(options.HumanPreset, options.HumanConfig)
                : null;
            return new CloakContextHandle(playwright, null, context, options.Humanize, humanCfg);
        }
        catch
        {
            try { await context.CloseAsync().ConfigureAwait(false); }
            catch (Exception closeEx) { CloakLog.Warning($"context cleanup after post-launch failure failed: {closeEx.Message}"); }
            playwright.Dispose();
            throw;
        }
    }

    // -----------------------------------------------------------------------
    // GeoIP resolution
    // -----------------------------------------------------------------------

    /// <summary>Return the value of the first <c>--key=value</c> flag found in args, else null.</summary>
    private static string? GetFlagValue(List<string>? args, params string[] keys)
    {
        if (args == null)
            return null;
        foreach (var a in args)
            foreach (var k in keys)
                if (a.StartsWith(k + "=", StringComparison.Ordinal))
                    return a.Substring(k.Length + 1);
        return null;
    }

    /// <summary>
    /// Auto-fill timezone/locale from the egress IP when geoip is enabled. Returns
    /// (timezone, locale, exitIp). The exit IP is a free bonus used for WebRTC spoofing.
    /// With a proxy the egress IP is the proxy's exit IP; with no proxy it is the
    /// machine's own public IP, so geoip works proxy-free too.
    /// A timezone/locale set as a raw flag in args (--fingerprint-timezone, --lang,
    /// --fingerprint-locale) counts as explicit and is promoted so geoip leaves it alone.
    /// </summary>
    public static async Task<(string? Timezone, string? Locale, string? ExitIp)> MaybeResolveGeoIpAsync(
        bool geoip, object? proxy, string? timezone, string? locale, List<string>? args = null)
    {
        if (!geoip)
            return (timezone, locale, null);

        // Promote raw flags to explicit values so geoip doesn't clobber them.
        timezone ??= GetFlagValue(args, "--fingerprint-timezone");
        locale ??= GetFlagValue(args, "--lang", "--fingerprint-locale");

        // null when no proxy -> echo services resolve the machine's own public IP.
        string? proxyUrl = proxy != null ? ProxyResolver.ExtractProxyUrl(proxy) : null;

        // When both tz/locale are explicit, resolve the exit IP for WebRTC — but only
        // with a proxy. With no proxy the WebRTC IP would just be the real connection
        // IP the site already sees (a no-op), so skip the third-party echo call.
        if (timezone != null && locale != null)
        {
            string? exitIpOnly = proxyUrl != null
                ? await GeoIp.ResolveProxyExitIpAsync(proxyUrl).ConfigureAwait(false)
                : null;
            return (timezone, locale, exitIpOnly);
        }

        var (geoTz, geoLocale, exitIp) = await GeoIp.ResolveProxyGeoWithIpAsync(proxyUrl).ConfigureAwait(false);
        return (timezone ?? geoTz, locale ?? geoLocale, exitIp);
    }

    // -----------------------------------------------------------------------
    // WebRTC args
    // -----------------------------------------------------------------------

    /// <summary>Replace <c>--fingerprint-webrtc-ip=auto</c> with the resolved proxy exit IP.</summary>
    public static async Task<List<string>?> ResolveWebRtcArgsAsync(List<string>? args, object? proxy)
    {
        if (args == null || args.Count == 0)
            return args;
        int idx = args.FindIndex(a => a == "--fingerprint-webrtc-ip=auto");
        if (idx < 0)
            return args;

        string? proxyUrl = ProxyResolver.ExtractProxyUrl(proxy);
        var result = new List<string>(args);
        if (string.IsNullOrEmpty(proxyUrl))
        {
            CloakLog.Warning("--fingerprint-webrtc-ip=auto requires a proxy; removing flag");
            result.RemoveAt(idx);
            return result;
        }

        string? exitIp;
        try { exitIp = await GeoIp.ResolveProxyExitIpAsync(proxyUrl).ConfigureAwait(false); }
        catch (Exception)
        {
            CloakLog.Warning("Failed to resolve proxy exit IP for WebRTC spoofing; removing --fingerprint-webrtc-ip=auto");
            result.RemoveAt(idx);
            return result;
        }

        if (!string.IsNullOrEmpty(exitIp))
            result[idx] = $"--fingerprint-webrtc-ip={exitIp}";
        else
        {
            CloakLog.Warning("Could not resolve proxy exit IP for WebRTC spoofing; removing --fingerprint-webrtc-ip=auto");
            result.RemoveAt(idx);
        }
        return result;
    }

    private static List<string>? MaybeAppendWebRtcExitIp(List<string>? args, string? exitIp)
    {
        if (string.IsNullOrEmpty(exitIp))
            return args;
        bool alreadySet = args != null && args.Any(a => a.StartsWith("--fingerprint-webrtc-ip"));
        if (alreadySet)
            return args;
        var result = new List<string>(args ?? new List<string>())
        {
            $"--fingerprint-webrtc-ip={exitIp}",
        };
        return result;
    }

    // -----------------------------------------------------------------------
    // build_args
    // -----------------------------------------------------------------------

    /// <summary>
    /// Combine stealth args with user-provided args and locale/timezone flags.
    /// Deduplicates by flag key (everything before <c>=</c>).
    /// Priority: stealth defaults &lt; user args &lt; dedicated params (timezone/locale).
    /// </summary>
    public static List<string> BuildArgs(
        bool stealthArgs,
        List<string>? extraArgs,
        string? timezone = null,
        string? locale = null,
        bool headless = true,
        List<string>? extensionPaths = null,
        bool startMaximized = false)
    {
        // Preserve insertion order while deduping by key.
        var seen = new Dictionary<string, string>();
        var order = new List<string>();

        void Set(string key, string value)
        {
            if (seen.ContainsKey(key))
                CloakLog.Debug($"Arg override: {seen[key]} -> {value}");
            else
                order.Add(key);
            seen[key] = value;
        }

        if (stealthArgs)
        {
            foreach (var arg in Config.GetDefaultStealthArgs())
                Set(arg.Split('=', 2)[0], arg);
        }

        // GPU blocklist bypass in headed mode (all platforms) or on Windows (all modes).
        if (!headless || RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            Set("--ignore-gpu-blocklist", "--ignore-gpu-blocklist");

        if (extraArgs != null)
        {
            foreach (var arg in extraArgs)
                Set(arg.Split('=', 2)[0], arg);
        }

        if (!string.IsNullOrEmpty(timezone))
            Set("--fingerprint-timezone", $"--fingerprint-timezone={timezone}");

        if (!string.IsNullOrEmpty(locale))
        {
            Set("--lang", $"--lang={locale}");
            Set("--fingerprint-locale", $"--fingerprint-locale={locale}");
        }

        if (extensionPaths != null && extensionPaths.Count > 0)
        {
            var absPaths = extensionPaths.Select(Path.GetFullPath);
            string extVal = string.Join(",", absPaths);
            Set("--load-extension", $"--load-extension={extVal}");
            Set("--disable-extensions-except", $"--disable-extensions-except={extVal}");
        }

        // Open maximized (real Chrome overwhelmingly runs maximized) so the window
        // fills the spoofed screen. Skipped if the caller chose a window geometry.
        // Gated to binaries where this stays coherent (see BinarySupportsMaximizedWindow)
        // — below the gate it would make outerWidth < innerWidth.
        if (startMaximized
            && !seen.ContainsKey("--start-maximized")
            && !seen.ContainsKey("--window-size")
            && !seen.ContainsKey("--window-position"))
        {
            Set("--start-maximized", "--start-maximized");
        }

        return order.Select(k => seen[k]).ToList();
    }

    // -----------------------------------------------------------------------
    // Windows-font mismatch warning (Linux only)
    //
    // On Linux the binary spoofs the Windows platform by default, but fonts come
    // from the host OS. A font-less Linux box contradicts the Windows claim and
    // font-fingerprinting anti-bot systems flag the mismatch. Warn once per
    // environment. See docs/chrome40-fpjs-font-minimum-set-investigation.md.
    // -----------------------------------------------------------------------

    // Windows OS fonts — ship with Windows itself, so their absence on a
    // Windows-spoofing Linux host degrades results. The two monospace fonts
    // (Consolas + Courier New) are part of the recommended set so the generic
    // `monospace` family resolves to a Windows font. See issue #395.
    internal static readonly string[] WindowsFontTells =
    {
        "Segoe UI", "Segoe UI Light", "Calibri", "Marlett", "MS UI Gothic",
        "Franklin Gothic", "Consolas", "Courier New",
    };

    // MS Office supplemental fonts, installed as one atomic block by every Office
    // install. Roughly half of real Windows machines have this pack and half do
    // not, so its absence is a perfectly normal Windows setup, NOT a problem —
    // reported as an informational signal only, never a warning.
    internal static readonly string[] OfficeFontTells =
    {
        "MT Extra", "Century", "Century Gothic", "MS Reference Specialty",
        "Wingdings 2", "Wingdings 3", "Book Antiqua", "Bookshelf Symbol 7",
        "Monotype Corsiva", "Bookman Old Style",
    };

    internal static bool _fontWarningChecked;

    /// <summary>
    /// Count how many tell-tale fonts are installed, via fc-list. Returns the
    /// number present (0..tells.Length), or null if it can't be determined
    /// (fc-list missing or errored). Callers must NOT treat null as zero — null
    /// means "unknown", 0 means "genuinely none installed".
    /// </summary>
    internal static int? CountFontsPresent(string[] tells)
    {
        string output;
        try
        {
            using var proc = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = "fc-list",
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                },
            };
            if (!proc.Start()) return null;
            // Drain both streams concurrently so a full stderr buffer can't block
            // the stdout read, and bound the WHOLE probe with the 5s ceiling
            // (a synchronous ReadToEnd would run unbounded before WaitForExit).
            var stdoutTask = proc.StandardOutput.ReadToEndAsync();
            _ = proc.StandardError.ReadToEndAsync();
            if (!proc.WaitForExit(5000))
            {
                try { proc.Kill(); } catch { /* best-effort */ }
                return null;
            }
            // Process exited within budget; the read completes once stdout closes.
            // Bound the join too in case the stream lingers after exit.
            if (!stdoutTask.Wait(1000)) return null;
            output = stdoutTask.Result;
            if (proc.ExitCode != 0) return null;
        }
        catch
        {
            return null;
        }
        var listing = output.ToLowerInvariant();
        return tells.Count(f => listing.Contains(f.ToLowerInvariant()));
    }

    /// <summary>
    /// True if ALL Windows OS fonts are installed, false if any are missing, null
    /// if unknown. Strict: a partial set is treated as incomplete, since the font
    /// install is atomic and a missing font degrades the Windows persona.
    /// </summary>
    internal static bool? WindowsFontsPresent()
    {
        var n = CountFontsPresent(WindowsFontTells);
        return n is null ? null : n == WindowsFontTells.Length;
    }

    /// <summary>
    /// Warn once when spoofing Windows on a Linux host without the full Windows
    /// font set. Best-effort and silent on error — never throws. Gated by an
    /// in-process flag plus a cache-dir marker so it fires at most once per
    /// environment. Suppress entirely with CLOAKBROWSER_SUPPRESS_FONT_WARNING.
    /// </summary>
    internal static void MaybeWarnWindowsFonts(IReadOnlyList<string> chromeArgs)
    {
        if (_fontWarningChecked) return;
        _fontWarningChecked = true;
        try
        {
            if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("CLOAKBROWSER_SUPPRESS_FONT_WARNING"))) return;
            if (!RuntimeInformation.IsOSPlatform(OSPlatform.Linux)) return;
            // Effective platform = the last --fingerprint-platform in the final argv
            // (BuildArgs dedups, so at most one). null => no Windows spoof.
            string? effectivePlatform = null;
            const string prefix = "--fingerprint-platform=";
            foreach (var arg in chromeArgs)
            {
                if (arg.StartsWith(prefix, StringComparison.Ordinal))
                    effectivePlatform = arg.Substring(prefix.Length).Trim().ToLowerInvariant();
            }
            if (effectivePlatform != "windows") return;
            var marker = Path.Combine(Config.GetCacheDir(), ".font_warning_shown");
            if (File.Exists(marker)) return;
            var present = WindowsFontsPresent();
            if (present != false) return; // true (full set) or null (undeterminable)
            CloakLog.Warning(
                "[cloakbrowser] Incomplete Windows font set — installing the full " +
                "set is strongly advised for best results when spoofing Windows on " +
                "Linux. https://github.com/CloakHQ/cloakbrowser#font-setup-on-linux " +
                "(silence: CLOAKBROWSER_SUPPRESS_FONT_WARNING=1)");
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(marker)!);
                File.WriteAllText(marker, "");
            }
            catch (IOException) { /* non-fatal */ }
        }
        catch
        {
            // Best-effort — never throw from a warning.
        }
    }

    // -----------------------------------------------------------------------
    // Context option helpers
    // -----------------------------------------------------------------------

    /// <summary>
    /// Resolve the viewport for a context. Headed: no emulated viewport so the page
    /// tracks the real window (CDP viewport emulation forces outerWidth &lt; innerWidth =
    /// a physically impossible window = bot tell). Headless: a fixed DEFAULT_VIEWPORT
    /// stays coherent (outer == inner) and keeps dimensions deterministic. An explicit
    /// <see cref="LaunchContextOptions.NoViewport"/> or <see cref="LaunchContextOptions.Viewport"/>
    /// is always honored. Port of Python <c>_resolve_context_viewport</c>.
    /// </summary>
    internal static ViewportSize? ResolveContextViewport(LaunchContextOptions options)
    {
        if (options.NoViewport)
            return ViewportSize.NoViewport;
        if (options.Viewport != null)
            return new ViewportSize { Width = options.Viewport.Value.Width, Height = options.Viewport.Value.Height };
        // Viewport unset: headed tracks the real window; headless on a newer binary also
        // tracks it (coherent dimensions natively), older headless gets the fixed default.
        bool headlessNoViewport = options.Headless
            && Config.BinarySupportsHeadlessNoViewport(options.LicenseKey, options.BrowserVersion);
        return options.Headless && !headlessNoViewport
            ? new ViewportSize { Width = Config.DefaultViewportWidth, Height = Config.DefaultViewportHeight }
            : ViewportSize.NoViewport;
    }

    private static BrowserNewContextOptions BuildContextOptions(LaunchContextOptions options)
    {
        var ctx = new BrowserNewContextOptions();
        if (!string.IsNullOrEmpty(options.UserAgent))
            ctx.UserAgent = options.UserAgent;

        ctx.ViewportSize = ResolveContextViewport(options);

        if (!string.IsNullOrEmpty(options.ColorScheme))
            ctx.ColorScheme = ParseColorScheme(options.ColorScheme);
        if (!string.IsNullOrEmpty(options.StorageStatePath))
            ctx.StorageStatePath = options.StorageStatePath;
        return ctx;
    }

    private static void ApplyContextEmulation(
        BrowserTypeLaunchPersistentContextOptions ctx, LaunchContextOptions options)
    {
        if (!string.IsNullOrEmpty(options.UserAgent))
            ctx.UserAgent = options.UserAgent;

        ctx.ViewportSize = ResolveContextViewport(options);

        if (!string.IsNullOrEmpty(options.ColorScheme))
            ctx.ColorScheme = ParseColorScheme(options.ColorScheme);
    }

    private static ColorScheme ParseColorScheme(string s) => s.ToLowerInvariant() switch
    {
        "light" => ColorScheme.Light,
        "dark" => ColorScheme.Dark,
        "no-preference" => ColorScheme.NoPreference,
        _ => ColorScheme.Light,
    };

    // Access the private Playwright instance of a browser handle via reflection-free shim.
    // CloakBrowserHandle exposes the browser; we need the same IPlaywright for the context
    // handle. Stored when we created it - expose through an internal accessor.
    private static IPlaywright GetPlaywright(CloakBrowserHandle handle) => handle.PlaywrightInstance;
}
