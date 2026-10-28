using System.Runtime.CompilerServices;

namespace CloakBrowser.Tests;

/// <summary>
/// Keeps the suite away from the developer's real <c>~/.cloakbrowser</c> (port of the Python
/// <c>isolated_cache_dir</c> fixture in <c>tests/conftest.py</c>).
///
/// A <c>license.key</c> or a cached Pro build in the real cache dir resolves the machine as Pro,
/// which flips version-gated defaults such as the headless no-viewport gate, so tests would assert
/// against whatever the developer happens to have installed. Tests that set their own
/// <c>CLOAKBROWSER_CACHE_DIR</c> still win, since they save and restore around this value.
///
/// Real-browser runs (<c>CLOAKBROWSER_BINARY_PATH</c> set, see <see cref="BrowserFactAttribute"/>)
/// opt out and run like a user machine with the developer's key, as the Python fixture does.
/// </summary>
internal static class IsolatedCacheDir
{
    [ModuleInitializer]
    internal static void Init()
    {
        if (BrowserFactAttribute.Available) return;
        if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR"))) return;
        var dir = Path.Combine(Path.GetTempPath(), "cloakbrowser-test-cache-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(dir);
        Environment.SetEnvironmentVariable("CLOAKBROWSER_CACHE_DIR", dir);
    }
}
