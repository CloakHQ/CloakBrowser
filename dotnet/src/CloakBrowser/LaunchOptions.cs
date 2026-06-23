using CloakBrowser.Human;

namespace CloakBrowser;

/// <summary>
/// Options for <see cref="CloakLauncher.LaunchAsync(LaunchOptions)"/> and friends.
/// Mirrors the keyword arguments of the Python <c>launch()</c> family.
/// </summary>
public class LaunchOptions
{
    /// <summary>Run in headless mode (default true).</summary>
    public bool Headless { get; set; } = true;

    /// <summary>Proxy: a URL string (<c>http://user:pass@host:port</c>) or a <see cref="ProxySettings"/>.</summary>
    public object? Proxy { get; set; }

    /// <summary>Additional Chromium CLI arguments.</summary>
    public List<string>? Args { get; set; }

    /// <summary>Include the default stealth fingerprint args (default true).</summary>
    public bool StealthArgs { get; set; } = true;

    /// <summary>IANA timezone, e.g. <c>America/New_York</c> - sets <c>--fingerprint-timezone</c>.</summary>
    public string? Timezone { get; set; }

    /// <summary>BCP 47 locale, e.g. <c>en-US</c> - sets <c>--lang</c> and <c>--fingerprint-locale</c>.</summary>
    public string? Locale { get; set; }

    /// <summary>Auto-detect timezone/locale (and WebRTC exit IP) from the proxy IP (default false).</summary>
    public bool GeoIp { get; set; }

    /// <summary>Enable the human-like behavior layer when creating pages via <see cref="CloakBrowserHandle"/>.</summary>
    public bool Humanize { get; set; }

    /// <summary>Humanize preset (default <see cref="HumanPreset.Default"/>).</summary>
    public HumanPreset HumanPreset { get; set; } = HumanPreset.Default;

    /// <summary>Custom humanize config overrides (snake_case or PascalCase keys).</summary>
    public IReadOnlyDictionary<string, object>? HumanConfig { get; set; }

    /// <summary>Chrome extension paths to load.</summary>
    public List<string>? ExtensionPaths { get; set; }

    /// <summary>
    /// CloakBrowser Pro license key. Also read from the <c>CLOAKBROWSER_LICENSE_KEY</c>
    /// env var or <c>~/.cloakbrowser/license.key</c>. With a valid key the latest Pro
    /// binary is downloaded from cloakbrowser.dev; without one, the free binary is used.
    /// </summary>
    public string? LicenseKey { get; set; }
}

/// <summary>Options for context-producing launchers (adds context-level emulation settings).</summary>
public class LaunchContextOptions : LaunchOptions
{
    /// <summary>Custom user agent string.</summary>
    public string? UserAgent { get; set; }

    /// <summary>Viewport size. Null means "use default 1920x947". Set <see cref="NoViewport"/> to disable.</summary>
    public (int Width, int Height)? Viewport { get; set; }

    /// <summary>Disable viewport emulation (use the OS window size).</summary>
    public bool NoViewport { get; set; }

    /// <summary>Color scheme preference: <c>light</c>, <c>dark</c>, or <c>no-preference</c>.</summary>
    public string? ColorScheme { get; set; }

    /// <summary>Path to a Playwright storage-state JSON to restore cookies/localStorage.</summary>
    public string? StorageStatePath { get; set; }
}
