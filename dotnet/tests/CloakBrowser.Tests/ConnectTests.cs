using System;
using System.Threading.Tasks;
using CloakBrowser;
using CloakBrowser.Human;
using Xunit;

namespace CloakBrowser.Tests;

public class ConnectTests
{
    [Fact]
    public void ConnectOptions_Defaults()
    {
        var o = new ConnectOptions();
        Assert.False(o.Humanize);
        Assert.Equal(HumanPreset.Default, o.HumanPreset);
        Assert.True(o.DefaultNoViewport); // no-viewport on by default (parity with Python/JS)
        Assert.Null(o.HumanConfig);
    }

    [Fact]
    public async Task ConnectAsync_UnreachableEndpoint_Throws()
    {
        // No browser is listening on this port; ConnectOverCDPAsync fails, and
        // ConnectAsync disposes Playwright and rethrows rather than leaking the driver.
        await Assert.ThrowsAnyAsync<Exception>(
            () => CloakLauncher.ConnectAsync("http://127.0.0.1:1"));
    }
}
