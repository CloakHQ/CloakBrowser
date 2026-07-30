using System.Diagnostics;
using System.Runtime.InteropServices;

namespace CloakBrowser;

/// <summary>
/// Environment + binary diagnostics gathering for the `info` / `doctor` CLI.
/// Returns a plain dictionary so the CLI can render it as text or JSON without
/// the two output paths drifting apart. Never triggers a binary download.
/// </summary>
internal static class Diagnostics
{
    /// <summary>
    /// Best-effort IANA name for the host/container timezone.
    /// </summary>
    /// <remarks>
    /// This is the zone the browser would report if GeoIP resolved nothing, so it
    /// is the thing worth comparing against - a UTC container behind a foreign
    /// exit IP is the failure this check exists to surface.
    /// </remarks>
    private static string? SystemTimezone()
    {
        try
        {
            // TimeZoneInfo.Local.Id is the IANA name on Unix and a Windows id on
            // Windows; on .NET 6+ the Windows id converts to IANA.
            var local = TimeZoneInfo.Local;
            if (TimeZoneInfo.TryConvertWindowsIdToIanaId(local.Id, out string? iana))
                return iana;
            return local.Id;
        }
        catch (Exception ex) when (ex is TimeZoneNotFoundException or InvalidTimeZoneException)
        {
            return null;
        }
    }

    /// <summary>Current UTC offset of <paramref name="zone"/>, or null if unresolvable.</summary>
    private static TimeSpan? UtcOffset(string zone)
    {
        try
        {
            return TimeZoneInfo.FindSystemTimeZoneById(zone).GetUtcOffset(DateTimeOffset.UtcNow);
        }
        catch (Exception ex) when (ex is TimeZoneNotFoundException or InvalidTimeZoneException)
        {
            return null;
        }
    }

    /// <summary>
    /// Whether the browser's clock would contradict the exit IP.
    /// </summary>
    /// <remarks>
    /// Compared by current UTC offset rather than by name: IANA aliases
    /// (Europe/Kiev vs Europe/Kyiv) would otherwise report a mismatch that no
    /// detector would ever see.
    /// </remarks>
    internal static bool TimezonesDisagree(string resolved, string? system)
    {
        if (string.IsNullOrEmpty(system) || resolved == system) return false;
        var a = UtcOffset(resolved);
        var b = UtcOffset(system!);
        if (a is null || b is null) return false;
        return a != b;
    }

    /// <summary>
    /// Resolve GeoIP for real and report what a launch would actually apply.
    /// </summary>
    /// <remarks>
    /// Presence of the database says nothing about whether resolution works: the
    /// egress IP can be unreachable, the lookup can miss, and both paths leave the
    /// browser on the container clock while the launch continues. So resolve.
    /// Never throws - a diagnostic that dies on the condition it diagnoses is
    /// worse than useless.
    /// </remarks>
    private static async Task<Dictionary<string, object?>> CheckGeoIpAsync(string? proxy)
    {
        string dbPath = Path.Combine(Config.GetCacheDir(), "geoip", "GeoLite2-City.mmdb");
        var result = new Dictionary<string, object?>
        {
            ["db_present"] = File.Exists(dbPath),
            ["path"] = dbPath,
            ["checked"] = true,
            ["via_proxy"] = !string.IsNullOrEmpty(proxy),
            ["system_timezone"] = SystemTimezone(),
            ["exit_ip"] = null,
            ["timezone"] = null,
            ["locale"] = null,
            ["mismatch"] = false,
            ["error"] = null,
        };

        // Report the switch rather than resolving past it: if the user turned
        // GeoIP off, "it resolves fine" would be a true statement about something
        // launches are not going to do.
        if (GeoIp.DisabledByEnv())
        {
            result["checked"] = false;
            result["reason"] = "disabled by CLOAKBROWSER_GEOIP";
            return result;
        }

        try
        {
            // force: the user explicitly asked to verify, so a recent-failure
            // cooldown marker must not make the report claim GeoIP is unavailable.
            if (await GeoIp.EnsureGeoIpDbAsync(CancellationToken.None, force: true).ConfigureAwait(false) is null)
                result["error"] = "GeoIP database unavailable (download failed)";
            result["db_present"] = File.Exists(dbPath);

            // A CLI-supplied proxy may omit the scheme ("host:port"), which the
            // HTTP client rejects outright.
            string? proxyUrl = string.IsNullOrEmpty(proxy)
                ? null
                : ProxyResolver.EnsureProxyScheme(proxy!);
            var (tz, locale, exitIp) = await GeoIp
                .ResolveProxyGeoWithIpAsync(proxyUrl)
                .ConfigureAwait(false);
            result["exit_ip"] = exitIp;
            result["timezone"] = tz;
            result["locale"] = locale;

            if (exitIp is null)
                result["error"] ??= "could not resolve the egress IP";
            else if (tz is null && result["error"] is null)
                result["error"] = $"no timezone for {exitIp} in the database";
            if (tz is not null)
                result["mismatch"] = TimezonesDisagree(tz, (string?)result["system_timezone"]);
        }
        catch (Exception ex)
        {
            result["error"] = $"{ex.GetType().Name}: {ex.Message}";
        }

        return result;
    }

    internal static async Task<Dictionary<string, object?>> CollectAsync(bool quick, string? proxy = null)
    {
        var diag = new Dictionary<string, object?>();

        var env = new Dictionary<string, object?>
        {
            ["wrapper"] = CloakVersion.Version,
            ["dotnet"] = RuntimeInformation.FrameworkDescription,
            ["os"] = RuntimeInformation.OSDescription,
            ["arch"] = RuntimeInformation.OSArchitecture.ToString(),
        };
        diag["environment"] = env;

        // Resolve the license up front — it decides which binary actually
        // launches (EnsureBinary only uses the Pro binary when a key validates).
        var (license, entitledPro) = ResolveLicense();

        // Live seat count — a Pro-only extra lookup, so gated exactly like the
        // server latest-version check: --quick keeps `info` network-free, and a
        // free tier holds no seats. Never cached (a cached count is a wrong count).
        if (entitledPro && !quick)
        {
            string? sessionKey = License.ResolveLicenseKey();
            if (!string.IsNullOrEmpty(sessionKey))
            {
                license["sessions"] = new Dictionary<string, object?>
                {
                    ["active"] = License.GetActiveSessionCount(sessionKey!),
                };
            }
        }

        try { env["platform_tag"] = Config.GetPlatformTag(); }
        catch (Exception ex) { env["platform_tag"] = $"unavailable ({ex.Message})"; }

        Dictionary<string, object?> binary;
        try { binary = EffectiveBinary(entitledPro, quick); }
        catch (Exception ex) { binary = new Dictionary<string, object?> { ["error"] = ex.Message }; }
        diag["binary"] = binary;

        // Launch test (skipped by --quick or when the binary is not installed).
        string? binPath = binary.TryGetValue("path", out var p) ? p as string : null;
        bool installed = binary.TryGetValue("installed", out var i) && i is true;
        if (quick)
        {
            diag["launch"] = new Dictionary<string, object?> { ["tested"] = false, ["reason"] = "skipped (--quick)" };
        }
        else if (string.IsNullOrEmpty(binPath) || !(installed || File.Exists(binPath)))
        {
            diag["launch"] = new Dictionary<string, object?> { ["tested"] = false, ["reason"] = "binary not installed" };
        }
        else
        {
            var (ok, version, error) = BinaryVersion(binPath!);
            var launch = new Dictionary<string, object?>
            {
                ["tested"] = true,
                ["ok"] = ok,
                ["version"] = version,
                ["error"] = error,
            };
            if (!ok) launch["missing_libs"] = MissingSharedLibs(binPath!);
            diag["launch"] = launch;
        }

        // Windows-font probe — only meaningful on a Linux host spoofing Windows.
        // Omitted entirely off Linux, where it carries no signal.
        if (RuntimeInformation.IsOSPlatform(OSPlatform.Linux))
        {
            // Strict count, not "any one present" — real font installs are atomic
            // (you have the whole pack or none), so report how complete the set is.
            int? winN = CloakLauncher.CountFontsPresent(CloakLauncher.WindowsFontTells);
            int? officeN = CloakLauncher.CountFontsPresent(CloakLauncher.OfficeFontTells);
            diag["fonts"] = new Dictionary<string, object?>
            {
                ["windows"] = winN is null ? null : new[] { winN.Value, CloakLauncher.WindowsFontTells.Length },
                ["office"] = officeN is null ? null : new[] { officeN.Value, CloakLauncher.OfficeFontTells.Length },
            };
        }

        diag["license"] = license;

        // GeoIP - resolved for real, because presence of the database says nothing
        // about whether resolution works. Under --quick, presence only (a ~70 MB
        // first-use download is not something a "quick" flag should trigger).
        if (quick)
        {
            string dbPath = Path.Combine(Config.GetCacheDir(), "geoip", "GeoLite2-City.mmdb");
            diag["geoip"] = new Dictionary<string, object?>
            {
                ["db_present"] = File.Exists(dbPath),
                ["path"] = dbPath,
                ["checked"] = false,
                ["reason"] = "skipped (--quick)",
            };
        }
        else
        {
            diag["geoip"] = await CheckGeoIpAsync(proxy).ConfigureAwait(false);
        }

        // Dependency assemblies — mirrors the Python/JS modules section. These are
        // hard NuGet references, so "missing" here means a broken deployment.
        diag["modules"] = new Dictionary<string, object?>
        {
            ["playwright"] = ModuleAvailable("Microsoft.Playwright"),
            ["geoip2"] = ModuleAvailable("MaxMind.GeoIP2"),
        };

        return diag;
    }

    // Resolve + validate the license the way EnsureBinary does.
    private static (Dictionary<string, object?> license, bool entitledPro) ResolveLicense()
    {
        string? key = License.ResolveLicenseKey();
        // EnsureBinary disables Pro routing when a custom download URL is set, so the
        // diagnostic must report free too (matches Download.cs).
        if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("CLOAKBROWSER_DOWNLOAD_URL")))
            key = null;
        if (string.IsNullOrEmpty(key))
            return (new Dictionary<string, object?> { ["tier"] = "free" }, false);
        try
        {
            LicenseInfo? lic = License.ValidateLicense(key!);
            if (lic is null)
                return (new Dictionary<string, object?> { ["tier"] = "unknown", ["error"] = "could not validate" }, false);
            if (lic.Valid)
                return (new Dictionary<string, object?> { ["tier"] = lic.Plan, ["valid"] = true, ["expires"] = lic.Expires }, true);
            return (new Dictionary<string, object?> { ["tier"] = "invalid", ["valid"] = false }, false);
        }
        catch (Exception ex)
        {
            return (new Dictionary<string, object?> { ["tier"] = "unknown", ["error"] = ex.Message }, false);
        }
    }

    private static bool ModuleAvailable(string assemblyName)
    {
        try { System.Reflection.Assembly.Load(assemblyName); return true; }
        catch { return false; }
    }

    // Describe the binary EnsureBinary would actually launch (no download).
    // Unlike Download.BinaryInfo(), a Pro binary on disk is only reported when
    // the license entitles Pro — so a keyless run shows the free binary.
    private static Dictionary<string, object?> EffectiveBinary(bool entitledPro, bool quick = false)
    {
        string? over = Config.GetLocalBinaryOverride();
        if (!string.IsNullOrEmpty(over))
        {
            return new Dictionary<string, object?>
            {
                ["version"] = null,
                ["latest_version"] = null,
                ["pinned"] = false,
                ["tier"] = "override",
                ["bundled_version"] = Config.ChromiumVersion,
                ["path"] = over,
                ["installed"] = File.Exists(over),
                ["cache_dir"] = null,
                ["override"] = over,
            };
        }
        string? requested = Config.NormalizeRequestedVersion();
        string requestedChannel = Config.NormalizeReleaseChannel();

        // For a Pro license, surface the server's latest separately from the version
        // that will actually launch, so `info` can never silently diverge from launch
        // (the divergence a customer hit: info showed latest, launch ran a stale cache).
        // --quick skips the optional lookups (server latest version, seat count,
        // GeoIP resolution). It is not fully network-free: the license itself is
        // still validated, behind a 24h cache.
        ProReleaseInfo? latestRelease = (entitledPro && !quick)
            ? License.GetProLatestRelease(requestedChannel)
            : null;
        string? latestVersion = latestRelease?.Version;

        string? version;
        string? installedVersion = null;
        if (!string.IsNullOrEmpty(requested))
            version = requested!;
        else if (entitledPro)
        {
            // Mirror EnsureBinary: report what the next launch resolves to, while
            // CLOAKBROWSER_AUTO_UPDATE=false retains an installed channel build.
            installedVersion = Config.GetEffectiveVersion(true, requestedChannel);
            var autoUpdate = (Environment.GetEnvironmentVariable("CLOAKBROWSER_AUTO_UPDATE") ?? "true").ToLowerInvariant();
            bool updatesEnabled = autoUpdate != "false";
            if (installedVersion != null && !updatesEnabled)
                version = installedVersion;
            else if (latestVersion != null && (installedVersion == null || Config.VersionNewer(latestVersion, installedVersion)))
                version = latestVersion;
            else
                version = installedVersion ?? latestVersion;
        }
        else
        {
            version = Config.GetEffectiveVersion(false);
            installedVersion = version;
        }
        string? path = version != null ? Config.GetBinaryPath(version, entitledPro) : null;
        return new Dictionary<string, object?>
        {
            ["version"] = version,
            ["latest_version"] = latestVersion,
            ["requested_channel"] = requestedChannel,
            ["resolved_channel"] = latestRelease?.ResolvedChannel,
            ["channel_fallback"] = latestRelease?.Fallback ?? false,
            ["installed_version"] = installedVersion,
            ["pinned"] = !string.IsNullOrEmpty(requested),
            ["tier"] = entitledPro ? "pro" : "free",
            ["bundled_version"] = Config.ChromiumVersion,
            ["path"] = path,
            ["installed"] = path != null && File.Exists(path),
            ["cache_dir"] = version != null ? Config.GetBinaryDir(version, entitledPro) : null,
            ["override"] = null,
        };
    }

    // Launch `<binary> --version` to prove it runs.
    //
    // Chromium only handles --version on POSIX, so on Windows the switch is ignored
    // and a browser starts instead of printing — the probe then times out and a
    // healthy install looks broken. --no-startup-window makes it exit right away
    // without putting a window on screen; a broken binary still exits non-zero, so
    // the check keeps its meaning. It just reports no version there, as nothing is
    // printed.
    private static (bool ok, string version, string error) BinaryVersion(string binaryPath)
    {
        try
        {
            var startInfo = new ProcessStartInfo
            {
                FileName = binaryPath,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
            };
            startInfo.ArgumentList.Add("--version");
            if (RuntimeInformation.IsOSPlatform(OSPlatform.Windows))
                startInfo.ArgumentList.Add("--no-startup-window");
            using var proc = new Process { StartInfo = startInfo };
            proc.Start();
            // Read both pipes asynchronously so a full pipe buffer can't deadlock
            // the parent, and so WaitForExit's timeout is the real wall-clock bound.
            var stdoutTask = proc.StandardOutput.ReadToEndAsync();
            var stderrTask = proc.StandardError.ReadToEndAsync();
            if (!proc.WaitForExit(10000))
            {
                try { proc.Kill(true); } catch { /* best-effort */ }
                return (false, "", "timed out");
            }
            proc.WaitForExit(); // flush async readers now that the process has exited
            string stdout = stdoutTask.GetAwaiter().GetResult();
            string stderr = stderrTask.GetAwaiter().GetResult();
            if (proc.ExitCode != 0)
                return (false, "", (string.IsNullOrWhiteSpace(stderr) ? stdout : stderr).Trim());
            return (true, stdout.Trim(), "");
        }
        catch (Exception ex)
        {
            return (false, "", ex.Message);
        }
    }

    // Linux-only: ldd the binary and return missing .so names.
    private static List<string> MissingSharedLibs(string binaryPath)
    {
        var missing = new List<string>();
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.Linux)) return missing;
        try
        {
            // ArgumentList passes the path as a single argv entry, so a path
            // containing spaces is not split into multiple ldd arguments.
            var psi = new ProcessStartInfo
            {
                FileName = "ldd",
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                UseShellExecute = false,
            };
            psi.ArgumentList.Add("--"); // so a path starting with - isn't read as a flag
            psi.ArgumentList.Add(binaryPath);
            using var proc = new Process { StartInfo = psi };
            proc.Start();
            var stdoutTask = proc.StandardOutput.ReadToEndAsync();
            if (!proc.WaitForExit(10000))
            {
                try { proc.Kill(true); } catch { /* best-effort */ }
                return missing;
            }
            proc.WaitForExit();
            string stdout = stdoutTask.GetAwaiter().GetResult();
            foreach (var line in stdout.Split('\n'))
                if (line.Contains("=> not found"))
                    missing.Add(line.Split("=>")[0].Trim());
        }
        catch { /* best-effort */ }
        return missing;
    }
}
