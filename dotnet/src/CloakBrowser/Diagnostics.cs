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
    internal static Dictionary<string, object?> Collect(bool quick)
    {
        var diag = new Dictionary<string, object?>();

        var env = new Dictionary<string, object?>
        {
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

        // GeoIP DB — presence only, never downloads.
        string dbPath = Path.Combine(Config.GetCacheDir(), "geoip", "GeoLite2-City.mmdb");
        diag["geoip"] = new Dictionary<string, object?> { ["db_present"] = File.Exists(dbPath), ["path"] = dbPath };

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

        // For a Pro license, surface the server's latest separately from the version
        // that will actually launch, so `info` can never silently diverge from launch
        // (the divergence a customer hit: info showed latest, launch ran a stale cache).
        // --quick keeps `info` fully network-free (skip the server latest lookup).
        string? latestVersion = (entitledPro && !quick) ? License.GetProLatestVersion() : null;

        string? version;
        if (!string.IsNullOrEmpty(requested))
            version = requested!;
        else if (entitledPro)
            // "Will launch now" is the cached Pro build; if none is cached, the next
            // launch downloads latestVersion. GetEffectiveVersion(true) returns null
            // (never the free base) when nothing is cached.
            version = Config.GetEffectiveVersion(true) ?? latestVersion;
        else
            version = Config.GetEffectiveVersion(false);
        string? path = version != null ? Config.GetBinaryPath(version, entitledPro) : null;
        return new Dictionary<string, object?>
        {
            ["version"] = version,
            ["latest_version"] = latestVersion,
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
    private static (bool ok, string version, string error) BinaryVersion(string binaryPath)
    {
        try
        {
            using var proc = new Process
            {
                StartInfo = new ProcessStartInfo
                {
                    FileName = binaryPath,
                    Arguments = "--version",
                    RedirectStandardOutput = true,
                    RedirectStandardError = true,
                    UseShellExecute = false,
                },
            };
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
