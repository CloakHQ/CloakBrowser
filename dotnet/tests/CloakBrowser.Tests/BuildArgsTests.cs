using CloakBrowser;
using Xunit;

namespace CloakBrowser.Tests;

public class BuildArgsTests
{
    [Fact]
    public void Dedupes_By_FlagKey_UserOverridesStealth()
    {
        var args = CloakLauncher.BuildArgs(
            stealthArgs: true,
            extraArgs: new List<string> { "--no-sandbox=foo" },
            headless: true);
        // --no-sandbox should appear once, with the user's value winning.
        Assert.Single(args, a => a.StartsWith("--no-sandbox"));
        Assert.Contains("--no-sandbox=foo", args);
    }

    [Fact]
    public void Timezone_And_Locale_Flags_Injected()
    {
        var args = CloakLauncher.BuildArgs(
            stealthArgs: false,
            extraArgs: null,
            timezone: "America/New_York",
            locale: "en-US",
            headless: true);
        Assert.Contains("--fingerprint-timezone=America/New_York", args);
        Assert.Contains("--lang=en-US", args);
        Assert.Contains("--fingerprint-locale=en-US", args);
    }

    [Fact]
    public void Headed_Adds_IgnoreGpuBlocklist()
    {
        var args = CloakLauncher.BuildArgs(stealthArgs: false, extraArgs: null, headless: false);
        Assert.Contains("--ignore-gpu-blocklist", args);
    }

    [Fact]
    public void DedicatedParams_Override_UserArgs()
    {
        var args = CloakLauncher.BuildArgs(
            stealthArgs: false,
            extraArgs: new List<string> { "--fingerprint-timezone=Europe/London" },
            timezone: "Asia/Tokyo",
            headless: true);
        Assert.Single(args, a => a.StartsWith("--fingerprint-timezone"));
        Assert.Contains("--fingerprint-timezone=Asia/Tokyo", args);
    }

    [Fact]
    public void ExtensionPaths_Produce_LoadExtension_And_DisableExcept()
    {
        var tmp = Directory.CreateTempSubdirectory().FullName;
        try
        {
            var args = CloakLauncher.BuildArgs(
                stealthArgs: false,
                extraArgs: null,
                extensionPaths: new List<string> { tmp });
            Assert.Contains(args, a => a.StartsWith("--load-extension="));
            Assert.Contains(args, a => a.StartsWith("--disable-extensions-except="));
        }
        finally { Directory.Delete(tmp); }
    }

    [Fact]
    public void NoLocale_NoTimezone_NoFlags()
    {
        var args = CloakLauncher.BuildArgs(stealthArgs: false, extraArgs: null, headless: true);
        Assert.DoesNotContain(args, a => a.StartsWith("--lang="));
        Assert.DoesNotContain(args, a => a.StartsWith("--fingerprint-timezone="));
    }
}
