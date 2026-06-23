using CloakBrowser;

// CLI for cloakbrowser - download and manage the stealth Chromium binary.
// Direct port of Python cloakbrowser/__main__.py.
//
// Usage:
//   cloakbrowser install      # Download binary (with progress)
//   cloakbrowser info         # Show binary version, path, platform
//   cloakbrowser update       # Check for and download newer binary
//   cloakbrowser clear-cache  # Remove cached binaries

// Route CloakBrowser logs to stderr at Info level (clean output).
CloakLog.MinLevel = CloakLogLevel.Info;

string? command = args.Length > 0 ? args[0] : null;

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
            CmdInfo();
            break;
        case "update":
            await CmdUpdate();
            break;
        case "clear-cache":
            CmdClearCache();
            break;
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

static void CmdInfo()
{
    var info = Download.BinaryInfo();
    string? over = Config.GetLocalBinaryOverride();

    Console.WriteLine($"Version:   {info.Version}");
    Console.WriteLine($"Platform:  {info.Platform}");
    Console.WriteLine($"Binary:    {info.BinaryPath}");
    Console.WriteLine($"Installed: {info.Installed}");
    Console.WriteLine($"Cache:     {info.CacheDir}");
    if (!string.IsNullOrEmpty(over))
        Console.WriteLine($"Override:  {over} (CLOAKBROWSER_BINARY_PATH)");
}

static async Task CmdUpdate()
{
    CloakLog.Info("Checking for updates...");
    string? newVersion = await Download.CheckForUpdateAsync().ConfigureAwait(false);
    Console.WriteLine(newVersion != null
        ? $"Updated to Chromium {newVersion}"
        : "Already up to date.");
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

static void PrintHelp()
{
    Console.WriteLine("usage: cloakbrowser <command>");
    Console.WriteLine();
    Console.WriteLine("Manage the CloakBrowser stealth Chromium binary.");
    Console.WriteLine();
    Console.WriteLine("commands:");
    Console.WriteLine("  install      Download the Chromium binary");
    Console.WriteLine("  info         Show binary version, path, and platform");
    Console.WriteLine("  update       Check for and download a newer binary");
    Console.WriteLine("  clear-cache  Remove all cached binaries");
}
