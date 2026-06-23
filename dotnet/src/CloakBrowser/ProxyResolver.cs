namespace CloakBrowser;

/// <summary>
/// Proxy resolution: maps a proxy (string URL or <see cref="ProxySettings"/>) into
/// Playwright proxy options and/or Chrome <c>--proxy-server</c> args.
/// Direct port of the proxy helpers in Python <c>cloakbrowser/browser.py</c>.
/// </summary>
internal static class ProxyResolver
{
    private const string HttpProxyInlineAuthMinVersion = "146.0.7680.177.5";
    private static readonly IReadOnlySet<string> HttpProxyInlineAuthPlatforms =
        new HashSet<string> { "linux-x64", "windows-x64" };

    /// <summary>Result of resolving a proxy: Playwright proxy (or null) plus extra Chrome args.</summary>
    public sealed record ProxyResolution(Microsoft.Playwright.Proxy? PlaywrightProxy, List<string> ExtraArgs);

    // -- small URL parsing model -------------------------------------------------

    /// <summary>A minimal parsed proxy URL (mirrors the pieces Python's urlparse exposes).</summary>
    private sealed class ParsedUrl
    {
        public string Scheme = "";
        public string? Username; // null = absent, "" = present-but-empty
        public string? Password;
        public string Host = "";
        public int? Port;
        public string Path = "";
        public string Query = "";
        public string Fragment = "";
    }

    /// <summary>Prepend <c>http://</c> to schemeless proxy URLs so parsers can extract the hostname.</summary>
    public static string EnsureProxyScheme(string proxyUrl) =>
        proxyUrl.Contains("://") ? proxyUrl : $"http://{proxyUrl}";

    private static ParsedUrl ParseUrl(string url)
    {
        var p = new ParsedUrl();
        string rest = url;

        int schemeIdx = rest.IndexOf("://", StringComparison.Ordinal);
        if (schemeIdx >= 0)
        {
            p.Scheme = rest[..schemeIdx].ToLowerInvariant();
            rest = rest[(schemeIdx + 3)..];
        }

        // Split off fragment.
        int hashIdx = rest.IndexOf('#');
        if (hashIdx >= 0) { p.Fragment = rest[(hashIdx + 1)..]; rest = rest[..hashIdx]; }

        // Split off query.
        int qIdx = rest.IndexOf('?');
        if (qIdx >= 0) { p.Query = rest[(qIdx + 1)..]; rest = rest[..qIdx]; }

        // Split off path.
        int slashIdx = rest.IndexOf('/');
        string netloc;
        if (slashIdx >= 0) { p.Path = rest[slashIdx..]; netloc = rest[..slashIdx]; }
        else netloc = rest;

        // Userinfo.
        int atIdx = netloc.LastIndexOf('@');
        string hostport;
        if (atIdx >= 0)
        {
            string userinfo = netloc[..atIdx];
            hostport = netloc[(atIdx + 1)..];
            int colon = userinfo.IndexOf(':');
            if (colon >= 0)
            {
                p.Username = userinfo[..colon];
                p.Password = userinfo[(colon + 1)..];
            }
            else
            {
                p.Username = userinfo;
                p.Password = null;
            }
        }
        else
        {
            hostport = netloc;
        }

        // Host / port (handle IPv6 literal in brackets).
        if (hostport.StartsWith('['))
        {
            int close = hostport.IndexOf(']');
            p.Host = hostport[1..close];
            string after = hostport[(close + 1)..];
            if (after.StartsWith(':'))
                p.Port = ParsePort(after[1..]);
        }
        else
        {
            int colon = hostport.LastIndexOf(':');
            if (colon >= 0)
            {
                p.Host = hostport[..colon];
                p.Port = ParsePort(hostport[(colon + 1)..]);
            }
            else
            {
                p.Host = hostport;
            }
        }
        // Python's urlparse().hostname cosmetically lowercases the host; match it so
        // the assembled proxy URL/server string is byte-for-byte identical.
        p.Host = p.Host.ToLowerInvariant();
        return p;
    }

    private static int? ParsePort(string s)
    {
        if (string.IsNullOrEmpty(s)) return null;
        if (!int.TryParse(s, out var port) || port < 0 || port > 65535)
            throw new FormatException($"Invalid port: {s}");
        return port;
    }

    /// <summary>Percent-encode like Python's <c>quote(safe="")</c>.</summary>
    private static string Quote(string s) => Uri.EscapeDataString(s);

    /// <summary>Percent-decode like Python's <c>unquote</c>.</summary>
    private static string Unquote(string s) => Uri.UnescapeDataString(s);

    private static string AssembleProxyUrl(
        string scheme, string host, int? port,
        string encUser, string? encPass,
        string path = "", string query = "", string fragment = "")
    {
        if (host.Contains(':')) // IPv6 literal - re-add brackets
            host = $"[{host}]";
        string userinfo;
        if (encPass != null)
            userinfo = $"{encUser}:{encPass}@";
        else if (!string.IsNullOrEmpty(encUser))
            userinfo = $"{encUser}@";
        else
            userinfo = "";
        string netloc = $"{userinfo}{host}";
        if (port != null)
            netloc += $":{port}";
        var sb = new System.Text.StringBuilder();
        if (!string.IsNullOrEmpty(scheme)) sb.Append(scheme).Append("://");
        sb.Append(netloc).Append(path);
        if (!string.IsNullOrEmpty(query)) sb.Append('?').Append(query);
        if (!string.IsNullOrEmpty(fragment)) sb.Append('#').Append(fragment);
        return sb.ToString();
    }

    // -- SOCKS handling ----------------------------------------------------------

    public static bool IsSocksProxy(string? url) =>
        url != null && (url.StartsWith("socks5://", StringComparison.OrdinalIgnoreCase)
                        || url.StartsWith("socks5h://", StringComparison.OrdinalIgnoreCase));

    public static bool IsSocksProxy(ProxySettings proxy) => IsSocksProxy(proxy.Server);

    private static string ReconstructSocksUrl(ProxySettings proxy)
    {
        string server = proxy.Server;
        string username = proxy.Username ?? "";
        string password = proxy.Password ?? "";
        if (string.IsNullOrEmpty(username))
            return server;
        var parsed = ParseUrl(server);
        string encUser = Quote(username);
        string? encPass = string.IsNullOrEmpty(password) ? null : Quote(password);
        return AssembleProxyUrl(parsed.Scheme, parsed.Host, parsed.Port, encUser, encPass, parsed.Path);
    }

    private static string NormalizeSocksStringUrl(string url)
    {
        ParsedUrl parsed;
        try { parsed = ParseUrl(url); }
        catch (FormatException e)
        {
            CloakLog.Warning($"Malformed SOCKS5 proxy URL, passing through unchanged: {e.Message}");
            return url;
        }
        if (parsed.Username == null && parsed.Password == null)
            return url;
        string rawUser = parsed.Username ?? "";
        string encUser = string.IsNullOrEmpty(rawUser) ? "" : Quote(Unquote(rawUser));
        string? rawPass = parsed.Password;
        string? encPass = parsed.Password != null
            ? (string.IsNullOrEmpty(parsed.Password) ? "" : Quote(Unquote(parsed.Password)))
            : null;
        string normalized = AssembleProxyUrl(parsed.Scheme, parsed.Host, parsed.Port, encUser, encPass,
            parsed.Path, parsed.Query, parsed.Fragment);
        if (encUser != rawUser || encPass != rawPass)
            CloakLog.Info("Auto URL-encoded SOCKS5 proxy credentials (special characters detected). " +
                          "Pre-encode the URL to suppress this notice.");
        return normalized;
    }

    // -- HTTP handling -----------------------------------------------------------

    private static bool HasCredentials(ProxySettings proxy) => !string.IsNullOrEmpty(proxy.Username);
    private static bool HasCredentials(string proxy) => proxy.Contains('@');

    private static string ReconstructHttpUrl(ProxySettings proxy)
    {
        string server = proxy.Server;
        string username = proxy.Username ?? "";
        string password = proxy.Password ?? "";
        if (string.IsNullOrEmpty(username))
            return server;
        var parsed = ParseUrl(EnsureProxyScheme(server));
        string encUser = Quote(username);
        string? encPass = string.IsNullOrEmpty(password) ? null : Quote(password);
        return AssembleProxyUrl(parsed.Scheme, parsed.Host, parsed.Port, encUser, encPass, parsed.Path);
    }

    private static string NormalizeHttpStringUrl(string url)
    {
        string normalized = url.Contains("://") ? url : $"http://{url}";
        ParsedUrl parsed;
        try { parsed = ParseUrl(normalized); }
        catch (FormatException e)
        {
            CloakLog.Warning($"Malformed HTTP proxy URL, passing through unchanged: {e.Message}");
            return normalized;
        }
        if (parsed.Username == null && parsed.Password == null)
            return normalized;
        string rawUser = parsed.Username ?? "";
        string encUser = string.IsNullOrEmpty(rawUser) ? "" : Quote(Unquote(rawUser));
        string? rawPass = parsed.Password;
        string? encPass = parsed.Password != null
            ? (string.IsNullOrEmpty(parsed.Password) ? "" : Quote(Unquote(parsed.Password)))
            : null;
        string result = AssembleProxyUrl(parsed.Scheme, parsed.Host, parsed.Port, encUser, encPass,
            parsed.Path, parsed.Query, parsed.Fragment);
        if (encUser != rawUser || encPass != rawPass)
            CloakLog.Info("Auto URL-encoded HTTP proxy credentials (special characters detected). " +
                          "Pre-encode the URL to suppress this notice.");
        return result;
    }

    /// <summary>Parse an HTTP(S) proxy URL into a Playwright <see cref="Microsoft.Playwright.Proxy"/>.</summary>
    private static Microsoft.Playwright.Proxy ParseProxyUrl(string proxy)
    {
        string normalized = proxy;
        if (proxy.Contains('@') && !proxy.Contains("://"))
            normalized = $"http://{proxy}";

        var parsed = ParseUrl(normalized);
        if (string.IsNullOrEmpty(parsed.Username))
            return new Microsoft.Playwright.Proxy { Server = proxy };

        string netloc = parsed.Host;
        if (parsed.Port != null) netloc += $":{parsed.Port}";
        var sb = new System.Text.StringBuilder();
        if (!string.IsNullOrEmpty(parsed.Scheme)) sb.Append(parsed.Scheme).Append("://");
        sb.Append(netloc).Append(parsed.Path);

        var result = new Microsoft.Playwright.Proxy
        {
            Server = sb.ToString(),
            Username = Unquote(parsed.Username!),
        };
        if (!string.IsNullOrEmpty(parsed.Password))
            result.Password = Unquote(parsed.Password!);
        return result;
    }

    private static bool SupportsHttpProxyInlineAuth()
    {
        string tag = Config.GetPlatformTag();
        if (!HttpProxyInlineAuthPlatforms.Contains(tag))
            return false;
        return Compare(Config.GetChromiumVersion(), HttpProxyInlineAuthMinVersion) >= 0;
    }

    private static int Compare(string a, string b)
    {
        var ta = Config.VersionTuple(a);
        var tb = Config.VersionTuple(b);
        int n = Math.Max(ta.Length, tb.Length);
        for (int i = 0; i < n; i++)
        {
            int va = i < ta.Length ? ta[i] : 0;
            int vb = i < tb.Length ? tb[i] : 0;
            if (va != vb) return va.CompareTo(vb);
        }
        return 0;
    }

    /// <summary>Extract a normalized proxy URL string from a string or dict proxy (for geoip / webrtc).</summary>
    public static string? ExtractProxyUrl(object? proxy)
    {
        switch (proxy)
        {
            case null:
                return null;
            case ProxySettings ps:
                if (string.IsNullOrEmpty(ps.Server)) return null;
                return IsSocksProxy(ps) ? ReconstructSocksUrl(ps) : EnsureProxyScheme(ps.Server);
            case string s:
                return EnsureProxyScheme(s);
            default:
                return null;
        }
    }

    /// <summary>Resolve a proxy into Playwright options + extra Chrome args (one or both empty).</summary>
    public static ProxyResolution Resolve(object? proxy)
    {
        if (proxy == null)
            return new ProxyResolution(null, new List<string>());

        // SOCKS5: bypass Playwright, pass directly to Chrome via --proxy-server.
        bool socks = proxy switch
        {
            ProxySettings ps => IsSocksProxy(ps),
            string s => IsSocksProxy(s),
            _ => false,
        };
        if (socks)
        {
            if (proxy is ProxySettings psd)
            {
                string url = ReconstructSocksUrl(psd);
                var extra = new List<string> { $"--proxy-server={url}" };
                if (!string.IsNullOrEmpty(psd.Bypass))
                    extra.Add($"--proxy-bypass-list={psd.Bypass}");
                return new ProxyResolution(null, extra);
            }
            string sUrl = (string)proxy;
            return new ProxyResolution(null, new List<string> { $"--proxy-server={NormalizeSocksStringUrl(sUrl)}" });
        }

        // HTTP/HTTPS with credentials on supported platforms: inline creds via --proxy-server.
        bool hasCreds = proxy switch
        {
            ProxySettings ps => HasCredentials(ps),
            string s => HasCredentials(s),
            _ => false,
        };
        if (hasCreds && SupportsHttpProxyInlineAuth())
        {
            if (proxy is ProxySettings psd)
            {
                string url = ReconstructHttpUrl(psd);
                var extra = new List<string> { $"--proxy-server={url}" };
                if (!string.IsNullOrEmpty(psd.Bypass))
                    extra.Add($"--proxy-bypass-list={psd.Bypass}");
                return new ProxyResolution(null, extra);
            }
            string sUrl = (string)proxy;
            return new ProxyResolution(null, new List<string> { $"--proxy-server={NormalizeHttpStringUrl(sUrl)}" });
        }

        // HTTP/HTTPS without credentials: use Playwright's proxy.
        if (proxy is ProxySettings dict)
        {
            return new ProxyResolution(new Microsoft.Playwright.Proxy
            {
                Server = dict.Server,
                Bypass = dict.Bypass,
                Username = dict.Username,
                Password = dict.Password,
            }, new List<string>());
        }
        return new ProxyResolution(ParseProxyUrl((string)proxy), new List<string>());
    }
}
