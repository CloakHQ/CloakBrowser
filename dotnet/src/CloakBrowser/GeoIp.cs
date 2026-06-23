using System.Globalization;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using MaxMind.GeoIP2;

namespace CloakBrowser;

/// <summary>
/// GeoIP-based timezone and locale detection from a proxy IP.
/// Downloads GeoLite2-City.mmdb (~70 MB) on first use, caches in
/// <c>~/.cloakbrowser/geoip/</c>. Background re-download after 30 days.
/// Direct port of Python <c>cloakbrowser/geoip.py</c>.
/// </summary>
public static class GeoIp
{
    // P3TERX mirror of MaxMind GeoLite2-City - no license key needed.
    private const string GeoIpDbUrl =
        "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb";
    private const string GeoIpDbFilename = "GeoLite2-City.mmdb";
    private const long GeoIpUpdateInterval = 30L * 86_400; // 30 days (seconds)
    private const double DefaultGeoIpTimeoutSeconds = 5.0;
    private const string GeoIpTimeoutEnv = "CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS";

    // IP echo services - fast, no auth, return just the IP.
    private static readonly string[] IpEchoUrls =
    {
        "https://api.ipify.org",
        "https://checkip.amazonaws.com",
        "https://ifconfig.me/ip",
    };

    /// <summary>Country ISO code -> BCP 47 locale (covers ~90% of proxy traffic).</summary>
    public static readonly IReadOnlyDictionary<string, string> CountryLocaleMap =
        new Dictionary<string, string>
        {
            ["US"] = "en-US", ["GB"] = "en-GB", ["AU"] = "en-AU", ["CA"] = "en-CA", ["NZ"] = "en-NZ",
            ["IE"] = "en-IE", ["ZA"] = "en-ZA", ["SG"] = "en-SG",
            ["DE"] = "de-DE", ["AT"] = "de-AT", ["CH"] = "de-CH",
            ["FR"] = "fr-FR", ["BE"] = "fr-BE",
            ["ES"] = "es-ES", ["MX"] = "es-MX", ["AR"] = "es-AR", ["CO"] = "es-CO", ["CL"] = "es-CL",
            ["BR"] = "pt-BR", ["PT"] = "pt-PT",
            ["IT"] = "it-IT", ["NL"] = "nl-NL",
            ["JP"] = "ja-JP", ["KR"] = "ko-KR", ["CN"] = "zh-CN", ["TW"] = "zh-TW", ["HK"] = "zh-HK",
            ["RU"] = "ru-RU", ["UA"] = "uk-UA", ["PL"] = "pl-PL", ["CZ"] = "cs-CZ", ["RO"] = "ro-RO",
            ["IL"] = "he-IL", ["TR"] = "tr-TR", ["SA"] = "ar-SA", ["AE"] = "ar-AE", ["EG"] = "ar-EG",
            ["IN"] = "hi-IN", ["ID"] = "id-ID", ["PH"] = "en-PH",
            ["TH"] = "th-TH", ["VN"] = "vi-VN", ["MY"] = "ms-MY",
            ["SE"] = "sv-SE", ["NO"] = "nb-NO", ["DK"] = "da-DK", ["FI"] = "fi-FI",
            ["GR"] = "el-GR", ["HU"] = "hu-HU", ["BG"] = "bg-BG",
        };

    /// <summary>
    /// Resolve timezone and locale from a proxy's IP address.
    /// Returns (timezone, locale) - either or both may be null on failure. Never throws.
    /// </summary>
    public static async Task<(string? Timezone, string? Locale)> ResolveProxyGeoAsync(
        string proxyUrl, CancellationToken ct = default)
    {
        var (tz, locale, _) = await ResolveProxyGeoWithIpAsync(proxyUrl, ct).ConfigureAwait(false);
        return (tz, locale);
    }

    /// <summary>
    /// Resolve timezone, locale, and exit IP from a proxy.
    /// The exit IP is a free bonus from the lookup - reused for WebRTC spoofing
    /// without an extra HTTP call.
    /// </summary>
    public static async Task<(string? Timezone, string? Locale, string? ExitIp)> ResolveProxyGeoWithIpAsync(
        string proxyUrl, CancellationToken ct = default)
    {
        var dbPath = await EnsureGeoIpDbAsync(ct).ConfigureAwait(false);
        if (dbPath == null)
            return (null, null, null);

        var timeout = GetGeoIpTimeoutSeconds();
        var deadline = DeadlineFromTimeout(timeout);

        // Exit IP (through proxy) is most accurate - gateway DNS may differ from exit.
        var ip = await ResolveExitIpAsync(proxyUrl, RemainingSeconds(deadline), ct).ConfigureAwait(false);
        if (ip == null && !DeadlineExpired(deadline))
            ip = ResolveProxyIp(proxyUrl);
        if (ip == null || DeadlineExpired(deadline))
        {
            if (deadline != null && DeadlineExpired(deadline))
                CloakLog.Warning("GeoIP resolution timed out after {0:0.0}s; continuing without GeoIP", timeout);
            return (null, null, null);
        }

        try
        {
            using var reader = new DatabaseReader(dbPath);
            var resp = reader.City(ip);
            var timezone = resp.Location?.TimeZone;
            var country = resp.Country?.IsoCode;
            string? locale = country != null && CountryLocaleMap.TryGetValue(country, out var l) ? l : null;
            CloakLog.Debug("GeoIP: {0} -> tz={1}, country={2}, locale={3}", ip, timezone, country, locale);
            return (timezone, locale, ip);
        }
        catch (Exception exc)
        {
            CloakLog.Warning("GeoIP lookup failed for {0}: {1}", ip, exc.Message);
            return (null, null, ip);
        }
    }

    // -----------------------------------------------------------------------
    // Proxy IP resolution
    // -----------------------------------------------------------------------

    private static string? ResolveProxyIp(string proxyUrl)
    {
        try
        {
            if (!Uri.TryCreate(proxyUrl, UriKind.Absolute, out var uri))
                return null;
            var hostname = uri.Host;
            if (string.IsNullOrEmpty(hostname))
                return null;

            // Already a literal IP?
            if (IPAddress.TryParse(hostname, out var literal))
                return literal.ToString();

            // DNS resolve (returns first result, handles both v4/v6).
            var results = Dns.GetHostAddresses(hostname);
            if (results.Length > 0)
            {
                var ip = results[0].ToString();
                CloakLog.Debug("Resolved proxy {0} -> {1}", hostname, ip);
                return ip;
            }
            return null;
        }
        catch (Exception exc)
        {
            CloakLog.Warning("Failed to resolve proxy hostname: {0}", exc.Message);
            return null;
        }
    }

    /// <summary>Check if an IP address is private/internal (not routable on the internet).</summary>
    public static bool IsPrivateIp(string ip)
    {
        if (!IPAddress.TryParse(ip, out var addr)) return false;
        if (addr.AddressFamily == AddressFamily.InterNetwork)
        {
            var b = addr.GetAddressBytes();
            return b[0] == 10
                || (b[0] == 172 && b[1] >= 16 && b[1] <= 31)
                || (b[0] == 192 && b[1] == 168)
                || b[0] == 127
                || (b[0] == 169 && b[1] == 254);
        }
        return IPAddress.IsLoopback(addr) || addr.IsIPv6LinkLocal || addr.IsIPv6SiteLocal;
    }

    private static double GetGeoIpTimeoutSeconds()
    {
        var raw = Environment.GetEnvironmentVariable(GeoIpTimeoutEnv);
        if (string.IsNullOrEmpty(raw)) return DefaultGeoIpTimeoutSeconds;
        if (!double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture, out var timeout)
            || double.IsNaN(timeout) || double.IsInfinity(timeout))
        {
            CloakLog.Warning("Invalid {0}={1}; using {2:0.0}s", GeoIpTimeoutEnv, raw, DefaultGeoIpTimeoutSeconds);
            return DefaultGeoIpTimeoutSeconds;
        }
        return Math.Max(timeout, 0.0);
    }

    private static double? DeadlineFromTimeout(double timeout) =>
        timeout <= 0 ? null : Now() + timeout;

    private static double? RemainingSeconds(double? deadline) =>
        deadline == null ? null : Math.Max(deadline.Value - Now(), 0.0);

    private static bool DeadlineExpired(double? deadline) =>
        deadline != null && Now() >= deadline.Value;

    private static double Now() =>
        System.Diagnostics.Stopwatch.GetTimestamp() / (double)System.Diagnostics.Stopwatch.Frequency;

    /// <summary>Resolve only the proxy exit IP, bounded by the GeoIP timeout.</summary>
    public static async Task<string?> ResolveProxyExitIpAsync(string proxyUrl, CancellationToken ct = default)
    {
        var timeout = GetGeoIpTimeoutSeconds();
        var deadline = DeadlineFromTimeout(timeout);
        var ip = await ResolveExitIpAsync(proxyUrl, timeout, ct).ConfigureAwait(false);
        if (ip == null && DeadlineExpired(deadline))
            CloakLog.Warning("GeoIP resolution timed out after {0:0.0}s; continuing without GeoIP", timeout);
        return ip;
    }

    private static async Task<string?> ResolveExitIpAsync(string proxyUrl, double? timeout, CancellationToken ct)
    {
        var deadline = DeadlineFromTimeout(timeout ?? 0);

        HttpClient client;
        try
        {
            var handler = new HttpClientHandler
            {
                Proxy = new WebProxy(NormalizeProxyForWebProxy(proxyUrl)),
                UseProxy = true,
            };
            var creds = ExtractProxyCredentials(proxyUrl);
            if (creds != null)
                handler.Proxy.Credentials = creds;
            client = new HttpClient(handler);
        }
        catch (Exception)
        {
            CloakLog.Warning("SOCKS5 proxy requires a SOCKS-capable transport; cannot resolve exit IP");
            return null;
        }

        try
        {
            foreach (var url in IpEchoUrls)
            {
                try
                {
                    var remaining = RemainingSeconds(deadline);
                    if (remaining != null && remaining <= 0)
                        return null;
                    var requestTimeout = remaining != null
                        ? TimeSpan.FromSeconds(Math.Min(10.0, remaining.Value))
                        : TimeSpan.FromSeconds(10.0);
                    using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                    cts.CancelAfter(requestTimeout);
                    var resp = await client.GetAsync(url, cts.Token).ConfigureAwait(false);
                    resp.EnsureSuccessStatusCode();
                    var ip = (await resp.Content.ReadAsStringAsync(cts.Token).ConfigureAwait(false)).Trim();
                    if (IPAddress.TryParse(ip, out _))
                    {
                        CloakLog.Debug("Exit IP via {0}: {1}", url, ip);
                        return ip;
                    }
                }
                catch (Exception) { /* try next */ }
            }
            CloakLog.Warning("Failed to discover exit IP through proxy");
            return null;
        }
        finally
        {
            client.Dispose();
        }
    }

    private static string NormalizeProxyForWebProxy(string proxyUrl)
    {
        // WebProxy wants scheme://host:port without credentials.
        if (!Uri.TryCreate(proxyUrl.Contains("://") ? proxyUrl : "http://" + proxyUrl,
                UriKind.Absolute, out var uri))
            return proxyUrl;
        var builder = new UriBuilder(uri.Scheme, uri.Host, uri.Port) { Path = uri.AbsolutePath };
        return builder.Uri.ToString();
    }

    private static NetworkCredential? ExtractProxyCredentials(string proxyUrl)
    {
        if (!Uri.TryCreate(proxyUrl.Contains("://") ? proxyUrl : "http://" + proxyUrl,
                UriKind.Absolute, out var uri))
            return null;
        if (string.IsNullOrEmpty(uri.UserInfo))
            return null;
        var parts = uri.UserInfo.Split(':', 2);
        var user = Uri.UnescapeDataString(parts[0]);
        var pass = parts.Length > 1 ? Uri.UnescapeDataString(parts[1]) : "";
        return new NetworkCredential(user, pass);
    }

    // -----------------------------------------------------------------------
    // GeoIP database management
    // -----------------------------------------------------------------------

    private static string GetGeoIpDir() => Path.Combine(Config.GetCacheDir(), "geoip");

    private static async Task<string?> EnsureGeoIpDbAsync(CancellationToken ct)
    {
        var dbPath = Path.Combine(GetGeoIpDir(), GeoIpDbFilename);

        if (File.Exists(dbPath))
        {
            MaybeTriggerUpdate(dbPath);
            return dbPath;
        }

        try
        {
            await DownloadGeoIpDbAsync(dbPath, ct).ConfigureAwait(false);
            return dbPath;
        }
        catch (Exception exc)
        {
            CloakLog.Warning("Failed to download GeoIP database: {0}", exc.Message);
            return null;
        }
    }

    private static async Task DownloadGeoIpDbAsync(string dest, CancellationToken ct)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
        CloakLog.Info("Downloading GeoIP database (~70 MB) ...");

        var tmpPath = dest + "." + Guid.NewGuid().ToString("N") + ".tmp";
        using var client = new HttpClient { Timeout = TimeSpan.FromSeconds(300) };
        try
        {
            using var resp = await client.GetAsync(GeoIpDbUrl, HttpCompletionOption.ResponseHeadersRead, ct)
                .ConfigureAwait(false);
            resp.EnsureSuccessStatusCode();
            long total = resp.Content.Headers.ContentLength ?? 0;
            long downloaded = 0;
            int lastPct = -1;

            await using (var src = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false))
            await using (var fs = new FileStream(tmpPath, FileMode.Create, FileAccess.Write, FileShare.None))
            {
                var buffer = new byte[65_536];
                int read;
                while ((read = await src.ReadAsync(buffer, ct).ConfigureAwait(false)) > 0)
                {
                    await fs.WriteAsync(buffer.AsMemory(0, read), ct).ConfigureAwait(false);
                    downloaded += read;
                    if (total > 0)
                    {
                        int pct = (int)(downloaded * 100 / total);
                        if (pct >= lastPct + 10)
                        {
                            lastPct = pct;
                            CloakLog.Info("GeoIP download: {0} %", pct);
                        }
                    }
                }
            }

            if (File.Exists(dest)) File.Delete(dest);
            File.Move(tmpPath, dest);
            CloakLog.Info("GeoIP database ready: {0}", dest);
        }
        catch (Exception)
        {
            try { if (File.Exists(tmpPath)) File.Delete(tmpPath); } catch (IOException) { }
            throw;
        }
    }

    private static void MaybeTriggerUpdate(string dbPath)
    {
        try
        {
            var age = (DateTime.UtcNow - File.GetLastWriteTimeUtc(dbPath)).TotalSeconds;
            if (age < GeoIpUpdateInterval)
                return;
        }
        catch (IOException)
        {
            return;
        }

        _ = Task.Run(async () =>
        {
            try { await DownloadGeoIpDbAsync(dbPath, CancellationToken.None).ConfigureAwait(false); }
            catch (Exception) { CloakLog.Debug("Background GeoIP update failed"); }
        });
    }
}
