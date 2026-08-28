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

    // Serializes GeoIP DB downloads within the process so N concurrent launches
    // don't each fetch the same ~70 MB file (issue #458). Per-process only.
    private static readonly SemaphoreSlim GeoIpDownloadGate = new(1, 1);
    private const double DefaultGeoIpTimeoutSeconds = 20.0;
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
            // Extended coverage - common residential/mobile proxy exits
            ["SI"] = "sl-SI", ["SK"] = "sk-SK", ["HR"] = "hr-HR", ["RS"] = "sr-RS", ["LT"] = "lt-LT",
            ["LV"] = "lv-LV", ["EE"] = "et-EE", ["IS"] = "is-IS", ["LU"] = "fr-LU", ["MT"] = "en-MT",
            ["CY"] = "el-CY", ["MD"] = "ro-MD", ["BY"] = "ru-BY", ["GE"] = "ka-GE", ["AL"] = "sq-AL",
            ["MK"] = "mk-MK", ["BA"] = "bs-BA",
            ["PE"] = "es-PE", ["VE"] = "es-VE", ["EC"] = "es-EC", ["UY"] = "es-UY", ["CR"] = "es-CR",
            ["DO"] = "es-DO", ["GT"] = "es-GT", ["BO"] = "es-BO", ["PY"] = "es-PY",
            ["PK"] = "en-PK", ["BD"] = "bn-BD", ["LK"] = "si-LK", ["KZ"] = "ru-KZ", ["IR"] = "fa-IR",
            ["IQ"] = "ar-IQ", ["JO"] = "ar-JO", ["LB"] = "ar-LB", ["KW"] = "ar-KW", ["QA"] = "ar-QA",
            ["OM"] = "ar-OM", ["BH"] = "ar-BH",
            ["NG"] = "en-NG", ["KE"] = "en-KE", ["MA"] = "fr-MA", ["DZ"] = "ar-DZ", ["TN"] = "ar-TN",
            ["GH"] = "en-GH",
            ["AM"] = "hy-AM", ["AZ"] = "az-AZ", ["UZ"] = "uz-UZ", ["KG"] = "ky-KG", ["TJ"] = "tg-TJ",
            ["TM"] = "tk-TM",
            ["ME"] = "sr-ME", ["XK"] = "sq-XK", ["LI"] = "de-LI", ["MC"] = "fr-MC", ["AD"] = "ca-AD",
            ["MM"] = "my-MM", ["KH"] = "km-KH", ["LA"] = "lo-LA", ["MN"] = "mn-MN", ["BN"] = "ms-BN",
            ["MO"] = "zh-MO",
            ["YE"] = "ar-YE", ["SY"] = "ar-SY", ["PS"] = "ar-PS", ["LY"] = "ar-LY",
            ["ET"] = "am-ET", ["TZ"] = "sw-TZ", ["UG"] = "en-UG", ["SN"] = "fr-SN", ["CI"] = "fr-CI",
            ["CM"] = "fr-CM", ["AO"] = "pt-AO", ["MZ"] = "pt-MZ", ["ZM"] = "en-ZM", ["ZW"] = "en-ZW",
            ["HN"] = "es-HN", ["NI"] = "es-NI", ["SV"] = "es-SV", ["PA"] = "es-PA", ["JM"] = "en-JM",
            ["TT"] = "en-TT", ["PR"] = "es-PR",
        };

    /// <summary>
    /// Resolve timezone and locale from a proxy's IP address.
    /// Throws when the exit IP, database, or database lookup cannot be resolved.
    /// </summary>
    public static async Task<(string? Timezone, string? Locale)> ResolveProxyGeoAsync(
        string? proxyUrl, CancellationToken ct = default)
    {
        var (tz, locale, _) = await ResolveProxyGeoWithIpAsync(proxyUrl, ct).ConfigureAwait(false);
        return (tz, locale);
    }

    /// <summary>
    /// Resolve timezone, locale, and exit IP from a proxy.
    /// The exit IP is a free bonus from the lookup - reused for WebRTC spoofing
    /// without an extra HTTP call. When <paramref name="proxyUrl"/> is null/empty,
    /// the machine's own public IP is used (echo services queried directly), so
    /// geoip works proxy-free too.
    /// </summary>
    public static async Task<(string? Timezone, string? Locale, string? ExitIp)> ResolveProxyGeoWithIpAsync(
        string? proxyUrl, CancellationToken ct = default)
    {
        // Ensure the DB first - the download must NOT be bounded by the resolution
        // timeout (a first-use ~70MB fetch legitimately outlasts it).
        var dbPath = await EnsureGeoIpDbAsync(ct).ConfigureAwait(false);

        var timeout = GetGeoIpTimeoutSeconds();
        var deadline = DeadlineFromTimeout(timeout);

        // Exit IP (through proxy, or the machine's own public IP when proxyUrl is
        // null/empty) is most accurate - gateway DNS may differ from exit. Resolved
        // even when the DB is unavailable: the IP does not need the DB, and dropping
        // it on a DB hiccup would let WebRTC fall back to the real IP behind a proxy
        // while the connection shows the proxy IP - a real deanonymization.
        var ip = await ResolveExitIpAsync(proxyUrl, RemainingSeconds(deadline), ct).ConfigureAwait(false);
        // Hostname fallback only applies to a proxy; no proxy -> echo services only.
        if (ip == null && !string.IsNullOrEmpty(proxyUrl) && !DeadlineExpired(deadline))
            ip = ResolveProxyIp(proxyUrl);
        if (ip == null || DeadlineExpired(deadline))
        {
            if (deadline != null && DeadlineExpired(deadline))
                throw new InvalidOperationException($"GeoIP resolution timed out after {timeout:0.0}s");
            throw new InvalidOperationException("GeoIP resolution failed: could not discover the egress IP");
        }

        if (dbPath == null)
            throw new InvalidOperationException("GeoIP resolution failed: GeoIP database is unavailable");

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
            throw new InvalidOperationException($"GeoIP lookup failed for {ip}: {exc.Message}", exc);
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

    /// <summary>
    /// Resolve the egress IP, bounded by the GeoIP timeout. With a proxy this is
    /// the proxy's exit IP; with no proxy it is the machine's own public IP
    /// (echo services queried directly).
    /// </summary>
    public static async Task<string?> ResolveProxyExitIpAsync(string? proxyUrl, CancellationToken ct = default)
    {
        var timeout = GetGeoIpTimeoutSeconds();
        var deadline = DeadlineFromTimeout(timeout);
        var ip = await ResolveExitIpAsync(proxyUrl, timeout, ct).ConfigureAwait(false);
        if (ip == null && DeadlineExpired(deadline))
            CloakLog.Warning("Proxy exit-IP resolution timed out after {0:0.0}s", timeout);
        return ip;
    }

    private static async Task<string?> ResolveExitIpAsync(string? proxyUrl, double? timeout, CancellationToken ct)
    {
        var deadline = DeadlineFromTimeout(timeout ?? 0);
        var direct = string.IsNullOrEmpty(proxyUrl);

        HttpClient client;
        try
        {
            if (direct)
            {
                // No proxy: query the echo services directly -> the machine's own public IP.
                client = new HttpClient();
            }
            else
            {
                var handler = new HttpClientHandler
                {
                    Proxy = new WebProxy(NormalizeProxyForWebProxy(proxyUrl!)),
                    UseProxy = true,
                };
                var creds = ExtractProxyCredentials(proxyUrl!);
                if (creds != null)
                    handler.Proxy.Credentials = creds;
                client = new HttpClient(handler);
            }
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
            CloakLog.Warning(direct ? "Failed to discover public IP" : "Failed to discover exit IP through proxy");
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

        // Serialize concurrent first-use downloads: only one launch fetches
        // the shared file, the rest wait and reuse it.
        await GeoIpDownloadGate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            if (File.Exists(dbPath)) // another launch finished while we waited
                return dbPath;
            await DownloadGeoIpDbAsync(dbPath, ct).ConfigureAwait(false);
            return dbPath;
        }
        catch (Exception exc)
        {
            CloakLog.Warning("Failed to download GeoIP database: {0}", exc.Message);
            return null;
        }
        finally
        {
            GeoIpDownloadGate.Release();
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

            File.Move(tmpPath, dest, overwrite: true); // atomic overwrite (net8.0)
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
            // Skip if a download (initial or refresh) is already running.
            if (!await GeoIpDownloadGate.WaitAsync(0).ConfigureAwait(false))
                return;
            try { await DownloadGeoIpDbAsync(dbPath, CancellationToken.None).ConfigureAwait(false); }
            catch (Exception) { CloakLog.Debug("Background GeoIP update failed"); }
            finally { GeoIpDownloadGate.Release(); }
        });
    }
}
