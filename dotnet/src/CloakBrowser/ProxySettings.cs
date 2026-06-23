namespace CloakBrowser;

/// <summary>
/// Playwright-compatible proxy configuration. Mirrors the Python
/// <c>ProxySettings</c> TypedDict. <see cref="Server"/> is required; the rest are optional.
/// </summary>
public sealed class ProxySettings
{
    /// <summary>Proxy server URL, e.g. <c>http://proxy:8080</c> or <c>socks5://proxy:1080</c>.</summary>
    public string Server { get; set; } = "";

    /// <summary>Comma-separated bypass list, e.g. <c>.google.com</c>.</summary>
    public string? Bypass { get; set; }

    /// <summary>Proxy username (for authenticated proxies).</summary>
    public string? Username { get; set; }

    /// <summary>Proxy password (for authenticated proxies).</summary>
    public string? Password { get; set; }
}
