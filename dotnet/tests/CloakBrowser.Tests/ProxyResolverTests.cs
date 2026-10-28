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
    public void Http_With_Creds_Uses_InlineAuth_On_Binary_With_Patch()
    {
        // Pin a version at/above every platform floor → inline on any host.
        var r = ProxyResolver.Resolve("http://user:pass@host:8080", "148.0.7778.215.3");
        Assert.Null(r.PlaywrightProxy);
        Assert.Equal("--proxy-server=http://user:pass@host:8080", Assert.Single(r.ExtraArgs));
    }

    [Fact]
    public void Http_With_Creds_Falls_Back_On_Binary_Without_Patch()
    {
        // Pin a version below every platform floor → Playwright proxy on any host.
        var r = ProxyResolver.Resolve("http://user:pass@host:8080", "146.0.7680.177.3");
        Assert.Empty(r.ExtraArgs);
        Assert.NotNull(r.PlaywrightProxy);
        Assert.Equal("http://host:8080", r.PlaywrightProxy!.Server);
        Assert.Equal("user", r.PlaywrightProxy.Username);
        Assert.Equal("pass", r.PlaywrightProxy.Password);
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
    public void ExtractProxyUrl_Http_Dict_Reconstructs_With_Creds()
    {
        var url = ProxyResolver.ExtractProxyUrl(new ProxySettings
        {
            Server = "host:8080", Username = "user@tenant", Password = "p:ss",
        });
        Assert.Equal("http://user%40tenant:p%3Ass@host:8080", url);
    }

    [Fact]
    public void IsSocksProxy_Detects_Variants()
    {
        Assert.True(ProxyResolver.IsSocksProxy("socks5://h:1"));
        Assert.True(ProxyResolver.IsSocksProxy("socks5h://h:1"));
        Assert.False(ProxyResolver.IsSocksProxy("http://h:1"));
    }
}
