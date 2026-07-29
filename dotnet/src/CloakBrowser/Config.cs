using System.Runtime.InteropServices;
using System.Text.RegularExpressions;

namespace CloakBrowser;

/// <summary>
/// Stealth configuration and platform detection for CloakBrowser.
/// Direct port of Python <c>cloakbrowser/config.py</c>.
/// </summary>
public static class Config
{
    // -----------------------------------------------------------------------
    // Chromium version shipped with this release.
    // Different platforms may ship different versions during transition periods.
    // ChromiumVersion is the latest across all platforms (for display/reference).
    // Use GetChromiumVersion() for the current platform's actual version.
    // -----------------------------------------------------------------------
    public const string ChromiumVersion = "146.0.7680.177.5";

    public static readonly IReadOnlyDictionary<string, string> PlatformChromiumVersions =
        new Dictionary<string, string>
        {
            ["linux-x64"] = "146.0.7680.177.5",
            ["linux-arm64"] = "146.0.7680.177.3",
            ["darwin-arm64"] = "145.0.7632.109.2",
            ["darwin-x64"] = "145.0.7632.109.2",
            ["windows-x64"] = "146.0.7680.177.5",
        };

    // -----------------------------------------------------------------------
    // Ed25519 public keys for verifying downloaded binaries.
    //
    // Each release publishes SHA256SUMS and a detached signature SHA256SUMS.sig.
    // The wrapper verifies that signature against the keys below before trusting
    // any hash in the manifest, so the download origin alone cannot certify a
    // tampered binary. Values are base64 of the 32-byte raw public key. Multiple
    // entries are accepted to allow key rotation.
    // -----------------------------------------------------------------------
    public static readonly IReadOnlyList<string> BinarySigningPubkeys = new[]
    {
        "MKFKwIhUcKWq5xTuNA0Ovg99njcDEcEJvmWYYhApvaU=",
    };

    // -----------------------------------------------------------------------
    // Playwright default args to suppress - these leak automation signals.
    // --enable-automation: exposes navigator.webdriver = true
    // --enable-unsafe-swiftshader: forces software WebGL rendering via SwiftShader,
    //   producing a distinctive renderer string that no real user browser has.
    // -----------------------------------------------------------------------
    public static readonly string[] IgnoreDefaultArgs =
        { "--enable-automation", "--enable-unsafe-swiftshader" };

    // -----------------------------------------------------------------------
    // Default viewport - used for HEADLESS only (headed launches use no_viewport
    // so the page tracks the real window). Headless has no window chrome, so a
    // fixed viewport stays coherent (outer == inner) and gives deterministic
    // dimensions. Models a maximized Chrome on 1080p Windows: screen=1920x1080,
    // innerHeight=947 (minus ~85px Chrome UI: tabs + address bar + bookmarks).
    // -----------------------------------------------------------------------
    public const int DefaultViewportWidth = 1920;
    public const int DefaultViewportHeight = 947;

    private static readonly Random _rng = new();

    /// <summary>
    /// Build stealth args with a random fingerprint seed per launch.
    /// On macOS, skips platform/GPU spoofing - runs as a native Mac browser.
    /// Spoofing Windows on Mac creates detectable mismatches (fonts, GPU, etc.).
    /// </summary>
    public static List<string> GetDefaultStealthArgs()
    {
        int seed;
        lock (_rng) { seed = _rng.Next(10000, 100000); }

        var baseArgs = new List<string>
        {
            "--no-sandbox",
            $"--fingerprint={seed}",
        };

        if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
        {
            // Tell the fingerprint patches we're on macOS so GPU/UA match natively.
            baseArgs.Add("--fingerprint-platform=macos");
            return baseArgs;
        }

        // Linux/Windows: Windows fingerprint profile.
        // Screen and window size come from the real display, not this flag (verified:
        // identical across seeds), so the wrapper must not emulate a viewport on top in
        // headed mode - that would break outerWidth >= innerWidth coherence.
        baseArgs.Add("--fingerprint-platform=windows");
        return baseArgs;
    }

    // -----------------------------------------------------------------------
    // Platform detection
    // -----------------------------------------------------------------------

    /// <summary>Platforms with pre-built binaries available for download.</summary>
    public static IReadOnlySet<string> AvailablePlatforms =>
        new HashSet<string>(PlatformChromiumVersions.Keys);

    /// <summary>Return the Chromium version for the current platform.</summary>
    public static string GetChromiumVersion()
    {
        var tag = GetPlatformTag();
        return PlatformChromiumVersions.TryGetValue(tag, out var v) ? v : ChromiumVersion;
    }

    // -----------------------------------------------------------------------
    // Version pinning
    // -----------------------------------------------------------------------

    private static readonly Regex VersionPinRe = new(
        @"^[0-9]+(?:\.[0-9]+){3,4}$",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);

    /// <summary>Return the requested release channel, defaulting to Stable.</summary>
    public static string NormalizeReleaseChannel(string? releaseChannel = null)
    {
        var raw = releaseChannel
            ?? Environment.GetEnvironmentVariable("CLOAKBROWSER_RELEASE_CHANNEL")
            ?? "stable";
        return string.Equals(raw.Trim(), "preview", StringComparison.OrdinalIgnoreCase)
            ? "preview"
            : "stable";
    }

    /// <summary>
    /// Return an explicit Chromium version pin from arg/env, or null.
    ///
    /// The explicit argument wins over <c>CLOAKBROWSER_VERSION</c>. Only numeric dotted
    /// versions are accepted because the value is interpolated into cache paths
    /// and download URLs. Port of Python <c>normalize_requested_version()</c>.
    /// </summary>
    public static string? NormalizeRequestedVersion(string? version = null)
    {
        var raw = version ?? Environment.GetEnvironmentVariable("CLOAKBROWSER_VERSION");
        if (raw == null)
            return null;
        var normalized = raw.Trim();
        if (normalized.Length == 0)
            return null;
        if (!VersionPinRe.IsMatch(normalized))
            throw new ArgumentException(
                "Invalid browser version pin. Use a full numeric Chromium version, " +
                "e.g. '148.0.7778.215.2'.");
        return normalized;
    }

    /// <summary>
    /// Return the platform tag for binary download (e.g. <c>linux-x64</c>, <c>darwin-arm64</c>).
    /// </summary>
    public static string GetPlatformTag()
    {
        var arch = RuntimeInformation.OSArchitecture;

        if (RuntimeInformation.IsOSPlatform(OSPlatform.Linux))
        {
            return arch switch
            {
                Architecture.X64 => "linux-x64",
                Architecture.Arm64 => "linux-arm64",
                _ => throw Unsupported("Linux", arch),
            };
        }

        if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
        {
            return arch switch
            {
                Architecture.Arm64 => "darwin-arm64",
                Architecture.X64 => "darwin-x64",
                _ => throw Unsupported("Darwin", arch),
            };
        }

        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
        {
            return arch switch
            {
                Architecture.X64 => "windows-x64",
                _ => throw Unsupported("Windows", arch),
            };
        }

        throw new PlatformNotSupportedException(
            $"Unsupported platform: {RuntimeInformation.OSDescription} {arch}");
    }

    private static PlatformNotSupportedException Unsupported(string system, Architecture arch) =>
        new($"Unsupported platform: {system} {arch}. " +
            "Supported: linux-x64, linux-arm64, darwin-arm64, darwin-x64, windows-x64");

    // -----------------------------------------------------------------------
    // Binary cache paths
    // -----------------------------------------------------------------------

    /// <summary>
    /// Return the cache directory for downloaded binaries.
    /// Override with the <c>CLOAKBROWSER_CACHE_DIR</c> env var. Default: <c>~/.cloakbrowser/</c>.
    /// </summary>
    public static string GetCacheDir()
    {
        var custom = Environment.GetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR");
        if (!string.IsNullOrEmpty(custom))
            return custom;
        var home = Environment.GetFolderPath(Environment.SpecialFolder.UserProfile);
        return Path.Combine(home, ".cloakbrowser");
    }

    /// <summary>Return the directory for a Chromium version binary.</summary>
    /// <param name="version">Version string, or null for the platform default.</param>
    /// <param name="pro">When true, use the Pro-specific cache dir (<c>chromium-{v}-pro</c>).</param>
    public static string GetBinaryDir(string? version = null, bool pro = false)
    {
        var v = version ?? GetChromiumVersion();
        var suffix = pro ? "-pro" : "";
        return Path.Combine(GetCacheDir(), $"chromium-{v}{suffix}");
    }

    /// <summary>Return the expected path to the chrome executable.</summary>
    public static string GetBinaryPath(string? version = null, bool pro = false)
    {
        var binaryDir = GetBinaryDir(version, pro);

        if (RuntimeInformation.IsOSPlatform(OSPlatform.OSX))
            return Path.Combine(binaryDir, "Chromium.app", "Contents", "MacOS", "Chromium");
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
            return Path.Combine(binaryDir, "chrome.exe");
        return Path.Combine(binaryDir, "chrome");
    }

    /// <summary>
    /// Raise a clear error if no pre-built binary exists for this platform.
    /// Skipped when <c>CLOAKBROWSER_BINARY_PATH</c> is set (user has their own build).
    /// </summary>
    public static void CheckPlatformAvailable()
    {
        if (GetLocalBinaryOverride() != null)
            return;

        var tag = GetPlatformTag(); // throws if platform unsupported entirely
        if (!AvailablePlatforms.Contains(tag))
        {
            var available = string.Join(", ", AvailablePlatforms.OrderBy(x => x));
            throw new PlatformNotSupportedException(
                $"\nCloakBrowser - Pre-built binaries are currently only available for: {available}.\n\n" +
                "To use CloakBrowser now, set CLOAKBROWSER_BINARY_PATH to a local Chromium binary.");
        }
    }

    /// <summary>
    /// Return the best available version: auto-updated if available, else platform default.
    /// Reads a platform-scoped marker file from the cache directory.
    /// When <paramref name="pro"/> is true, reads from the Pro-specific marker and returns
    /// <c>null</c> when no cached Pro binary matches it. A valid Pro license must NEVER fall
    /// back to the free binary, so there is deliberately no free-version fallback for Pro —
    /// callers treat <c>null</c> as "resolve the latest Pro version from the server".
    /// </summary>
    public static string? GetEffectiveVersion(bool pro = false, string? releaseChannel = null)
    {
        var baseVersion = GetChromiumVersion();
        var cache = GetCacheDir();

        if (pro)
        {
            var markerPrefix = NormalizeReleaseChannel(releaseChannel) == "preview"
                ? "latest_pro_version_preview"
                : "latest_pro_version";
            var proMarker = Path.Combine(cache, $"{markerPrefix}_{GetPlatformTag()}");
            if (File.Exists(proMarker))
            {
                try
                {
                    var version = File.ReadAllText(proMarker).Trim();
                    // Match launch's ProBinaryReady (exists AND executable) so `info`
                    // never reports a build that launch would reject.
                    if (!string.IsNullOrEmpty(version) && IsExecutableFile(GetBinaryPath(version, pro: true)))
                        return version;
                }
                catch (Exception ex) when (ex is FormatException or IOException) { }
            }
            return null;
        }

        foreach (var name in new[] { $"latest_version_{GetPlatformTag()}", "latest_version" })
        {
            var marker = Path.Combine(cache, name);
            if (File.Exists(marker))
            {
                try
                {
                    var version = File.ReadAllText(marker).Trim();
                    if (!string.IsNullOrEmpty(version) && VersionNewer(version, baseVersion))
                    {
                        var binary = GetBinaryPath(version);
                        if (File.Exists(binary))
                            return version;
                    }
                }
                catch (Exception ex) when (ex is FormatException or IOException) { }
            }
        }
        return baseVersion;
    }

    /// <summary>True when a binary exists and is executable. Canonical check shared with Download.</summary>
    internal static bool IsExecutableFile(string path)
    {
        if (!File.Exists(path)) return false;
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows)) return true;
        var mode = File.GetUnixFileMode(path);
        return (mode & (UnixFileMode.UserExecute | UnixFileMode.GroupExecute | UnixFileMode.OtherExecute)) != 0;
    }

    /// <summary>Parse "145.0.7718.0" into (145, 0, 7718, 0) for comparison.</summary>
    public static int[] VersionTuple(string v) =>
        v.Split('.').Select(int.Parse).ToArray();

    /// <summary>Return true if version a is strictly newer than version b.</summary>
    public static bool VersionNewer(string a, string b)
    {
        var ta = VersionTuple(a);
        var tb = VersionTuple(b);
        int len = Math.Max(ta.Length, tb.Length);
        for (int i = 0; i < len; i++)
        {
            int va = i < ta.Length ? ta[i] : 0;
            int vb = i < tb.Length ? tb[i] : 0;
            if (va != vb) return va > vb;
        }
        return false;
    }

    // -----------------------------------------------------------------------
    // Download URL
    // -----------------------------------------------------------------------

    public static string DownloadBaseUrl =>
        Environment.GetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL") ?? "https://cloakbrowser.dev";

    public const string GitHubApiUrl = "https://api.github.com/repos/CloakHQ/cloakbrowser/releases";

    public const string GitHubDownloadBaseUrl =
        "https://github.com/CloakHQ/cloakbrowser/releases/download";

    /// <summary>Return the archive extension for the current platform (.zip for Windows, .tar.gz otherwise).</summary>
    public static string GetArchiveExt() =>
        RuntimeInformation.IsOSPlatform(OSPlatform.Windows) ? ".zip" : ".tar.gz";

    /// <summary>Return the archive filename for a platform tag (e.g. 'cloakbrowser-linux-x64.tar.gz').</summary>
    public static string GetArchiveName(string? tag = null)
    {
        var t = tag ?? GetPlatformTag();
        return $"cloakbrowser-{t}{GetArchiveExt()}";
    }

    /// <summary>Return the full download URL for the current platform's binary archive.</summary>
    public static string GetDownloadUrl(string? version = null)
    {
        var v = version ?? GetChromiumVersion();
        return $"{DownloadBaseUrl}/chromium-v{v}/{GetArchiveName()}";
    }

    /// <summary>Return the GitHub Releases fallback URL for the binary archive.</summary>
    public static string GetFallbackDownloadUrl(string? version = null)
    {
        var v = version ?? GetChromiumVersion();
        return $"{GitHubDownloadBaseUrl}/chromium-v{v}/{GetArchiveName()}";
    }

    // -----------------------------------------------------------------------
    // CloakBrowser Pro download URLs (cloakbrowser.dev, license-key authed)
    // -----------------------------------------------------------------------

    /// <summary>
    /// Return the Pro binary download URL for an explicit version. The version is
    /// requested explicitly so the served archive matches the signed Pro manifest.
    /// </summary>
    public static string GetProDownloadUrl(string version) =>
        $"{DownloadBaseUrl}/api/download/{version}";

    /// <summary>Return the base URL for the Pro signed manifest (SHA256SUMS + .sig) of a version.</summary>
    public static string GetProManifestBaseUrl(string version) =>
        $"{DownloadBaseUrl}/releases/pro/chromium-v{version}";

    /// <summary>Return the "latest Pro" display download URL (shown by binary_info for Pro installs).</summary>
    public static string GetProLatestDownloadUrl(string? releaseChannel = null) =>
        NormalizeReleaseChannel(releaseChannel) == "preview"
            ? $"{DownloadBaseUrl}/api/download/latest?channel=preview"
            : $"{DownloadBaseUrl}/api/download/latest";

    // -----------------------------------------------------------------------
    // Local binary override (skip download, use your own build)
    // -----------------------------------------------------------------------

    /// <summary>
    /// Check if the user has set a local binary path via the <c>CLOAKBROWSER_BINARY_PATH</c> env var.
    /// </summary>
    public static string? GetLocalBinaryOverride() =>
        Environment.GetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH");

    // First Chromium build that reports coherent headless dimensions without an
    // emulated viewport. On these binaries the wrapper launches headless with no
    // viewport; older binaries need a fixed default viewport to stay coherent.
    // null => not shipped yet; feature off, behavior byte-identical to today.
    // TODO: set to the chromium version string that first ships it.
    public static readonly string? HeadlessNoViewportMinVersion = "148.0.7778.215.4";

    /// <summary>
    /// Whether headless can launch without an emulated viewport on the resolved binary.
    /// Only binaries at or above <see cref="HeadlessNoViewportMinVersion"/> qualify; older
    /// ones keep the fixed default viewport. A local override binary
    /// (<c>CLOAKBROWSER_BINARY_PATH</c>) is unknown-version, so stay on the safe path.
    /// </summary>
    public static bool BinarySupportsHeadlessNoViewport(
        string? licenseKey = null, string? browserVersion = null, string? releaseChannel = null)
    {
        if (HeadlessNoViewportMinVersion == null)
            return false;
        // A declared version (browserVersion arg OR CLOAKBROWSER_VERSION env) wins even
        // under a local override — the caller asserts the version (also how internal builds
        // opt in). Only an override with no declared version stays on the safe path.
        string? declared;
        try
        {
            declared = NormalizeRequestedVersion(browserVersion);
        }
        catch
        {
            declared = null;
        }
        string? version;
        if (!string.IsNullOrEmpty(declared))
        {
            version = declared!;
        }
        else if (GetLocalBinaryOverride() != null)
        {
            return false;
        }
        else
        {
            bool pro = !string.IsNullOrEmpty(License.ResolveLicenseKey(licenseKey));
            version = GetEffectiveVersion(pro, releaseChannel);
        }
        // No cached Pro build resolvable (GetEffectiveVersion returned null) → fail safe.
        if (version == null) return false;
        try
        {
            return !VersionNewer(HeadlessNoViewportMinVersion, version);
        }
        catch
        {
            return false;
        }
    }

    // First build whose --fingerprint-webrtc-ip accepts a second address for the
    // other address family. Below this floor the flag takes a single address only,
    // so the wrapper MUST pass one, as it always has.
    public static readonly string? WebrtcDualStackMinVersion = "150.0.7871.114.5";

    /// <summary>
    /// Whether the resolved binary understands a two-address WebRTC exit IP.
    /// Same resolution rules as <see cref="BinarySupportsHeadlessNoViewport"/>: a
    /// declared version wins, an unknown-version local override stays on the safe
    /// (IPv4-only) path. Python, JS and .NET mirror this gate.
    /// </summary>
    public static bool BinarySupportsDualStackWebrtc(
        string? licenseKey = null, string? browserVersion = null, string? releaseChannel = null)
    {
        if (WebrtcDualStackMinVersion == null)
            return false;
        string? declared;
        try
        {
            declared = NormalizeRequestedVersion(browserVersion);
        }
        catch
        {
            declared = null;
        }
        string? version;
        if (!string.IsNullOrEmpty(declared))
        {
            version = declared!;
        }
        else if (GetLocalBinaryOverride() != null)
        {
            return false;
        }
        else
        {
            bool pro = !string.IsNullOrEmpty(License.ResolveLicenseKey(licenseKey));
            version = GetEffectiveVersion(pro, releaseChannel);
        }
        if (version == null) return false;
        try
        {
            return !VersionNewer(WebrtcDualStackMinVersion, version);
        }
        catch
        {
            return false;
        }
    }

    /// <summary>
    /// Whether the wrapper may auto-add <c>--start-maximized</c>. Gated on the same
    /// threshold as the no_viewport shim: only binaries whose headless surface-fix +
    /// headed screen-clamp make a maximized window coherent (<c>outer == screen</c>).
    /// Below it, maximizing headless while the CDP viewport stays at 1280x720 yields
    /// <c>outerWidth &lt; innerWidth</c> — a bot tell — so the flag must NOT be added.
    /// Shares <see cref="HeadlessNoViewportMinVersion"/>; own name so the two can
    /// diverge later. Python, JS and .NET mirror this gate.
    /// </summary>
    public static bool BinarySupportsMaximizedWindow(
        string? licenseKey = null, string? browserVersion = null, string? releaseChannel = null)
        => BinarySupportsHeadlessNoViewport(licenseKey, browserVersion, releaseChannel);

    // First Chromium build, per platform, whose binary can take inline HTTP proxy
    // credentials (Chromium-native --proxy-server=http://user:pass@host). Below the
    // floor the wrapper MUST route credentialed HTTP/HTTPS proxies through
    // Playwright's proxy object — an older binary treats the user:pass@ authority as
    // an invalid proxy host and drops proxy auth (#182). A single global threshold
    // can't model this: the capability landed in different build lineages at different
    // points (linux-x64/windows-x64 at 146.0.7680.177.5, but the free macOS 145.x and
    // linux-arm64 146.0.7680.177.3 floors predate it, qualifying only once they resolve
    // to a Pro/newer 148+ build). Platforms absent from this map are never-inline.
    public static readonly IReadOnlyDictionary<string, string> HttpProxyInlineAuthMinVersion =
        new Dictionary<string, string>
        {
            ["linux-x64"] = "146.0.7680.177.5",
            ["windows-x64"] = "146.0.7680.177.5",
            ["linux-arm64"] = "148.0.7778.215.3",
            ["darwin-arm64"] = "148.0.7778.215.3",
            ["darwin-x64"] = "148.0.7778.215.3",
        };

    /// <summary>
    /// Whether the resolved binary accepts inline HTTP proxy credentials. The
    /// capability is a function of the binary version; <paramref name="licenseKey"/>
    /// only resolves which version launches (Pro build vs free default), exactly like
    /// <see cref="BinarySupportsHeadlessNoViewport"/>. A declared pin wins, else a valid
    /// Pro license resolves to the Pro build (which ships the patch), else the free
    /// per-platform default — then it compares to this platform's floor. Below the
    /// floor, credentialed HTTP proxies fall back to Playwright's proxy object. A local
    /// override with no declared version is unknown-version, so stay on the safe
    /// fallback. Python, JS and .NET mirror this gate.
    /// </summary>
    public static bool BinarySupportsHttpProxyInlineAuth(
        string? licenseKey = null, string? browserVersion = null, string? releaseChannel = null)
    {
        string tag;
        try
        {
            tag = GetPlatformTag();
        }
        catch
        {
            return false;
        }
        if (!HttpProxyInlineAuthMinVersion.TryGetValue(tag, out var floor))
            return false;
        string? declared;
        try
        {
            declared = NormalizeRequestedVersion(browserVersion);
        }
        catch
        {
            declared = null;
        }
        string? version;
        if (!string.IsNullOrEmpty(declared))
        {
            version = declared!;
        }
        else if (GetLocalBinaryOverride() != null)
        {
            return false;
        }
        else
        {
            bool pro = !string.IsNullOrEmpty(License.ResolveLicenseKey(licenseKey));
            version = GetEffectiveVersion(pro, releaseChannel);
        }
        if (version == null) return false;
        try
        {
            return !VersionNewer(floor, version);
        }
        catch
        {
            return false;
        }
    }
}
