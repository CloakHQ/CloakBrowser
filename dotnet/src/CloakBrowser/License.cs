using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace CloakBrowser;

/// <summary>
/// Result of a CloakBrowser Pro license validation.
/// Mirrors the Python <c>LicenseInfo</c> dataclass / JS <c>LicenseInfo</c> interface.
/// </summary>
public sealed record LicenseInfo(bool Valid, string Plan, string? Expires);

/// <summary>
/// License validation and caching for CloakBrowser Pro.
///
/// Handles license-key resolution (param -> env -> file), server validation with a
/// local 24h cache, and Pro version lookups. Direct port of Python
/// <c>cloakbrowser/license.py</c> and JS <c>js/src/license.ts</c>.
/// </summary>
public static class License
{
    public const string ValidateUrl = "https://cloakbrowser.dev/api/license/validate";
    public const string ProVersionUrl = "https://cloakbrowser.dev/api/download/version";

    // 24 hours / 1 hour, in seconds (matches Python's LICENSE_CACHE_TTL / PRO_VERSION_CHECK_INTERVAL).
    private const double LicenseCacheTtl = 86400;
    private const double ProVersionCheckInterval = 3600;

    private static readonly HttpClient Http = CreateHttpClient();

    private static HttpClient CreateHttpClient()
    {
        var client = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };
        client.DefaultRequestHeaders.UserAgent.ParseAdd($"cloakbrowser-dotnet/{CloakVersion.Version}");
        return client;
    }

    // -----------------------------------------------------------------------
    // Testing seams - mirror the monkey-patching the Python/JS tests rely on.
    // Null means "use real behavior" (HTTP). Tests inject deterministic results
    // without touching the network.
    // -----------------------------------------------------------------------

    /// <summary>Overrides the server license-validation call for tests. Null -> real HTTP.</summary>
    internal static Func<string, LicenseInfo?>? ValidateLicenseOverride;

    /// <summary>Overrides the Pro latest-version lookup for tests. Null -> real HTTP.</summary>
    internal static Func<string?>? ProLatestVersionOverride;

    // -----------------------------------------------------------------------

    /// <summary>Resolve the license key: explicit param &gt; env var &gt; file &gt; null.</summary>
    public static string? ResolveLicenseKey(string? licenseKey = null)
    {
        var trimmed = licenseKey?.Trim();
        if (!string.IsNullOrEmpty(trimmed))
            return trimmed;

        var envKey = (Environment.GetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY") ?? "").Trim();
        if (!string.IsNullOrEmpty(envKey))
            return envKey;

        try
        {
            var keyFile = Path.Combine(Config.GetCacheDir(), "license.key");
            var content = File.ReadAllText(keyFile).Trim();
            if (!string.IsNullOrEmpty(content))
                return content;
        }
        catch (IOException) { /* file missing/unreadable */ }
        catch (UnauthorizedAccessException) { }

        return null;
    }

    /// <summary>
    /// Validate a license key with the CloakBrowser server.
    ///
    /// Checks a local file cache first (24h TTL). Falls back to a stale cache if the
    /// server is unreachable. Returns the <see cref="LicenseInfo"/> on success, or
    /// null on total failure (server unreachable and no cache).
    /// </summary>
    public static LicenseInfo? ValidateLicense(string licenseKey)
    {
        if (ValidateLicenseOverride != null)
            return ValidateLicenseOverride(licenseKey);

        var cachePath = Path.Combine(Config.GetCacheDir(), ".license_cache");
        var keySha = Sha256Hex(licenseKey);

        var cached = ReadCache(cachePath, keySha);
        if (cached != null)
            return cached;

        try
        {
            var body = new StringContent(
                JsonSerializer.Serialize(new Dictionary<string, string> { ["license_key"] = licenseKey }),
                Encoding.UTF8, "application/json");
            using var resp = Http.PostAsync(ValidateUrl, body).GetAwaiter().GetResult();
            resp.EnsureSuccessStatusCode();
            var json = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;

            var info = new LicenseInfo(
                Valid: root.TryGetProperty("valid", out var v) && v.ValueKind == JsonValueKind.True,
                Plan: root.TryGetProperty("plan", out var p) && p.ValueKind == JsonValueKind.String
                    ? p.GetString() ?? "solo" : "solo",
                Expires: root.TryGetProperty("expires", out var e) && e.ValueKind == JsonValueKind.String
                    ? e.GetString() : null);

            if (info.Valid)
                WriteCache(cachePath, keySha, info);
            return info;
        }
        catch (Exception ex)
        {
            CloakLog.Warning("License validation request failed: {0}", ex.Message);

            var stale = ReadCache(cachePath, keySha, ignoreTtl: true);
            if (stale != null)
            {
                CloakLog.Warning("Using cached license validation (server unreachable)");
                return stale;
            }
            return null;
        }
    }

    /// <summary>
    /// Get the latest Pro binary version from the server.
    /// Rate-limited to 1 call per hour via a marker file.
    /// </summary>
    public static string? GetProLatestVersion()
    {
        if (ProLatestVersionOverride != null)
            return ProLatestVersionOverride();

        var marker = Path.Combine(Config.GetCacheDir(), ".last_pro_version_check");

        if (File.Exists(marker))
        {
            try
            {
                var age = (DateTime.UtcNow - File.GetLastWriteTimeUtc(marker)).TotalSeconds;
                if (age < ProVersionCheckInterval)
                {
                    var content = File.ReadAllText(marker).Trim();
                    return string.IsNullOrEmpty(content) ? null : content;
                }
            }
            catch (IOException) { /* unreadable - proceed with fetch */ }
        }

        try
        {
            using var resp = Http.GetAsync(ProVersionUrl).GetAwaiter().GetResult();
            resp.EnsureSuccessStatusCode();
            var json = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            using var doc = JsonDocument.Parse(json);
            var version = doc.RootElement.TryGetProperty("version", out var ve) && ve.ValueKind == JsonValueKind.String
                ? ve.GetString() : null;
            if (string.IsNullOrEmpty(version))
                return null;

            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(marker)!);
                var tmp = marker + ".tmp";
                File.WriteAllText(tmp, version);
                if (File.Exists(marker)) File.Delete(marker);
                File.Move(tmp, marker);
            }
            catch (IOException) { /* non-fatal */ }

            return version;
        }
        catch (Exception ex)
        {
            CloakLog.Debug("Pro version check failed: {0}", ex.Message);
            return null;
        }
    }

    // -----------------------------------------------------------------------
    // Cache helpers (atomic write via tmp+rename, like Python/JS).
    // -----------------------------------------------------------------------

    private sealed record CacheData(
        string? key_sha256, bool valid, string? plan, string? expires, double validated_at);

    private static LicenseInfo? ReadCache(string cachePath, string keySha, bool ignoreTtl = false)
    {
        try
        {
            if (!File.Exists(cachePath))
                return null;

            using var doc = JsonDocument.Parse(File.ReadAllText(cachePath));
            var root = doc.RootElement;

            var cachedSha = root.TryGetProperty("key_sha256", out var ks) && ks.ValueKind == JsonValueKind.String
                ? ks.GetString() : null;
            if (cachedSha != keySha)
                return null;

            if (!ignoreTtl)
            {
                // A non-numeric validated_at (corrupted cache) is treated as absent
                // rather than silently trusting the entry.
                if (!root.TryGetProperty("validated_at", out var va) || va.ValueKind != JsonValueKind.Number)
                    return null;
                var validatedAt = va.GetDouble();
                var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
                if (now - validatedAt > LicenseCacheTtl)
                    return null;
            }

            var plan = root.TryGetProperty("plan", out var pe) && pe.ValueKind == JsonValueKind.String
                ? pe.GetString() ?? "solo" : "solo";
            var expires = root.TryGetProperty("expires", out var ee) && ee.ValueKind == JsonValueKind.String
                ? ee.GetString() : null;
            var valid = root.TryGetProperty("valid", out var ve) && ve.ValueKind == JsonValueKind.True;

            // An expired license is reported invalid even if it was cached as valid.
            if (!string.IsNullOrEmpty(expires))
            {
                if (DateTimeOffset.TryParse(expires, System.Globalization.CultureInfo.InvariantCulture,
                        System.Globalization.DateTimeStyles.AssumeUniversal | System.Globalization.DateTimeStyles.AdjustToUniversal,
                        out var expDt))
                {
                    if (expDt < DateTimeOffset.UtcNow)
                        return new LicenseInfo(false, plan, expires);
                }
            }

            return new LicenseInfo(valid, plan, expires);
        }
        catch (Exception ex) when (ex is JsonException or IOException or UnauthorizedAccessException)
        {
            // Any unreadable/corrupt cache is treated as absent rather than crashing.
            return null;
        }
    }

    private static void WriteCache(string cachePath, string keySha, LicenseInfo info)
    {
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(cachePath)!);
            var tmpPath = cachePath + ".tmp";
            var now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() / 1000.0;
            var payload = JsonSerializer.Serialize(new CacheData(
                key_sha256: keySha, valid: info.Valid, plan: info.Plan,
                expires: info.Expires, validated_at: now));
            File.WriteAllText(tmpPath, payload);
            if (File.Exists(cachePath)) File.Delete(cachePath);
            File.Move(tmpPath, cachePath);
        }
        catch (IOException ex)
        {
            CloakLog.Debug("Failed to write license cache: {0}", ex.Message);
        }
    }

    private static string Sha256Hex(string s)
    {
        var bytes = SHA256.HashData(Encoding.UTF8.GetBytes(s));
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }
}
