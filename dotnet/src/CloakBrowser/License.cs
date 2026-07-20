using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace CloakBrowser;

/// <summary>
/// Result of a CloakBrowser Pro license validation.
/// Mirrors the Python <c>LicenseInfo</c> dataclass / JS <c>LicenseInfo</c> interface.
/// </summary>
public sealed record LicenseInfo(bool Valid, string Plan, string? Expires);

/// <summary>
/// The Pro binary refused to run for a license reason. Thrown when a launch fails
/// and the browser process exited with one of the Pro binary's license exit codes,
/// carrying a human-readable reason instead of the opaque "target/browser closed"
/// error the caller would otherwise see. Mirrors Python/JS
/// <c>CloakBrowserLicenseError</c>.
/// </summary>
public sealed class CloakBrowserLicenseError : Exception
{
    public CloakBrowserLicenseError(string message) : base(message) { }
    public CloakBrowserLicenseError(string message, Exception inner) : base(message, inner) { }
}

/// <summary>
/// Source of a resolved license key.  Determines whether env injection
/// into the child browser process is needed.
/// </summary>
internal enum LicenseKeySource
{
    /// <summary>Explicit <c>licenseKey</c> param.</summary>
    Param,
    /// <summary><c>CLOAKBROWSER_LICENSE_KEY</c> env var.</summary>
    Env,
    /// <summary>Default <c>~/.cloakbrowser/license.key</c> (binary reads it directly).</summary>
    DefaultFile,
    /// <summary>Custom cache dir <c>license.key</c> (binary can't see it).</summary>
    CustomFile,
    /// <summary>No key resolved.</summary>
    None,
}

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
    public const string SessionCountUrl = "https://cloakbrowser.dev/api/license/session/count";

    // 24 hours / 1 hour, in seconds (matches Python's LICENSE_CACHE_TTL / PRO_VERSION_CHECK_INTERVAL).
    private const double LicenseCacheTtl = 86400;
    private const double ProVersionCheckInterval = 3600;

    // Not readonly so tests can swap in an HttpClient backed by a recording
    // handler to exercise the real request path (header, etc.) without network.
    internal static HttpClient Http = CreateHttpClient();

    private static HttpClient CreateHttpClient()
    {
        var client = new HttpClient { Timeout = TimeSpan.FromSeconds(10) };
        client.DefaultRequestHeaders.UserAgent.ParseAdd($"cloakbrowser-dotnet/{CloakVersion.Version}");
        return client;
    }

    // Exit codes the Pro binary uses for honest-user license denials. The binary
    // emits only the number (no diagnostic strings, by design); the message text
    // lives here in the wrapper. Mirrors Python _LICENSE_EXIT_MESSAGES / JS
    // LICENSE_EXIT_MESSAGES.
    private static readonly Dictionary<int, string> LicenseExitMessages = new()
    {
        [76] = "CloakBrowser Pro: session limit reached for your plan. Close another running session or upgrade your plan.",
        [77] = "CloakBrowser Pro: license key is invalid, expired, or missing. Check CLOAKBROWSER_LICENSE_KEY.",
        [78] = "CloakBrowser Pro: couldn't verify your license (license server unreachable or a connection problem).",
        [79] = "CloakBrowser Pro: local configuration problem, ~/.cloakbrowser is not writable.",
    };

    // Playwright embeds the child-process exit as "<process did exit: exitCode=N, ...>".
    // Anchor to that record so an unrelated "exitCode=" elsewhere can't false-match.
    private static readonly Regex ExitCodeRegex = new(@"process did exit:\s*exitCode=(\d+)", RegexOptions.Compiled);

    /// <summary>
    /// Maps a launch-failure message to a license reason, or null. Returns the human
    /// message when the browser process exited with a known license exit code, else
    /// null so a genuine crash propagates unchanged.
    /// </summary>
    public static string? LicenseErrorMessage(string? errorText)
    {
        if (string.IsNullOrEmpty(errorText)) return null;
        var match = ExitCodeRegex.Match(errorText);
        if (!match.Success) return null;
        // TryParse, not Parse: a non-license crash can carry a huge exit code
        // (e.g. Windows SEH status 3221225477) that would overflow int and, since
        // this runs inside the launch catch block, mask the original error.
        if (!int.TryParse(match.Groups[1].Value, out var code)) return null;
        return LicenseExitMessages.TryGetValue(code, out var msg) ? msg : null;
    }

    /// <summary>
    /// Returns a <see cref="CloakBrowserLicenseError"/> if a launch failure was a
    /// license deny, else null so the original exception propagates unchanged.
    /// </summary>
    public static CloakBrowserLicenseError? LicenseErrorFrom(Exception ex)
    {
        var msg = LicenseErrorMessage(ex.Message);
        return msg is not null ? new CloakBrowserLicenseError(msg, ex) : null;
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

    /// <summary>Overrides the live seat-count lookup for tests. Null -> real HTTP.</summary>
    internal static Func<string, int?>? ActiveSessionCountOverride;

    /// <summary>
    /// Resolves the user home directory used to detect the default
    /// <c>~/.cloakbrowser</c> cache path. A test seam mirroring the Python
    /// <c>Path.home</c> / JS <c>os.homedir</c> mocks. Null -> real UserProfile.
    /// </summary>
    internal static Func<string>? HomeDirOverride;

    // -----------------------------------------------------------------------

    // -----------------------------------------------------------------------
    // Key source tracking — determines whether env injection is needed.
    // (The binary reads the default file path directly, so env injection
    //  is only required for explicit params or custom cache-dir files.)
    // -----------------------------------------------------------------------

    /// <summary>Resolve license key with source tracking for env-injection decisions.</summary>
    internal static (string? Key, LicenseKeySource Source) ResolveLicenseKeyWithSource(
        string? licenseKey = null)
    {
        // 1. Explicit param
        var trimmed = licenseKey?.Trim();
        if (!string.IsNullOrEmpty(trimmed))
            return (trimmed, LicenseKeySource.Param);

        // 2. Environment variable
        var envKey = (Environment.GetEnvironmentVariable("CLOAKBROWSER_LICENSE_KEY") ?? "").Trim();
        if (!string.IsNullOrEmpty(envKey))
            return (envKey, LicenseKeySource.Env);

        // 3. File in the wrapper cache dir
        try
        {
            var cacheDir = Config.GetCacheDir();
            var keyFile = Path.Combine(cacheDir, "license.key");
            var content = File.ReadAllText(keyFile).Trim();
            if (!string.IsNullOrEmpty(content))
            {
                var homeDir = HomeDirOverride?.Invoke()
                    ?? Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
                var defaultCache = Path.Combine(homeDir, ".cloakbrowser");
                var source = string.Equals(
                    Path.GetFullPath(cacheDir),
                    Path.GetFullPath(defaultCache),
                    StringComparison.OrdinalIgnoreCase)
                    ? LicenseKeySource.DefaultFile
                    : LicenseKeySource.CustomFile;
                return (content, source);
            }
        }
        catch (IOException) { /* file missing/unreadable */ }
        catch (UnauthorizedAccessException) { }

        return (null, LicenseKeySource.None);
    }

    /// <summary>Resolve the license key: explicit param &gt; env var &gt; file &gt; null.</summary>
    public static string? ResolveLicenseKey(string? licenseKey = null)
    {
        return ResolveLicenseKeyWithSource(licenseKey).Key;
    }

    /// <summary>
    /// Build a child-process env dict with any needed license key injection.
    ///
    /// The Pro binary reads <c>CLOAKBROWSER_LICENSE_KEY</c> from its own process
    /// environment at startup.  This helper merges the resolved key into the
    /// child process env dict <b>only</b> when injection is necessary:
    ///
    /// <list type="bullet">
    ///   <item><description><c>Param</c> / <c>CustomFile</c> — inject into child env.</description></item>
    ///   <item><description><c>Env</c> — child inherits from parent (no injection).</description></item>
    ///   <item><description><c>DefaultFile</c> — binary reads the file directly (no injection), unless a custom userEnv is passed (Playwright replaces the child env and can drop HOME) — then inject.</description></item>
    /// </list>
    ///
    /// When <paramref name="userEnv"/> is provided it is used as the base
    /// (Playwright replaces the child env entirely when <c>env</c> is set),
    /// with the key injected only when needed.
    ///
    /// Returns <c>null</c> when no injection is needed and no custom userEnv
    /// was given — Playwright treats <c>env=null</c> as "inherit parent env".
    /// </summary>
    public static Dictionary<string, string>? BuildLaunchEnv(
        string? licenseKey = null,
        Dictionary<string, string>? userEnv = null)
    {
        var (key, source) = ResolveLicenseKeyWithSource(licenseKey);

        // Default file: binary reads it directly — no env injection needed,
        // UNLESS the caller passes a custom env. Playwright replaces (not
        // merges) the child env, which can drop HOME and hide the file from
        // the binary, so inject the key too then (fall through to the merge).
        if (source == LicenseKeySource.DefaultFile && userEnv == null)
            return null;

        // No key at all: pass through user env or null.
        if (source == LicenseKeySource.None || key == null)
            return userEnv;

        // Env source, no custom user env: child inherits parent env, which
        // already has CLOAKBROWSER_LICENSE_KEY.
        if (source == LicenseKeySource.Env && userEnv == null)
            return null;

        // Build the merged env dict.
        var merged = userEnv != null
            ? new Dictionary<string, string>(userEnv)
            : Environment.GetEnvironmentVariables()
                .Cast<System.Collections.DictionaryEntry>()
                .ToDictionary(e => (string)e.Key, e => (string)e.Value!);

        // For Param/CustomFile this is THE injection into the child env.
        // For Env source with a custom userEnv this ensures the key persists
        // through the user's env override (Playwright replaces, not merges).
        merged["CLOAKBROWSER_LICENSE_KEY"] = key;

        return merged;
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

        var marker = Path.Combine(Config.GetCacheDir(), $".last_pro_version_check_{Config.GetPlatformTag()}");

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
            using var req = new HttpRequestMessage(HttpMethod.Get, ProVersionUrl);
            req.Headers.Add("X-Platform", Config.GetPlatformTag());
            using var resp = Http.SendAsync(req).GetAwaiter().GetResult();
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

    /// <summary>
    /// How many concurrent sessions (seats) this license is holding right now.
    /// </summary>
    /// <remarks>
    /// Deliberately NOT cached: a cached seat count is a wrong seat count. Returns
    /// null when the number is unknown — the server couldn't be reached, or it
    /// reported the count as unavailable (it does that instead of a false 0 while
    /// running in leaseless mode). Callers render null as "unavailable".
    /// </remarks>
    public static int? GetActiveSessionCount(string licenseKey)
    {
        if (ActiveSessionCountOverride != null)
            return ActiveSessionCountOverride(licenseKey);

        try
        {
            var body = new StringContent(
                JsonSerializer.Serialize(new Dictionary<string, string> { ["license_key"] = licenseKey }),
                Encoding.UTF8, "application/json");
            using var resp = Http.PostAsync(SessionCountUrl, body).GetAwaiter().GetResult();
            resp.EnsureSuccessStatusCode();
            var json = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            using var doc = JsonDocument.Parse(json);
            return doc.RootElement.TryGetProperty("active", out var a) && a.ValueKind == JsonValueKind.Number
                ? a.GetInt32() : null;
        }
        catch (Exception ex)
        {
            CloakLog.Debug("Session count lookup failed: {0}", ex.Message);
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
