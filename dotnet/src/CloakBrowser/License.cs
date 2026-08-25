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
/// Result of a seat lookup: the count, the cap it counts against, and the reason
/// either is missing. Mirrors the Python <c>SessionSeats</c> dataclass / JS
/// <c>SessionSeats</c> interface.
/// </summary>
/// <remarks>
/// <see cref="State"/> is one of:
/// <list type="bullet">
/// <item><c>"ok"</c> — Active is a real number (0 is a real answer, not an error)</item>
/// <item><c>"unreachable"</c> — never got an answer: DNS, refused, timeout, TLS</item>
/// <item><c>"denied"</c> — the server refused; <see cref="Reason"/> carries its error code</item>
/// <item><c>"unknown"</c> — the server is up and the key is fine, but it cannot count
/// right now (leaseless mode, or its seat store is unreachable)</item>
/// </list>
/// <see cref="Limit"/> is null whenever the server declined to state a cap: unlimited,
/// an unrecognised plan, or a server too old to send the field. Callers must fall back
/// to the bare count, never invent a denominator.
/// </remarks>
public sealed record SessionSeats
{
    public int? Active { get; init; }
    public int? Limit { get; init; }
    public string State { get; init; } = "ok";
    public string? Reason { get; init; }
}

/// <summary>Server-resolved Pro release for the requested channel and platform.</summary>
public sealed record ProReleaseInfo(
    string Version, string RequestedChannel, string ResolvedChannel, bool Fallback);

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

    /// <summary>
    /// Env var the wrapper uses to tell the Pro binary where to record a license
    /// denial. A denial that resolves AFTER the CDP handshake (e.g. an over-cap
    /// seat) kills the browser once the driver already holds a live connection,
    /// so the exit code never reaches the wrapper as a launch failure. The binary
    /// writes the code to this path just before exiting; the wrapper reads it when
    /// the user's next call fails. Old binaries ignore the unknown var.
    /// </summary>
    public const string LicenseStatusFileEnv = "CLOAKBROWSER_LICENSE_STATUS_FILE";

    /// <summary>
    /// Maps a raw license exit code (76-79) to a <see cref="CloakBrowserLicenseError"/>,
    /// or null for any code that is not a known license denial (so a genuine crash
    /// is never mislabelled). Companion to <see cref="LicenseErrorMessage"/> for the
    /// post-handshake file path where we hold the integer directly.
    /// </summary>
    public static CloakBrowserLicenseError? LicenseErrorForCode(int code)
    {
        return LicenseExitMessages.TryGetValue(code, out var msg)
            ? new CloakBrowserLicenseError(msg)
            : null;
    }

    /// <summary>
    /// Reads and consumes a denial file written by the binary, returning its code.
    /// The file holds a single JSON integer (the exit code). Reading is destructive:
    /// the file is deleted afterwards so a later launch can't see a stale code. Any
    /// problem — absent, unreadable, or not a valid int — yields null.
    /// </summary>
    // Once a denial has been observed for a per-launch path, remember it. The
    // read is destructive, so a concurrent second guarded call for the same
    // launch would otherwise find the file gone and miss the denial. Paths are
    // unique per launch; ConcurrentDictionary since Tasks may run on the pool.
    private static readonly System.Collections.Concurrent.ConcurrentDictionary<string, int> ObservedDenials = new();

    public static int? ReadDenialFile(string filePath)
    {
        if (ObservedDenials.TryGetValue(filePath, out var cached)) return cached;
        // Fast path: the guard calls this after EVERY browser call to catch a
        // denial that lands while calls still succeed, so the no-denial case
        // (file absent) must be cheap — a single stat, not a read+throw per call.
        if (!File.Exists(filePath)) return null;
        int? code = null;
        try
        {
            var raw = File.ReadAllText(filePath);
            // Parse as tolerantly as Python (int(json.load)) and JS
            // (Number(JSON.parse)): accept a bare JSON number AND a quoted or
            // whitespace-padded value, so all three wrappers read an identical
            // denial file the same way.
            using var doc = JsonDocument.Parse(raw);
            var el = doc.RootElement;
            code = el.ValueKind switch
            {
                JsonValueKind.Number => el.GetInt32(),
                JsonValueKind.String => int.Parse(
                    el.GetString()!, System.Globalization.CultureInfo.InvariantCulture),
                _ => throw new FormatException("denial file is not a number"),
            };
        }
        catch
        {
            code = null;
        }
        try { File.Delete(filePath); } catch { /* best-effort cleanup */ }
        if (code.HasValue)
        {
            ObservedDenials[filePath] = code.Value;
            return code;
        }
        // File gone/garbage: a concurrent reader may have already recorded it.
        return ObservedDenials.TryGetValue(filePath, out var c2) ? c2 : (int?)null;
    }

    /// <summary>
    /// Returns a fresh, unique path for the binary to write a denial code to. Only
    /// computes the path (and ensures the parent dir exists) — the file is created
    /// by the binary, and only on a denial, so a granted launch leaves nothing
    /// behind. Returns null if the directory can't be created; the caller then skips
    /// the feature (the fix must never break a launch).
    /// </summary>
    public static string? MintDenialFile()
    {
        try
        {
            var home = HomeDirOverride?.Invoke()
                ?? Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
            var denialDir = Path.Combine(home, ".cloakbrowser", "denials");
            Directory.CreateDirectory(denialDir);
            SweepStaleDenials(denialDir);
            return Path.Combine(denialDir, $"{Guid.NewGuid():N}.json");
        }
        catch
        {
            return null;
        }
    }

    // A denial file is orphaned when the binary writes one but the user never
    // calls a guarded method afterwards. It is only consumed on a guarded call,
    // so sweep leftovers older than this at mint time — long enough that a live
    // in-flight denial from a concurrent launch is never deleted before its
    // owner reads it.
    private static readonly TimeSpan DenialFileTtl = TimeSpan.FromHours(1);

    private static void SweepStaleDenials(string denialDir)
    {
        try
        {
            var cutoff = DateTime.UtcNow - DenialFileTtl;
            foreach (var f in Directory.EnumerateFiles(denialDir, "*.json"))
            {
                try
                {
                    if (File.GetLastWriteTimeUtc(f) < cutoff) File.Delete(f);
                }
                catch { /* best-effort */ }
            }
        }
        catch { /* best-effort */ }
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

    /// <summary>Overrides resolved Pro release metadata for tests. Null -> normal resolution.</summary>
    internal static Func<ProReleaseInfo?>? ProLatestReleaseOverride;

    /// <summary>Overrides the live seat-count lookup for tests. Null -> real HTTP.</summary>
    internal static Func<string, int?>? ActiveSessionCountOverride;

    /// <summary>Overrides the full seat lookup (count + cap + state) for tests. Null -> real HTTP.</summary>
    internal static Func<string, SessionSeats>? SessionSeatsOverride;

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
        Dictionary<string, string>? userEnv = null,
        string? statusFile = null)
    {
        var result = BuildKeyEnv(licenseKey, userEnv);

        // Add the denial-status file path last so it rides along even on the
        // inherit-parent-env (null) paths, which then have to become a full
        // parent-env copy (Playwright replaces, not merges). Only set when the
        // caller asked for it, which it only does when a license key is in play.
        if (statusFile != null)
        {
            result ??= Environment.GetEnvironmentVariables()
                .Cast<System.Collections.DictionaryEntry>()
                .ToDictionary(e => (string)e.Key, e => (string)e.Value!);
            result[LicenseStatusFileEnv] = statusFile;
        }

        return result;
    }

    /// <summary>The license-key half of BuildLaunchEnv (unchanged behavior).</summary>
    private static Dictionary<string, string>? BuildKeyEnv(
        string? licenseKey,
        Dictionary<string, string>? userEnv)
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

    /// <summary>Get the server-resolved Pro release and channel for this platform.</summary>
    public static ProReleaseInfo? GetProLatestRelease(string? releaseChannel = null)
    {
        var channel = Config.NormalizeReleaseChannel(releaseChannel);
        if (ProLatestReleaseOverride != null)
            return ProLatestReleaseOverride();
        if (ProLatestVersionOverride != null)
        {
            var overridden = ProLatestVersionOverride();
            return string.IsNullOrEmpty(overridden)
                ? null
                : new ProReleaseInfo(overridden, channel, channel, false);
        }

        var markerSuffix = channel == "preview"
            ? $"preview_{Config.GetPlatformTag()}"
            : Config.GetPlatformTag();
        var marker = Path.Combine(Config.GetCacheDir(), $".last_pro_version_check_{markerSuffix}");
        var resolutionMarker = Path.Combine(
            Config.GetCacheDir(), $".last_pro_version_resolution_{markerSuffix}");

        if (File.Exists(marker) && File.Exists(resolutionMarker))
        {
            try
            {
                var age = (DateTime.UtcNow - File.GetLastWriteTimeUtc(marker)).TotalSeconds;
                if (age < ProVersionCheckInterval)
                {
                    var version = File.ReadAllText(marker).Trim();
                    using var cachedDoc = JsonDocument.Parse(File.ReadAllText(resolutionMarker));
                    var root = cachedDoc.RootElement;
                    var cachedVersion = root.GetProperty("version").GetString();
                    if (!string.IsNullOrEmpty(version) && cachedVersion == version)
                    {
                        var requested = root.TryGetProperty("requested_channel", out var requestedSnake)
                            ? requestedSnake.GetString()
                            : root.TryGetProperty("requestedChannel", out var requestedCamel)
                                ? requestedCamel.GetString()
                                : channel;
                        var resolved = root.TryGetProperty("resolved_channel", out var resolvedSnake)
                            ? resolvedSnake.GetString()
                            : root.TryGetProperty("resolvedChannel", out var resolvedCamel)
                                ? resolvedCamel.GetString()
                                : "stable";
                        requested ??= channel;
                        resolved ??= "stable";
                        var didFallback = root.TryGetProperty("fallback", out var fallback)
                            ? fallback.GetBoolean()
                            : requested != resolved;
                        return new ProReleaseInfo(version, requested, resolved, didFallback);
                    }
                }
            }
            catch (IOException) { /* unreadable - proceed with fetch */ }
            catch (JsonException) { /* invalid - proceed with fetch */ }
            catch (KeyNotFoundException) { /* malformed sidecar - proceed with fetch */ }
            catch (InvalidOperationException) { /* wrong JSON value kind - proceed with fetch */ }
        }

        try
        {
            var versionUrl = channel == "preview"
                ? $"{ProVersionUrl}?channel=preview"
                : ProVersionUrl;
            using var req = new HttpRequestMessage(HttpMethod.Get, versionUrl);
            req.Headers.Add("X-Platform", Config.GetPlatformTag());
            using var resp = Http.SendAsync(req).GetAwaiter().GetResult();
            resp.EnsureSuccessStatusCode();
            var json = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            var version = root.TryGetProperty("version", out var ve) && ve.ValueKind == JsonValueKind.String
                ? ve.GetString() : null;
            if (string.IsNullOrEmpty(version)) return null;

            var requested = root.TryGetProperty("requested_channel", out var requestedElement)
                ? requestedElement.GetString() ?? channel : channel;
            var resolved = root.TryGetProperty("resolved_channel", out var resolvedElement)
                ? resolvedElement.GetString() ?? "stable" : "stable";
            var didFallback = root.TryGetProperty("fallback", out var fallbackElement)
                ? fallbackElement.ValueKind == JsonValueKind.True
                : requested != resolved;
            var release = new ProReleaseInfo(version, requested, resolved, didFallback);

            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(marker)!);
                var resolutionTmp = resolutionMarker + ".tmp";
                File.WriteAllText(resolutionTmp, JsonSerializer.Serialize(new
                {
                    version = release.Version,
                    requested_channel = release.RequestedChannel,
                    resolved_channel = release.ResolvedChannel,
                    fallback = release.Fallback,
                }));
                File.Move(resolutionTmp, resolutionMarker, true);
                var tmp = marker + ".tmp";
                File.WriteAllText(tmp, version);
                File.Move(tmp, marker, true);
            }
            catch (IOException) { /* non-fatal */ }

            return release;
        }
        catch (Exception ex)
        {
            CloakLog.Debug("Pro version check failed: {0}", ex.Message);
            try
            {
                var version = File.ReadAllText(marker).Trim();
                if (string.IsNullOrEmpty(version))
                    return null;
                // Prefer the last successful fetch's channel metadata (the resolution
                // sidecar) so an offline preview build is not mislabeled as a stable
                // fallback. Older wrappers left only the version marker, so its channel
                // is unknowable — hardcode a conservative stable fallback then.
                if (File.Exists(resolutionMarker))
                {
                    try
                    {
                        using var cachedDoc = JsonDocument.Parse(File.ReadAllText(resolutionMarker));
                        var root = cachedDoc.RootElement;
                        var cachedVersion = root.TryGetProperty("version", out var ve)
                            ? ve.GetString() : null;
                        if (cachedVersion == version)
                        {
                            var requested = root.TryGetProperty("requested_channel", out var rq)
                                ? rq.GetString()
                                : root.TryGetProperty("requestedChannel", out var rqc)
                                    ? rqc.GetString() : channel;
                            var resolved = root.TryGetProperty("resolved_channel", out var rs)
                                ? rs.GetString()
                                : root.TryGetProperty("resolvedChannel", out var rsc)
                                    ? rsc.GetString() : "stable";
                            requested ??= channel;
                            resolved ??= "stable";
                            var didFallback = root.TryGetProperty("fallback", out var fb)
                                    && (fb.ValueKind == JsonValueKind.True || fb.ValueKind == JsonValueKind.False)
                                ? fb.GetBoolean()
                                : requested != resolved;
                            return new ProReleaseInfo(version, requested, resolved, didFallback);
                        }
                    }
                    catch (IOException) { /* unreadable - use conservative default */ }
                    catch (JsonException) { /* malformed - use conservative default */ }
                    catch (InvalidOperationException) { /* wrong value kind - use default */ }
                }
                return new ProReleaseInfo(version, channel, "stable", channel == "preview");
            }
            catch (IOException)
            {
                return null;
            }
        }
    }

    /// <summary>Get only the version from the server-resolved Pro release.</summary>
    public static string? GetProLatestVersion(string? releaseChannel = null) =>
        GetProLatestRelease(releaseChannel)?.Version;

    /// <summary>
    /// Seats held right now, the cap they count against, and why either is missing.
    /// </summary>
    /// <remarks>
    /// Deliberately NOT cached: a cached seat count is a wrong seat count.
    /// <para>
    /// Six different things can stop us answering — no route to the host, a timeout,
    /// a 403 for a dead key, a 429, the server reporting the count as unknown in
    /// leaseless mode, and its seat store being unreachable. They used to collapse
    /// into one bare null, so <c>info</c> printed the same "unavailable" for "your
    /// key is dead" and "our backend is degraded, you are fine". <see
    /// cref="SessionSeats.State"/> keeps them apart.
    /// </para>
    /// </remarks>
    public static SessionSeats GetSessionSeats(string licenseKey)
    {
        if (SessionSeatsOverride != null)
            return SessionSeatsOverride(licenseKey);
        if (ActiveSessionCountOverride != null)
        {
            // Older tests (and any external caller) seam in only the number.
            var only = ActiveSessionCountOverride(licenseKey);
            return only is null
                ? new SessionSeats { State = "unknown" }
                : new SessionSeats { Active = only, State = "ok" };
        }

        HttpResponseMessage resp;
        try
        {
            var body = new StringContent(
                JsonSerializer.Serialize(new Dictionary<string, string> { ["license_key"] = licenseKey }),
                Encoding.UTF8, "application/json");
            resp = Http.PostAsync(SessionCountUrl, body).GetAwaiter().GetResult();
        }
        catch (Exception ex)
        {
            // Never reached the server: DNS, refused, timed out, TLS.
            CloakLog.Debug("Session count lookup unreachable: {0}", ex.Message);
            return new SessionSeats { State = "unreachable" };
        }

        using (resp)
        {
            string json;
            try
            {
                json = resp.Content.ReadAsStringAsync().GetAwaiter().GetResult();
            }
            catch (Exception ex)
            {
                CloakLog.Debug("Session count body unreadable: {0}", ex.Message);
                return new SessionSeats { State = resp.IsSuccessStatusCode ? "unknown" : "denied",
                                          Reason = resp.IsSuccessStatusCode ? null : $"HTTP {(int)resp.StatusCode}" };
            }

            if (!resp.IsSuccessStatusCode)
            {
                // The server answered, and the answer was a refusal. Its `error` field is
                // the actionable part (invalid_key / license_inactive / rate_limited);
                // fall back to the status when the body is missing or not JSON.
                string? reason = null;
                try
                {
                    using var errDoc = JsonDocument.Parse(json);
                    if (errDoc.RootElement.TryGetProperty("error", out var e) && e.ValueKind == JsonValueKind.String)
                        reason = e.GetString();
                }
                catch (JsonException)
                {
                    // fall through to the status
                }
                reason ??= $"HTTP {(int)resp.StatusCode}";
                CloakLog.Debug("Session count denied: {0}", reason);
                return new SessionSeats { State = "denied", Reason = reason };
            }

            JsonDocument doc;
            try
            {
                doc = JsonDocument.Parse(json);
            }
            catch (JsonException ex)
            {
                CloakLog.Debug("Session count body unparseable: {0}", ex.Message);
                return new SessionSeats { State = "unknown" };
            }

            using (doc)
            {
                if (!doc.RootElement.TryGetProperty("active", out var a) || a.ValueKind != JsonValueKind.Number)
                {
                    // 200 with active=null is the server saying "up, your key is fine, but
                    // I genuinely cannot count right now" — deliberate, so it never
                    // reports a false 0.
                    return new SessionSeats { State = "unknown" };
                }

                // limit absent (older server) or null (unlimited / unknown plan): callers
                // fall back to the bare count rather than printing a made-up denominator.
                int? limit = doc.RootElement.TryGetProperty("limit", out var l) && l.ValueKind == JsonValueKind.Number
                    ? l.GetInt32() : null;
                return new SessionSeats { Active = a.GetInt32(), Limit = limit, State = "ok" };
            }
        }
    }

    /// <summary>
    /// How many concurrent sessions (seats) this license is holding right now.
    /// </summary>
    /// <remarks>
    /// Kept for callers outside <c>info</c> that only want the number. Prefer
    /// <see cref="GetSessionSeats"/>, which also carries the cap and the reason a
    /// lookup failed.
    /// </remarks>
    public static int? GetActiveSessionCount(string licenseKey) =>
        // Straight through GetSessionSeats, which honours both override seams itself.
        // Re-checking ActiveSessionCountOverride here would give the two methods
        // different precedence if a test ever set both, and disagree about the count.
        GetSessionSeats(licenseKey).Active;

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
