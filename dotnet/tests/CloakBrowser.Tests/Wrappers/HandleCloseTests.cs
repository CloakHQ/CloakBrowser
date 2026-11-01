using CloakBrowser;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests.Wrappers;

/// <summary>
/// Playwright's own CloseAsync takes options (e.g. Reason); the handles must forward
/// them and still run their cleanup (browser close + Playwright dispose).
/// </summary>
public class HandleCloseTests
{
    [Fact]
    public async Task Context_close_forwards_options_and_closes_browser()
    {
        var (playwright, pwRec) = Fake.Of<IPlaywright>();
        var (browser, browserRec) = Fake.Of<IBrowser>();
        var (ctx, ctxRec) = Fake.Of<IBrowserContext>();
        var handle = new CloakContextHandle(playwright, browser, ctx, humanize: false, null);

        var options = new BrowserContextCloseOptions { Reason = "shutting down" };
        await handle.CloseAsync(options);

        Assert.Same(options, ctxRec.Last("CloseAsync")!.Args[0]);
        Assert.Equal(1, browserRec.CountOf("CloseAsync"));
        Assert.Equal(1, pwRec.CountOf("Dispose"));
    }

    [Fact]
    public async Task Context_close_still_closes_browser_when_context_close_throws()
    {
        var (playwright, pwRec) = Fake.Of<IPlaywright>();
        var (browser, browserRec) = Fake.Of<IBrowser>();
        var (ctx, ctxRec) = Fake.Of<IBrowserContext>();
        ctxRec.On("CloseAsync", _ => Task.FromException(new InvalidOperationException("boom")));
        var handle = new CloakContextHandle(playwright, browser, ctx, humanize: false, null);

        await Assert.ThrowsAsync<InvalidOperationException>(() => handle.CloseAsync());

        Assert.Equal(1, browserRec.CountOf("CloseAsync"));
        Assert.Equal(1, pwRec.CountOf("Dispose"));
    }

    [Fact]
    public async Task Browser_close_forwards_options()
    {
        var (playwright, pwRec) = Fake.Of<IPlaywright>();
        var (browser, browserRec) = Fake.Of<IBrowser>();
        var handle = new CloakBrowserHandle(playwright, browser, humanize: false, null);

        var options = new BrowserCloseOptions { Reason = "shutting down" };
        await handle.CloseAsync(options);

        Assert.Same(options, browserRec.Last("CloseAsync")!.Args[0]);
        Assert.Equal(1, pwRec.CountOf("Dispose"));
    }
}
