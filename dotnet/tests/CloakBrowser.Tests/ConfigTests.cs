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
}
