using CloakBrowser.Human;
using CloakBrowser.Wrappers;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests.Wrappers;

/// <summary>
/// Tests for <see cref="HumanizedBrowser"/> / <see cref="HumanizedBrowserContext"/>:
/// the wrapping chain must be complete - a wrapped browser produces wrapped contexts
/// and pages, and a wrapped context produces wrapped pages, so there are no raw leaks.
/// </summary>
public class BrowserContextWrapperTests
{
    private static IPage MakeFakePage()
    {
        var (mouse, _) = Fake.Of<IMouse>();
        var (keyboard, _) = Fake.Of<IKeyboard>();
        var (page, pageRec) = Fake.Of<IPage>();
        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);
        pageRec.On("ViewportSize", new PageViewportSizeResult { Width = 800, Height = 600 });
        return page;
    }

    // -----------------------------------------------------------------------
    // Context
    // -----------------------------------------------------------------------

    [Fact]
    public async Task Context_NewPageAsync_returns_wrapped_page()
    {
        var (ctx, ctxRec) = Fake.Of<IBrowserContext>();
        ctxRec.On("NewPageAsync", Task.FromResult(MakeFakePage()));

        var human = Humanize.Context(ctx, new HumanConfig());
        var page = await human.NewPageAsync();

        Assert.IsType<HumanizedPage>(page);
    }

    [Fact]
    public void Context_Pages_returns_wrapped_pages()
    {
        var (ctx, ctxRec) = Fake.Of<IBrowserContext>();
        ctxRec.On("Pages", new List<IPage> { MakeFakePage(), MakeFakePage() });

        var human = Humanize.Context(ctx, new HumanConfig());

        Assert.Equal(2, human.Pages.Count);
        Assert.All(human.Pages, p => Assert.IsType<HumanizedPage>(p));
    }

    [Fact]
    public async Task Context_delegated_member_forwards_to_inner()
    {
        var (ctx, ctxRec) = Fake.Of<IBrowserContext>();
        ctxRec.On("CookiesAsync", Task.FromResult<IReadOnlyList<BrowserContextCookiesResult>>(
            new List<BrowserContextCookiesResult>()));

        var human = Humanize.Context(ctx, new HumanConfig());
        await human.CookiesAsync();

        Assert.True(ctxRec.WasCalled("CookiesAsync"));
    }

    [Fact]
    public void Context_Original_exposes_inner()
    {
        var (ctx, _) = Fake.Of<IBrowserContext>();
        var human = (HumanizedBrowserContext)Humanize.Context(ctx, new HumanConfig());
        Assert.Same(ctx, human.Original);
        Assert.Same(ctx, human.Inner);
    }

    [Fact]
    public void Context_wrapping_is_idempotent()
    {
        var (ctx, _) = Fake.Of<IBrowserContext>();
        var once = Humanize.Context(ctx, new HumanConfig());
        var twice = Humanize.Context(once, new HumanConfig());
        Assert.Same(once, twice);
    }

    // -----------------------------------------------------------------------
    // Browser
    // -----------------------------------------------------------------------

    [Fact]
    public async Task Browser_NewPageAsync_returns_wrapped_page()
    {
        var (browser, browserRec) = Fake.Of<IBrowser>();
        browserRec.On("NewPageAsync", Task.FromResult(MakeFakePage()));

        var human = Humanize.Browser(browser, new HumanConfig());
        var page = await human.NewPageAsync();

        Assert.IsType<HumanizedPage>(page);
    }

    [Fact]
    public async Task Browser_NewContextAsync_returns_wrapped_context()
    {
        var (ctx, _) = Fake.Of<IBrowserContext>();
        var (browser, browserRec) = Fake.Of<IBrowser>();
        browserRec.On("NewContextAsync", Task.FromResult(ctx));

        var human = Humanize.Browser(browser, new HumanConfig());
        var context = await human.NewContextAsync();

        Assert.IsType<HumanizedBrowserContext>(context);
    }

    [Fact]
    public void Browser_Contexts_returns_wrapped_contexts()
    {
        var (ctx1, _) = Fake.Of<IBrowserContext>();
        var (ctx2, _) = Fake.Of<IBrowserContext>();
        var (browser, browserRec) = Fake.Of<IBrowser>();
        browserRec.On("Contexts", new List<IBrowserContext> { ctx1, ctx2 });

        var human = Humanize.Browser(browser, new HumanConfig());

        Assert.Equal(2, human.Contexts.Count);
        Assert.All(human.Contexts, c => Assert.IsType<HumanizedBrowserContext>(c));
    }

    [Fact]
    public async Task Browser_full_chain_browser_to_context_to_page_is_all_wrapped()
    {
        var (page, pageRec) = Fake.Of<IPage>();
        var (mouse, _) = Fake.Of<IMouse>();
        var (keyboard, _) = Fake.Of<IKeyboard>();
        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);

        var (ctx, ctxRec) = Fake.Of<IBrowserContext>();
        ctxRec.On("NewPageAsync", Task.FromResult<IPage>(page));

        var (browser, browserRec) = Fake.Of<IBrowser>();
        browserRec.On("NewContextAsync", Task.FromResult(ctx));

        var human = Humanize.Browser(browser, new HumanConfig());
        var context = await human.NewContextAsync();
        var leaf = await context.NewPageAsync();

        // No raw leaks anywhere along the chain.
        Assert.IsType<HumanizedBrowserContext>(context);
        Assert.IsType<HumanizedPage>(leaf);
        Assert.IsType<HumanizedMouse>(leaf.Mouse);
        Assert.IsType<HumanizedKeyboard>(leaf.Keyboard);
    }

    [Fact]
    public async Task Browser_delegated_member_exception_propagates()
    {
        var (browser, browserRec) = Fake.Of<IBrowser>();
        browserRec.On("NewContextAsync", _ => throw new PlaywrightException("launch failed"));

        var human = Humanize.Browser(browser, new HumanConfig());

        await Assert.ThrowsAsync<PlaywrightException>(() => human.NewContextAsync());
    }

    [Fact]
    public void Browser_Original_exposes_inner()
    {
        var (browser, _) = Fake.Of<IBrowser>();
        var human = (HumanizedBrowser)Humanize.Browser(browser, new HumanConfig());
        Assert.Same(browser, human.Original);
        Assert.Same(browser, human.Inner);
    }
}
