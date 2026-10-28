using CloakBrowser;
using Xunit;

namespace CloakBrowser.Tests;

public class ConfigTests
{
    [Fact]
    public void ChromiumVersion_IsPinned()
    {
        Assert.Equal("146.0.7680.177.5", Config.ChromiumVersion);
    }

    [Fact]
    public void DefaultViewport_Matches_Python()
    {
        Assert.Equal(1920, Config.DefaultViewportWidth);
        Assert.Equal(947, Config.DefaultViewportHeight);
    }

    [Fact]
    public void IgnoreDefaultArgs_IsNonEmpty()
    {
        Assert.NotEmpty(Config.IgnoreDefaultArgs);
    }

    [Fact]
    public void GetPlatformTag_ReturnsKnownTag()
    {
        var tag = Config.GetPlatformTag();
        Assert.Contains(tag, new[] { "linux-x64", "linux-arm64", "darwin-arm64", "darwin-x64", "windows-x64" });
    }

    [Theory]
    [InlineData("146.0.7680.177.5", "146.0.7680.177.5", 0)]
    [InlineData("146.0.7680.177.6", "146.0.7680.177.5", 1)]
    [InlineData("146.0.7680.177.4", "146.0.7680.177.5", -1)]
    [InlineData("147.0.0.0.0", "146.9.9.9.9", 1)]
    public void VersionTuple_Comparison(string a, string b, int sign)
    {
        var ta = Config.VersionTuple(a);
        var tb = Config.VersionTuple(b);
        int cmp = 0;
        int n = System.Math.Max(ta.Length, tb.Length);
        for (int i = 0; i < n; i++)
        {
            int va = i < ta.Length ? ta[i] : 0;
            int vb = i < tb.Length ? tb[i] : 0;
            if (va != vb) { cmp = va.CompareTo(vb); break; }
        }
        Assert.Equal(sign, System.Math.Sign(cmp));
    }

    [Fact]
    public void VersionNewer_Works()
    {
        Assert.True(Config.VersionNewer("147.0.0.0.0", "146.0.0.0.0"));
        Assert.False(Config.VersionNewer("146.0.0.0.0", "146.0.0.0.0"));
        Assert.False(Config.VersionNewer("145.0.0.0.0", "146.0.0.0.0"));
    }

    [Fact]
    public void GetDefaultStealthArgs_IncludesNoSandboxAndFingerprint()
    {
        var args = Config.GetDefaultStealthArgs();
        Assert.Contains("--no-sandbox", args);
        Assert.Contains(args, a => a.StartsWith("--fingerprint="));
        Assert.Contains(args, a => a.StartsWith("--fingerprint-platform="));
    }

    [Fact]
    public void GetDefaultStealthArgs_RandomSeed_InRange()
    {
        var args = Config.GetDefaultStealthArgs();
        var seedArg = args.First(a => a.StartsWith("--fingerprint="));
        int seed = int.Parse(seedArg.Split('=')[1]);
        Assert.InRange(seed, 10000, 99999);
    }

    // NormalizeRequestedVersion tests (port of Python/JS browser_version pinning)

    [Theory]
    [InlineData("146.0.7680.177")]
    [InlineData("146.0.7680.177.5")]
    [InlineData("148.0.7778.215.2")]
    [InlineData("1.2.3.4")]
    [InlineData("123.456.789.012")]
    public void NormalizeRequestedVersion_ValidFormats(string version)
    {
        Assert.Equal(version, Config.NormalizeRequestedVersion(version));
    }

    [Theory]
    [InlineData("  146.0.7680.177  ", "146.0.7680.177")]
    public void NormalizeRequestedVersion_TrimsWhitespace(string input, string expected)
    {
        Assert.Equal(expected, Config.NormalizeRequestedVersion(input));
    }

    [Theory]
    [InlineData("v146.0.7680.177")]
    [InlineData("146")]
    [InlineData("146.0")]
    [InlineData("146.0.7680")]
    [InlineData("146.0.7680.177.5.6")] // 6 segments — too many
    [InlineData("latest")]
    [InlineData("../etc/passwd")]
    [InlineData("١٤٦.0.7680.177")] // non-ASCII digits — parity with JS [0-9]
    public void NormalizeRequestedVersion_InvalidFormats_Throw(string version)
    {
        var ex = Assert.Throws<ArgumentException>(() => Config.NormalizeRequestedVersion(version));
        Assert.Contains("browser version pin", ex.Message);
    }

    [Fact]
    public void NormalizeRequestedVersion_Null_ReturnsNull()
    {
        // Isolate the env so a CLOAKBROWSER_VERSION set in the test runner can't
        // make null fall through to the env value (parity with Python/JS).
        var prev = Environment.GetEnvironmentVariable("CLOAKBROWSER_VERSION");
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_VERSION", null);
            Assert.Null(Config.NormalizeRequestedVersion(null));
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_VERSION", prev);
        }
    }

    [Theory]
    [InlineData("")]
    [InlineData(" ")]
    [InlineData("  ")]
    public void NormalizeRequestedVersion_EmptyOrWhitespace_ReturnsNull(string version)
    {
        // Explicit empty/whitespace returns null without reading the env, but
        // isolate anyway so a set CLOAKBROWSER_VERSION can't perturb the result.
        var prev = Environment.GetEnvironmentVariable("CLOAKBROWSER_VERSION");
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_VERSION", null);
            Assert.Null(Config.NormalizeRequestedVersion(version));
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_VERSION", prev);
        }
    }

    [Fact]
    public void NormalizeRequestedVersion_ReadsEnv()
    {
        var prev = Environment.GetEnvironmentVariable("CLOAKBROWSER_VERSION");
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_VERSION", "148.0.7778.215.2");
            Assert.Equal("148.0.7778.215.2", Config.NormalizeRequestedVersion(null));
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_VERSION", prev);
        }
    }

    [Fact]
    public void NormalizeRequestedVersion_ExplicitWinsOverEnv()
    {
        var prev = Environment.GetEnvironmentVariable("CLOAKBROWSER_VERSION");
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_VERSION", "146.0.0.0");
            Assert.Equal("148.0.7778.215.2", Config.NormalizeRequestedVersion("148.0.7778.215.2"));
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_VERSION", prev);
        }
    }
}

[Collection("env-serial")]
public class ReleaseChannelConfigTests
{
    [Fact]
    public void NormalizeReleaseChannel_defaults_to_stable()
    {
        var previous = Environment.GetEnvironmentVariable("CLOAKBROWSER_RELEASE_CHANNEL");
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_RELEASE_CHANNEL", null);
            Assert.Equal("stable", Config.NormalizeReleaseChannel());
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_RELEASE_CHANNEL", previous);
        }
    }

    [Theory]
    [InlineData(" preview ", "preview")]
    [InlineData("PREVIEW", "preview")]
    [InlineData("stable", "stable")]
    [InlineData("unknown", "stable")]
    public void NormalizeReleaseChannel_normalizes_values(string input, string expected)
        => Assert.Equal(expected, Config.NormalizeReleaseChannel(input));

    [Fact]
    public void NormalizeReleaseChannel_explicit_stable_overrides_environment()
    {
        var previous = Environment.GetEnvironmentVariable("CLOAKBROWSER_RELEASE_CHANNEL");
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_RELEASE_CHANNEL", "preview");
            Assert.Equal("preview", Config.NormalizeReleaseChannel());
            Assert.Equal("stable", Config.NormalizeReleaseChannel("stable"));
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_RELEASE_CHANNEL", previous);
        }
    }
}

/// <summary>
/// Config.BinarySupportsHeadlessNoViewport() — parity-critical: Python and JS mirror
/// this gate. Threshold is an unshipped version, so the resolved-version path is a
/// no-op today; the declared-version path is what these tests pin. In env-serial
/// because the override tests mutate CLOAKBROWSER_BINARY_PATH.
/// </summary>
[Collection("env-serial")]
public class HeadlessNoViewportGateTests
{
    [Fact]
    public void DeclaredBelowThreshold_Off()
    {
        // Current live Pro version — one build below the threshold => feature OFF.
        Assert.False(Config.BinarySupportsHeadlessNoViewport(browserVersion: "148.0.7778.215.3"));
    }

    [Fact]
    public void DeclaredAtThreshold_On()
    {
        Assert.True(Config.BinarySupportsHeadlessNoViewport(browserVersion: "148.0.7778.215.4"));
    }

    [Fact]
    public void DeclaredAboveThreshold_On()
    {
        Assert.True(Config.BinarySupportsHeadlessNoViewport(browserVersion: "149.0.0.0"));
    }

    [Fact]
    public void DeclaredWinsOverLocalOverride()
    {
        var prev = Environment.GetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH");
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH", "/fake/chrome");
            Assert.True(Config.BinarySupportsHeadlessNoViewport(browserVersion: "149.0.0.0"));
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH", prev);
        }
    }

    [Fact]
    public void LocalOverrideWithoutDeclared_Off()
    {
        var prev = Environment.GetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH");
        try
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH", "/fake/chrome");
            Assert.False(Config.BinarySupportsHeadlessNoViewport());
        }
        finally
        {
            Environment.SetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH", prev);
        }
    }
}

/// <summary>
/// BinarySupportsMaximizedWindow() — parity-critical: Python and JS mirror this gate.
/// Shares the no_viewport threshold today.
/// </summary>
public class MaximizedWindowGateTests
{
    [Fact]
    public void DeclaredBelowThreshold_Off()
    {
        Assert.False(Config.BinarySupportsMaximizedWindow(browserVersion: "148.0.7778.215.3"));
    }

    [Fact]
    public void DeclaredAtThreshold_On()
    {
        Assert.True(Config.BinarySupportsMaximizedWindow(browserVersion: "148.0.7778.215.4"));
    }

    [Fact]
    public void DeclaredAboveThreshold_On()
    {
        Assert.True(Config.BinarySupportsMaximizedWindow(browserVersion: "149.0.0.0"));
    }
}
