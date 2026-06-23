using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;

namespace CloakBrowser;

/// <summary>
/// Widevine CDM hint-file seeding for persistent contexts.
/// CloakBrowser's binary is built with Widevine support but ships no CDM (the CDM
/// is a proprietary Google binary we can't redistribute). Users sideload it by
/// copying a <c>WidevineCdm/</c> directory from a real Chrome install next to the binary.
///
/// This module pre-seeds the hint file before launch so a sideloaded CDM works on
/// the very first launch. It never bundles, downloads, or copies the CDM itself -
/// it only writes the hint when a CDM the user provided is already present.
///
/// Linux only: Chromium's hint-file mechanism is Linux/ChromeOS-specific.
/// Direct port of Python <c>cloakbrowser/widevine.py</c>.
/// </summary>
public static class Widevine
{
    // Chromium reads this file from <user-data-dir>/WidevineCdm/ at early startup.
    private const string HintFilename = "latest-component-updated-widevine-cdm";

    private static bool SeedingDisabled()
    {
        var val = (Environment.GetEnvironmentVariable("CLOAKBROWSER_WIDEVINE") ?? "").Trim().ToLowerInvariant();
        return val is "0" or "false" or "off" or "no";
    }

    /// <summary>
    /// Locate a sideloaded Widevine CDM directory, or null if absent.
    /// If <c>CLOAKBROWSER_WIDEVINE_CDM</c> is set, it is used exclusively (overrides
    /// auto-detection). Otherwise <c>&lt;dir of the chrome binary&gt;/WidevineCdm</c>.
    /// A directory counts only if it contains <c>manifest.json</c>.
    /// </summary>
    public static string? ResolveWidevineCdmDir(string binaryPath)
    {
        var custom = Environment.GetEnvironmentVariable("CLOAKBROWSER_WIDEVINE_CDM");
        // "is not null" (not truthiness): a present-but-empty env var is "set" and
        // used exclusively - it resolves to an invalid path and skips seeding.
        string cdmDir;
        if (custom != null)
        {
            // A present-but-empty/whitespace value is "set" and used exclusively,
            // but is not a usable path: treat it as invalid so we skip seeding
            // (Path.Combine("", "manifest.json") would otherwise probe the CWD,
            // diverging from the Python/JS wrappers' bogus-path => null behaviour).
            if (string.IsNullOrWhiteSpace(custom))
                return null;
            cdmDir = custom;
        }
        else
        {
            cdmDir = Path.Combine(Path.GetDirectoryName(Path.GetFullPath(binaryPath)) ?? ".", "WidevineCdm");
        }

        if (File.Exists(Path.Combine(cdmDir, "manifest.json")))
            return Path.GetFullPath(cdmDir);
        return null;
    }

    /// <summary>
    /// Write the Widevine CDM hint file into a persistent profile before launch.
    /// No-op on non-Linux platforms, when seeding is disabled via CLOAKBROWSER_WIDEVINE,
    /// or when no sideloaded CDM is present. Never throws.
    /// </summary>
    public static void SeedWidevineHint(string? userDataDir, string binaryPath)
    {
        if (!RuntimeInformation.IsOSPlatform(OSPlatform.Linux))
            return;
        if (SeedingDisabled())
        {
            CloakLog.Debug("Widevine hint seeding disabled via CLOAKBROWSER_WIDEVINE");
            return;
        }
        if (string.IsNullOrEmpty(userDataDir))
        {
            // Empty user_data_dir = Playwright's ephemeral profile (its own temp dir).
            return;
        }

        try
        {
            var cdmDir = ResolveWidevineCdmDir(binaryPath);
            if (cdmDir == null)
            {
                if (Environment.GetEnvironmentVariable("CLOAKBROWSER_WIDEVINE_CDM") != null)
                    CloakLog.Warning(
                        "CLOAKBROWSER_WIDEVINE_CDM is set but has no manifest.json; " +
                        "skipping Widevine hint seeding");
                else
                    CloakLog.Debug("No sideloaded Widevine CDM found; skipping hint seeding");
                return;
            }

            var hintDir = Path.Combine(userDataDir, "WidevineCdm");
            Directory.CreateDirectory(hintDir);
            var hintFile = Path.Combine(hintDir, HintFilename);

            // Compact separators byte-match the JS wrapper's JSON.stringify (UTF-8) output.
            var content = JsonSerializer.Serialize(
                new Dictionary<string, string> { ["Path"] = cdmDir },
                new JsonSerializerOptions { Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping });

            try
            {
                if (File.Exists(hintFile) && File.ReadAllText(hintFile, Encoding.UTF8) == content)
                    return; // already seeded correctly
            }
            catch (Exception)
            {
                CloakLog.Warning("Existing Widevine hint unreadable; rewriting");
            }

            File.WriteAllText(hintFile, content, new UTF8Encoding(encoderShouldEmitUTF8Identifier: false));
            CloakLog.Info("Seeded Widevine CDM hint -> {0}", cdmDir);
        }
        catch (Exception e)
        {
            CloakLog.Warning("Failed to seed Widevine CDM hint file: {0}", e.Message);
        }
    }
}
