using CloakBrowser;
using Xunit;

namespace CloakBrowser.Tests;

public class ProxyResolverTests
{
    [Fact]
    public void Null_Proxy_Returns_Empty()
    {
        var r = ProxyResolver.Resolve(null);
        Assert.Null(r.PlaywrightProxy);
        Assert.Empty(r.ExtraArgs);
    }

    [Fact]
    public void Socks5_String_With_Creds_Uses_ProxyServerArg()
    {
        var r = ProxyResolver.Resolve("socks5://user:pass@host:1080");
        Assert.Null(r.PlaywrightProxy);
        Assert.Single(r.ExtraArgs);
        Assert.StartsWith("--proxy-server=socks5://", r.ExtraArgs[0]);
        Assert.Contains("user:pass@host:1080", r.ExtraArgs[0]);
    }

    [Fact]
    public void Socks5_Dict_With_Creds_And_Bypass()
    {
        var r = ProxyResolver.Resolve(new ProxySettings
        {
            Server = "socks5://host:1080",
            Username = "u",
            Password = "p",
            Bypass = ".google.com",
        });
        Assert.Null(r.PlaywrightProxy);
        Assert.Contains(r.ExtraArgs, a => a.StartsWith("--proxy-server=socks5://u:p@host:1080"));
        Assert.Contains("--proxy-bypass-list=.google.com", r.ExtraArgs);
    }

    [Fact]
    public void Socks5_Creds_With_Special_Chars_Are_Encoded()
    {
        // Password contains '=' and '@' which Chromium would truncate; expect encoding.
        var r = ProxyResolver.Resolve("socks5://user:p=ss@word@host:1080");
        Assert.Single(r.ExtraArgs);
        // '=' -> %3D, the literal '@' inside the password -> %40
        Assert.Contains("%3D", r.ExtraArgs[0]);
    }

    [Fact]
    public void Http_Without_Creds_Uses_PlaywrightProxy()
    {
        var r = ProxyResolver.Resolve("http://host:8080");
        Assert.NotNull(r.PlaywrightProxy);
        Assert.Equal("http://host:8080", r.PlaywrightProxy!.Server);
        Assert.Empty(r.ExtraArgs);
    }

    [Fact]
    public void Http_Dict_Without_Creds_Uses_PlaywrightProxy()
    {
        var r = ProxyResolver.Resolve(new ProxySettings { Server = "http://host:8080" });
        Assert.NotNull(r.PlaywrightProxy);
        Assert.Equal("http://host:8080", r.PlaywrightProxy!.Server);
    }

    [Fact]
    public void Http_With_Creds_Parses_Into_PlaywrightFields_When_InlineAuth_Unsupported()
    {
        // On platforms NOT in the inline-auth set (e.g. linux-arm64, darwin-*),
        // HTTP creds go to the Playwright proxy dict. On linux-x64/windows-x64 with
        // a recent binary they go to --proxy-server. Accept either valid outcome.
        var r = ProxyResolver.Resolve("http://user:pass@host:8080");
        bool inlineArg = r.ExtraArgs.Any(a => a.StartsWith("--proxy-server="));
        bool pwProxy = r.PlaywrightProxy != null;
        Assert.True(inlineArg ^ pwProxy, "Exactly one of inline-arg or playwright-proxy should be set");
        if (pwProxy)
        {
            Assert.Equal("http://host:8080", r.PlaywrightProxy!.Server);
            Assert.Equal("user", r.PlaywrightProxy.Username);
            Assert.Equal("pass", r.PlaywrightProxy.Password);
        }
    }

    [Fact]
    public void ExtractProxyUrl_AddsScheme_For_Bare()
    {
        Assert.Equal("http://host:8080", ProxyResolver.ExtractProxyUrl("host:8080"));
    }

    [Fact]
    public void ExtractProxyUrl_Socks_Dict_Reconstructs_With_Creds()
    {
        var url = ProxyResolver.ExtractProxyUrl(new ProxySettings
        {
            Server = "socks5://host:1080", Username = "u", Password = "p",
        });
        Assert.Equal("socks5://u:p@host:1080", url);
    }

    [Fact]
    public void IsSocksProxy_Detects_Variants()
    {
        Assert.True(ProxyResolver.IsSocksProxy("socks5://h:1"));
        Assert.True(ProxyResolver.IsSocksProxy("socks5h://h:1"));
        Assert.False(ProxyResolver.IsSocksProxy("http://h:1"));
    }
}
