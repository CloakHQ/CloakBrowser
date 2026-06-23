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

        string binaryPath = await Download.EnsureBinaryAsync(options.LicenseKey).ConfigureAwait(false);
        var (timezone, locale, exitIp) = await MaybeResolveGeoIpAsync(
            options.GeoIp, options.Proxy, options.Timezone, options.Locale).ConfigureAwait(false);
        var proxyResolution = ProxyResolver.Resolve(options.Proxy);
        var args = await ResolveWebRtcArgsAsync(options.Args, options.Proxy).ConfigureAwait(false);
        args = MaybeAppendWebRtcExitIp(args, exitIp);

        var combined = new List<string>(args ?? new List<string>());
        combined.AddRange(proxyResolution.ExtraArgs);
        var chromeArgs = BuildArgs(options.StealthArgs, combined, timezone, locale, options.Headless, options.ExtensionPaths);

        CloakLog.Debug($"Launching stealth Chromium (headless={options.Headless}, args={chromeArgs.Count})");

        var playwright = await Playwright.CreateAsync().ConfigureAwait(false);
        try
        {
            var browser = await playwright.Chromium.LaunchAsync(new BrowserTypeLaunchOptions
            {
                ExecutablePath = binaryPath,
                Headless = options.Headless,
                Args = chromeArgs,
                IgnoreDefaultArgs = Config.IgnoreDefaultArgs,
                Proxy = proxyResolution.PlaywrightProxy,
            }).ConfigureAwait(false);

            var humanCfg = options.Humanize
                ? HumanConfigFactory.Resolve(options.HumanPreset, options.HumanConfig)
                : null;
            // Pass headless so headed handles default new pages/contexts to NoViewport
            // (track the real window - see CloakBrowserHandle.ApplyDefaultNoViewport).
            return new CloakBrowserHandle(playwright, browser, options.Humanize, humanCfg, options.Headless);
        }
        catch
        {
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
            options.GeoIp, options.Proxy, options.Timezone, options.Locale).ConfigureAwait(false);
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
            // geoip already resolved above; don't re-resolve.
            GeoIp = false,
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

        string binaryPath = await Download.EnsureBinaryAsync(options.LicenseKey).ConfigureAwait(false);
        var (timezone, locale, exitIp) = await MaybeResolveGeoIpAsync(
            options.GeoIp, options.Proxy, options.Timezone, options.Locale).ConfigureAwait(false);
        var proxyResolution = ProxyResolver.Resolve(options.Proxy);
        var args = await ResolveWebRtcArgsAsync(options.Args, options.Proxy).ConfigureAwait(false);
        args = MaybeAppendWebRtcExitIp(args, exitIp);

        var combined = new List<string>(args ?? new List<string>());
        combined.AddRange(proxyResolution.ExtraArgs);
        var chromeArgs = BuildArgs(options.StealthArgs, combined, timezone, locale, options.Headless, options.ExtensionPaths);

        CloakLog.Debug($"Launching persistent stealth Chromium (headless={options.Headless}, user_data_dir={userDataDir})");

        // Seed the Widevine CDM hint (Linux-only; no-op elsewhere).
        Widevine.SeedWidevineHint(userDataDir, binaryPath);

        var playwright = await Playwright.CreateAsync().ConfigureAwait(false);
        try
        {
            var ctxLaunchOptions = new BrowserTypeLaunchPersistentContextOptions
            {
                ExecutablePath = binaryPath,
                Headless = options.Headless,
                Args = chromeArgs,
                IgnoreDefaultArgs = Config.IgnoreDefaultArgs,
                Proxy = proxyResolution.PlaywrightProxy,
            };
            ApplyContextEmulation(ctxLaunchOptions, options);

            var context = await playwright.Chromium.LaunchPersistentContextAsync(
                userDataDir, ctxLaunchOptions).ConfigureAwait(false);

            var humanCfg = options.Humanize
                ? HumanConfigFactory.Resolve(options.HumanPreset, options.HumanConfig)
                : null;
            return new CloakContextHandle(playwright, null, context, options.Humanize, humanCfg);
        }
        catch
        {
            playwright.Dispose();
            throw;
        }
    }

    // -----------------------------------------------------------------------
    // GeoIP resolution
    // -----------------------------------------------------------------------

    /// <summary>
    /// Auto-fill timezone/locale from the proxy IP when geoip is enabled. Returns
    /// (timezone, locale, exitIp). The exit IP is a free bonus used for WebRTC spoofing.
    /// </summary>
    public static async Task<(string? Timezone, string? Locale, string? ExitIp)> MaybeResolveGeoIpAsync(
        bool geoip, object? proxy, string? timezone, string? locale)
    {
        if (!geoip || proxy == null)
            return (timezone, locale, null);

        string? proxyUrl = ProxyResolver.ExtractProxyUrl(proxy);
        if (string.IsNullOrEmpty(proxyUrl))
            return (timezone, locale, null);

        // When both tz/locale are explicit, still resolve the exit IP for WebRTC.
        if (timezone != null && locale != null)
        {
            string? exitIpOnly = await GeoIp.ResolveProxyExitIpAsync(proxyUrl).ConfigureAwait(false);
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
        List<string>? extensionPaths = null)
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

        return order.Select(k => seen[k]).ToList();
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
        // Viewport unset: headed tracks the real window; headless gets the fixed default.
        return options.Headless
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
