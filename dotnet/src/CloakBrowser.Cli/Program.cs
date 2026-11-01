using System.Text.Json;
using CloakBrowser;

// CLI for cloakbrowser - download and manage the stealth Chromium binary.
// Direct port of Python cloakbrowser/__main__.py.
//
// Usage:
//   cloakbrowser login        # Save a license key (or get a free key by email)
//   cloakbrowser logout       # Remove the saved license key
//   cloakbrowser install      # Download binary (with progress)
//   cloakbrowser info         # Environment + binary diagnostics (--quick, --json)
//   cloakbrowser doctor       # Alias for info
//   cloakbrowser update       # Check for and download newer binary
//   cloakbrowser clear-cache  # Remove cached binaries

const string UpgradeHint = "For more than one concurrent session → https://cloakbrowser.dev";
const string NoKeyHint = "Get a free key → run 'cloakbrowser login'";

// Route CloakBrowser logs to stderr at Info level (clean output).
CloakLog.MinLevel = CloakLogLevel.Info;

string? command = args.Length > 0 ? args[0] : null;
string[] rest = args.Length > 1 ? args[1..] : Array.Empty<string>();

if (string.IsNullOrEmpty(command) || command is "-h" or "--help" or "help")
{
    PrintHelp();
    return string.IsNullOrEmpty(command) ? 2 : 0;
}

try
{
    switch (command)
    {
        case "install":
            await CmdInstall();
            break;
        case "info":
        case "doctor":
            CmdInfo(rest);
            break;
        case "update":
            return await CmdUpdate();
        case "clear-cache":
            CmdClearCache();
            break;
        case "login":
            return CmdLogin(rest);
        case "logout":
            return CmdLogout();
        default:
            Console.Error.WriteLine($"Unknown command: {command}");
            PrintHelp();
            return 2;
    }
}
catch (OperationCanceledException)
{
    return 130;
}
catch (Exception e)
{
    Console.Error.WriteLine($"Error: {e.Message}");
    return 1;
}

return 0;

static async Task CmdInstall()
{
    string path = await Download.EnsureBinaryAsync().ConfigureAwait(false);
    Console.WriteLine(path);
}

static void CmdInfo(string[] flags)
{
    bool quick = flags.Contains("--quick") || flags.Contains("--no-launch");
    bool asJson = flags.Contains("--json");
    string? proxy = GetFlagValue(flags, "--proxy");

    var diag = Diagnostics.Collect(quick, proxy);

    if (asJson)
    {
        Console.WriteLine(JsonSerializer.Serialize(diag, new JsonSerializerOptions { WriteIndented = true }));
    }
    else
    {
        PrintDiagnostics(diag);
    }
}

static string? GetFlagValue(string[] flags, string name)
{
    string prefix = name + "=";
    foreach (var f in flags)
        if (f.StartsWith(prefix, StringComparison.Ordinal))
            return f[prefix.Length..];
    int i = Array.IndexOf(flags, name);
    return i != -1 && i + 1 < flags.Length ? flags[i + 1] : null;
}

static void PrintDiagnostics(Dictionary<string, object?> diag)
{
    var env = (Dictionary<string, object?>)diag["environment"]!;
    Console.WriteLine("CloakBrowser diagnostics");
    Console.WriteLine($"Wrapper:   {env["wrapper"]}");
    Console.WriteLine($".NET:      {env["dotnet"]}");
    Console.WriteLine($"OS:        {env["os"]} {env["arch"]}");
    Console.WriteLine($"Platform:  {env.GetValueOrDefault("platform_tag") ?? "unknown"}");

    var binary = (Dictionary<string, object?>)diag["binary"]!;
    if (binary.ContainsKey("error"))
    {
        Console.WriteLine($"Binary:    unavailable ({binary["error"]})");
    }
    else
    {
        if ((string)binary["tier"]! == "override")
            Console.WriteLine("Version:   set via CLOAKBROWSER_BINARY_PATH (see Launch line)");
        else
        {
            if (binary.TryGetValue("channel_fallback", out var fallback) && fallback is true)
                Console.WriteLine("Channel:   Preview → Stable fallback");
            else
            {
                var channel = binary.GetValueOrDefault("resolved_channel") as string
                    ?? binary.GetValueOrDefault("requested_channel") as string
                    ?? "stable";
                Console.WriteLine($"Channel:   {TitleCase(channel)}");
            }
            if (binary.TryGetValue("latest_version", out var lv) && lv is string latest && !string.IsNullOrEmpty(latest))
            {
                // Pro: show what launches now AND the server's latest, so the two can't diverge.
                Console.WriteLine($"Version:   {binary["version"]} ({binary["tier"]}) — next launch");
                if (latest == binary["version"] as string && binary["installed"] is true)
                    Console.WriteLine($"Latest:    {latest} (up to date)");
                else if (latest == binary["version"] as string)
                    Console.WriteLine($"Latest:    {latest} (downloads on next launch)");
                else if (binary.TryGetValue("pinned", out var p) && p is true)
                    Console.WriteLine($"Latest:    {latest} (available — pinned; unset CLOAKBROWSER_VERSION to upgrade)");
                else
                    Console.WriteLine($"Latest:    {latest} (server-resolved; installed build retained)");
                if (binary.GetValueOrDefault("installed_version") is string installedVersion
                    && installedVersion != binary["version"] as string)
                    Console.WriteLine($"Installed: {installedVersion}");
            }
            else if (binary["version"] is null)
                // Pro with no cached build and no server answer (e.g. offline).
                Console.WriteLine($"Version:   not downloaded yet ({binary["tier"]}) — next launch downloads the latest");
            else
                Console.WriteLine($"Version:   {binary["version"]} ({binary["tier"]})");
        }
        Console.WriteLine($"Binary:    {binary["path"]}");
        Console.WriteLine($"Installed: {binary["installed"]}");
        if (binary["cache_dir"] is string cd && !string.IsNullOrEmpty(cd))
            Console.WriteLine($"Cache:     {cd}");
        if (binary["override"] is string ov && !string.IsNullOrEmpty(ov))
            Console.WriteLine($"Override:  {ov} (CLOAKBROWSER_BINARY_PATH)");
    }

    var launch = (Dictionary<string, object?>)diag["launch"]!;
    if (launch["tested"] is not true)
    {
        Console.WriteLine($"Launch:    {launch["reason"]}");
    }
    else if (launch["ok"] is true)
    {
        // Windows prints nothing, so say it ran rather than show an empty version.
        var launched = launch["version"] as string;
        Console.WriteLine($"Launch:    ✓ {(string.IsNullOrEmpty(launched) ? "runs (no version reported on Windows)" : launched)}");
    }
    else
    {
        Console.WriteLine($"Launch:    ✗ failed — {launch["error"]}");
        var libs = launch.GetValueOrDefault("missing_libs") as List<string> ?? new();
        foreach (var lib in libs)
            Console.WriteLine($"           missing: {lib}");
        if (libs.Count > 0)
            Console.WriteLine("           → install the missing system libraries (e.g. apt-get install)");
    }

    if (diag.TryGetValue("fonts", out var fontsObj) && fontsObj is Dictionary<string, object?> fonts)
    {
        if (fonts["windows"] is int[] win)
        {
            int n = win[0], total = win[1];
            string verdict = n == total ? "ok" : n == 0 ? "missing" : "partial";
            Console.WriteLine($"Win fonts: {verdict} ({n}/{total})");
            if (n < total)
                Console.WriteLine("           → incomplete Windows font set; copy real Windows fonts (Segoe UI, Calibri, Consolas)");
        }
        else
        {
            Console.WriteLine("Win fonts: unknown (fc-list unavailable)");
        }
        // Office is informational only — no Office pack is a normal Windows
        // persona (~53% of real machines have none), so no install nudge.
        if (fonts.TryGetValue("office", out var officeObj) && officeObj is int[] office)
        {
            int n = office[0], total = office[1];
            string verdict = n == total ? "ok" : n == 0 ? "absent" : "partial";
            Console.WriteLine($"Office fonts: {verdict} ({n}/{total})");
        }
        if (fonts.TryGetValue("macos", out var macObj) && macObj is int[] mac)
        {
            int n = mac[0], total = mac[1];
            string verdict = n == total ? "ok" : n == 0 ? "missing" : "partial";
            Console.WriteLine($"Mac fonts: {verdict} ({n}/{total})");
            if (n < total)
                // Phrased conditionally: some Mac fonts also ship on a Windows box,
                // so a partial count is expected unless macOS is the intended persona.
                Console.WriteLine("           → if spoofing macOS on this host, copy the real Mac fonts (Helvetica Neue, Menlo, SF/Apple system fonts)");
        }
        else
        {
            Console.WriteLine("Mac fonts: unknown (fc-list unavailable)");
        }
    }

    var lic = (Dictionary<string, object?>)diag["license"]!;
    string tier = (string)lic["tier"]!;
    bool validated = lic.TryGetValue("valid", out var validObj) && validObj is true;
    if (tier == "free" && validated)
    {
        Console.WriteLine("License:   Free (latest binary, 1 concurrent session)");
        Console.WriteLine($"           {UpgradeHint}");
    }
    else if (tier == "none")
    {
        Console.WriteLine("License:   none (a launch needs a key)");
        Console.WriteLine($"           {NoKeyHint}");
    }
    else if (lic.ContainsKey("error"))
    {
        Console.WriteLine($"License:   {tier} ({lic["error"]})");
    }
    else
    {
        Console.WriteLine($"License:   {tier}");
    }

    if (lic.TryGetValue("sessions", out var sessionsObj) && sessionsObj is Dictionary<string, object?> sessions)
    {
        Console.WriteLine($"Sessions:  {Diagnostics.FormatSeats(sessions)}");
    }

    var geoip = (Dictionary<string, object?>)diag["geoip"]!;
    bool hasResolved = geoip.TryGetValue("resolved", out var resolvedObj) && resolvedObj is Dictionary<string, object?>;
    string dbLine = geoip["db_present"] is true ? "present" : "not downloaded (optional)";
    if (!hasResolved)
        dbLine += "  (pass --proxy <url> to resolve exit IP + timezone/locale)";
    Console.WriteLine($"GeoIP DB:  {dbLine}");
    if (hasResolved && resolvedObj is Dictionary<string, object?> resolved)
    {
        if (resolved.TryGetValue("error", out var errObj) && errObj is not null)
        {
            Console.WriteLine($"Exit IP:   (could not resolve — {errObj})");
        }
        else
        {
            Console.WriteLine($"Exit IP:   {resolved.GetValueOrDefault("exit_ip") ?? "(unknown)"}");
            Console.WriteLine($"Timezone:  {resolved.GetValueOrDefault("timezone") ?? "(unknown)"}");
            Console.WriteLine($"Locale:    {resolved.GetValueOrDefault("locale") ?? "(unknown)"}");
        }
    }

    if (diag.TryGetValue("modules", out var modulesObj) && modulesObj is Dictionary<string, object?> modules)
    {
        Console.WriteLine("Modules:");
        foreach (var kv in modules)
            Console.WriteLine($"  {kv.Key}: {(kv.Value is true ? "ok" : "missing")}");
    }
}

static async Task<int> CmdUpdate()
{
    string? key = License.ResolveLicenseKey();
    if (string.IsNullOrEmpty(key) || License.ValidateLicense(key)?.Valid != true)
    {
        Console.Error.WriteLine($"No valid license key. {NoKeyHint}");
        return 1;
    }

    CloakLog.Info("Checking for updates...");
    string? newVersion = await Download.CheckForProUpdateAsync(key).ConfigureAwait(false);
    Console.WriteLine(newVersion != null
        ? $"Updated to Chromium {newVersion}"
        : "Already up to date.");
    return 0;
}

static void CmdClearCache()
{
    if (!Directory.Exists(Config.GetCacheDir()))
    {
        Console.WriteLine("No cache to clear.");
        return;
    }
    Download.ClearCache();
    Console.WriteLine("Cache cleared.");
}

// Activate any key. `login <key>` saves a pasted key; bare `login` shows the same
// menu as a no-key launch: get a free key by email, or paste one. Mirrors Python cmd_login.
static int CmdLogin(string[] flags)
{
    string key = (flags.Length > 0 ? flags[0] : "").Trim();

    if (string.IsNullOrEmpty(key))
    {
        // Same check as a launch: the menu is written to stderr, so both must be a terminal.
        if (!Download.CanPrompt())
        {
            Console.Error.WriteLine(
                "Usage: cloakbrowser login <key>  (or run it interactively for a free key).");
            return 2;
        }
        try
        {
            key = Download.PromptLicenseKey();
        }
        catch (EndOfStreamException)
        {
            key = "";
        }
    }

    if (string.IsNullOrEmpty(key))
    {
        Console.Error.WriteLine("No key entered. Nothing saved.");
        return 1;
    }

    LicenseInfo? info = License.ValidateLicense(key);
    if (info is null)
    {
        Console.Error.WriteLine(
            "Could not reach the license server to verify the key. Check your connection and retry.");
        return 1;
    }
    if (!info.Valid)
    {
        Console.Error.WriteLine("That license key is invalid or expired. Nothing was saved.");
        return 1;
    }

    try
    {
        License.SaveLicenseKey(key);
    }
    catch (ArgumentException)
    {
        Console.Error.WriteLine("That is not a CloakBrowser license key (they start with cb_). Nothing was saved.");
        return 1;
    }
    if (info.Plan == "free")
    {
        Console.WriteLine(
            "Saved. Free tier active: latest binary, 1 concurrent session (one browser at a time).");
        Console.WriteLine("Need to run more at once? See the plans at https://cloakbrowser.dev");
    }
    else
    {
        Console.WriteLine($"Saved. {TitleCase(info.Plan)} key active: latest binary, full plan limits.");
    }
    return 0;
}

// Remove the saved license key. Mirrors Python cmd_logout.
static int CmdLogout()
{
    // A pending claim code would quietly reinstall a key on the next launch.
    try { File.Delete(Path.Combine(Config.GetCacheDir(), ".free_claim")); }
    catch (IOException) { }
    string keyFile = Path.Combine(Config.GetCacheDir(), "license.key");
    if (File.Exists(keyFile))
    {
        try
        {
            File.Delete(keyFile);
        }
        catch (IOException e)
        {
            Console.Error.WriteLine($"Could not remove {keyFile}: {e.Message}");
            return 1;
        }
        Console.WriteLine("Logged out. Removed the saved key; launches need a key again.");
    }
    else
    {
        Console.WriteLine("No saved license key found.");
    }
    return 0;
}

static string TitleCase(string s) =>
    string.IsNullOrEmpty(s) ? s : char.ToUpperInvariant(s[0]) + s.Substring(1);

static void PrintHelp()
{
    Console.WriteLine("usage: cloakbrowser <command>");
    Console.WriteLine();
    Console.WriteLine("Manage the CloakBrowser stealth Chromium binary.");
    Console.WriteLine();
    Console.WriteLine("commands:");
    Console.WriteLine("  login        Save a license key (or get a free key by email)");
    Console.WriteLine("  logout       Remove the saved license key");
    Console.WriteLine("  install      Download the Chromium binary");
    Console.WriteLine("  info         Environment + binary diagnostics (--quick, --json)");
    Console.WriteLine("  doctor       Alias for info");
    Console.WriteLine("  update       Check for and download a newer binary");
    Console.WriteLine("  clear-cache  Remove all cached binaries");
}
