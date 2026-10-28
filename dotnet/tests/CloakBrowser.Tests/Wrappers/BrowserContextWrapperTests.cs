using CloakBrowser;
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

    // -----------------------------------------------------------------------
    // NewCDPSessionAsync: the page/frame argument must reach Playwright unwrapped.
    // Playwright down-casts it to its concrete Page/Frame (reads .Guid), which throws
    // NullReferenceException on any wrapper. Regression for the .NET 0.5.4 report.
    // -----------------------------------------------------------------------

    [Fact]
    public async Task Unwrap_peels_guard_proxy_and_humanize_off_a_page()
    {
        var raw = MakeFakePage();
        var humanized = await Humanize.PageAsync(raw, new HumanConfig());
        var denialPath = License.MintDenialFile()!;
        var guarded = (IPage)LicenseGuard.Wrap(humanized, denialPath);

        Assert.NotSame(raw, guarded);
        Assert.Same(raw, LicenseGuard.Unwrap(guarded)); // internal peeler
        Assert.Same(raw, Humanize.Unwrap(guarded));     // public escape hatch
    }

    [Fact]
    public async Task Guarded_context_forwards_unwrapped_page_to_NewCDPSession()
    {
        var raw = MakeFakePage();
        var humanized = await Humanize.PageAsync(raw, new HumanConfig());
        var denialPath = License.MintDenialFile()!;
        var guardedPage = (IPage)LicenseGuard.Wrap(humanized, denialPath);

        var (cdp, _) = Fake.Of<ICDPSession>();
        var (ctx, ctxRec) = Fake.Of<IBrowserContext>();
        ctxRec.On("NewCDPSessionAsync", _ => Task.FromResult(cdp));
        var guardedCtx = (IBrowserContext)LicenseGuard.Wrap(ctx, denialPath);

        await guardedCtx.NewCDPSessionAsync(guardedPage);

        // The inner Playwright context must receive the RAW page, not a wrapper.
        Assert.Same(raw, ctxRec.Last("NewCDPSessionAsync")!.Args[0]);
    }

    [Fact]
    public async Task Humanized_context_unwraps_page_for_NewCDPSession()
    {
        var raw = MakeFakePage();
        var humanized = await Humanize.PageAsync(raw, new HumanConfig());

        var (cdp, _) = Fake.Of<ICDPSession>();
        var (ctx, ctxRec) = Fake.Of<IBrowserContext>();
        ctxRec.On("NewCDPSessionAsync", _ => Task.FromResult(cdp));
        var humanCtx = Humanize.Context(ctx, new HumanConfig());

        await humanCtx.NewCDPSessionAsync(humanized);

        Assert.Same(raw, ctxRec.Last("NewCDPSessionAsync")!.Args[0]);
    }

    [Fact]
    public async Task HumanizedPage_Context_stays_humanized()
    {
        var (mouse, _) = Fake.Of<IMouse>();
        var (keyboard, _) = Fake.Of<IKeyboard>();
        var (page, pageRec) = Fake.Of<IPage>();
        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);
        pageRec.On("ViewportSize", new PageViewportSizeResult { Width = 800, Height = 600 });
        var (rawCtx, _) = Fake.Of<IBrowserContext>();
        pageRec.On("Context", rawCtx);

        var humanized = await Humanize.PageAsync(page, new HumanConfig());

        // page.Context must not leak the raw context (else page.Context.NewPageAsync()
        // silently returns an un-humanized page).
        Assert.IsType<HumanizedBrowserContext>(humanized.Context);

        // ...and it must be the SAME instance across accesses (identity parity with
        // Playwright's singleton context; a fresh wrapper each call breaks == / dict keys).
        Assert.Same(humanized.Context, humanized.Context);
    }

    [Fact]
    public void Unwrap_recovers_raw_context_through_guard_and_humanize()
    {
        var (rawCtx, _) = Fake.Of<IBrowserContext>();
        var humanized = Humanize.Context(rawCtx, new HumanConfig());
        var denialPath = License.MintDenialFile()!;
        var guarded = (IBrowserContext)LicenseGuard.Wrap(humanized, denialPath);

        Assert.NotSame(rawCtx, guarded);
        Assert.Same(rawCtx, Humanize.Unwrap(guarded)); // peels guard proxy + humanize decorator
    }

    [Fact]
    public async Task Guarded_page_Context_is_stable_across_accesses()
    {
        var raw = MakeFakePage();
        var (rawCtx, _) = Fake.Of<IBrowserContext>();
        ((FakeProxy)(object)raw).On("Context", rawCtx);
        var humanized = await Humanize.PageAsync(raw, new HumanConfig());
        var denialPath = License.MintDenialFile()!;
        var guardedPage = (IPage)LicenseGuard.Wrap(humanized, denialPath);

        Assert.Same(guardedPage.Context, guardedPage.Context);
    }
}
