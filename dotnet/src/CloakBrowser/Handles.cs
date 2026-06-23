using CloakBrowser.Human;
using CloakBrowser.Wrappers;
using Microsoft.Playwright;

namespace CloakBrowser;

/// <summary>
/// A launched stealth browser. Owns the underlying Playwright instance and disposes
/// it on <see cref="CloseAsync"/>. Use <see cref="Browser"/> for the raw Playwright API.
/// </summary>
public sealed class CloakBrowserHandle : IAsyncDisposable
{
    private readonly IPlaywright _playwright;
    private readonly bool _humanize;
    private readonly HumanConfig? _humanCfg;
    private readonly IBrowser _rawBrowser;
    private readonly bool _headless;

    /// <summary>
    /// The Playwright browser. When humanize is enabled this is a transparent
    /// humanizing wrapper: every page/context it produces uses human-like mouse,
    /// keyboard, and scrolling automatically while exposing the full standard
    /// <see cref="IBrowser"/> API. Use <see cref="RawBrowser"/> for the un-wrapped
    /// browser.
    /// </summary>
    public IBrowser Browser { get; }

    /// <summary>The original, un-humanized Playwright browser (escape hatch).</summary>
    public IBrowser RawBrowser => _rawBrowser;

    /// <summary>The owning Playwright instance (used internally to transfer ownership to a context handle).</summary>
    internal IPlaywright PlaywrightInstance => _playwright;

    internal CloakBrowserHandle(IPlaywright playwright, IBrowser browser, bool humanize, HumanConfig? humanCfg,
        bool headless = true)
    {
        _playwright = playwright;
        _rawBrowser = browser;
        _humanize = humanize;
        _humanCfg = humanCfg;
        _headless = headless;
        // Wrap the whole browser so the entire object graph (contexts, pages, mice,
        // keyboards, locators, frames) is humanized transparently. The wrapper is
        // headless-aware so the headed no-viewport default also applies when pages are
        // created through the humanized browser (parity with Python's _default_no_viewport,
        // which patches the raw browser so the default holds on every path).
        Browser = humanize
            ? Wrappers.Humanize.Browser(browser, humanCfg ?? new HumanConfig(), headless)
            : browser;
    }

    /// <summary>
    /// On headed launches, default a page/context that the caller didn't give an explicit
    /// viewport to <c>NoViewport</c> so it tracks the real OS window. Delegates to the
    /// shared <see cref="ViewportDefaults"/> (the single source of truth shared with the
    /// humanize wrapper). Port of Python <c>_default_no_viewport</c>.
    /// </summary>
    private BrowserNewPageOptions ApplyDefaultNoViewport(BrowserNewPageOptions? options) =>
        ViewportDefaults.ApplyHeadedNoViewport(options, _headless);

    private BrowserNewContextOptions ApplyDefaultNoViewport(BrowserNewContextOptions? options) =>
        ViewportDefaults.ApplyHeadedNoViewport(options, _headless);

    /// <summary>
    /// Create a new browser context. On headed launches without an explicit viewport,
    /// defaults to <c>NoViewport</c> so the page tracks the real window (see
    /// <see cref="NewPageAsync"/>).
    /// </summary>
    public Task<IBrowserContext> NewContextAsync(BrowserNewContextOptions? options = null) =>
        Browser.NewContextAsync(ApplyDefaultNoViewport(options));

    /// <summary>
    /// Create a new page. When humanize is enabled the returned <see cref="IPage"/> is a
    /// transparent humanizing wrapper - your standard Playwright calls
    /// (<c>page.ClickAsync</c>, <c>page.FillAsync</c>, <c>page.Mouse.MoveAsync</c>, ...)
    /// are automatically humanized.
    /// </summary>
    public Task<IPage> NewPageAsync(BrowserNewPageOptions? options = null) =>
        Browser.NewPageAsync(ApplyDefaultNoViewport(options));

    /// <summary>
    /// Create a new page wrapped in an explicit <see cref="HumanPage"/> with this
    /// browser's humanize config. Prefer <see cref="NewPageAsync"/> for transparent
    /// humanization; this is the explicit-wrapper API kept for advanced control.
    /// </summary>
    public async Task<HumanPage> NewHumanPageAsync(BrowserNewPageOptions? options = null)
    {
        // Use the raw browser so we don't build a HumanPage over an already-wrapped page.
        var page = await _rawBrowser.NewPageAsync(ApplyDefaultNoViewport(options)).ConfigureAwait(false);
        return await HumanPage.CreateAsync(page, _humanCfg ?? new HumanConfig()).ConfigureAwait(false);
    }

    /// <summary>Whether the humanize layer is enabled for this browser.</summary>
    public bool HumanizeEnabled => _humanize;

    /// <summary>Close the browser and stop the underlying Playwright instance.</summary>
    public async Task CloseAsync()
    {
        try { await _rawBrowser.CloseAsync().ConfigureAwait(false); }
        finally { _playwright.Dispose(); }
    }

    /// <inheritdoc/>
    public async ValueTask DisposeAsync() => await CloseAsync().ConfigureAwait(false);
}

/// <summary>
/// A launched stealth browser context. Owns the underlying Playwright instance (and,
/// for non-persistent contexts, the browser) and cleans them up on <see cref="CloseAsync"/>.
/// </summary>
public sealed class CloakContextHandle : IAsyncDisposable
{
    private readonly IPlaywright _playwright;
    private readonly IBrowser? _browser; // null for persistent contexts
    private readonly bool _humanize;
    private readonly HumanConfig? _humanCfg;
    private readonly IBrowserContext _rawContext;

    /// <summary>
    /// The Playwright browser context. When humanize is enabled this is a transparent
    /// humanizing wrapper: every page it produces uses human-like input automatically
    /// while exposing the full standard <see cref="IBrowserContext"/> API. Use
    /// <see cref="RawContext"/> for the un-wrapped context.
    /// </summary>
    public IBrowserContext Context { get; }

    /// <summary>The original, un-humanized Playwright context (escape hatch).</summary>
    public IBrowserContext RawContext => _rawContext;

    internal CloakContextHandle(IPlaywright playwright, IBrowser? browser, IBrowserContext context,
        bool humanize, HumanConfig? humanCfg)
    {
        _playwright = playwright;
        _browser = browser;
        _rawContext = context;
        _humanize = humanize;
        _humanCfg = humanCfg;
        Context = humanize ? Wrappers.Humanize.Context(context, humanCfg ?? new HumanConfig()) : context;
    }

    /// <summary>
    /// Create a new page. When humanize is enabled the returned <see cref="IPage"/> is a
    /// transparent humanizing wrapper - standard Playwright calls are auto-humanized.
    /// </summary>
    public Task<IPage> NewPageAsync() => Context.NewPageAsync();

    /// <summary>
    /// Create a new page wrapped in an explicit <see cref="HumanPage"/> with this
    /// context's humanize config. Prefer <see cref="NewPageAsync"/> for transparent
    /// humanization.
    /// </summary>
    public async Task<HumanPage> NewHumanPageAsync()
    {
        var page = await _rawContext.NewPageAsync().ConfigureAwait(false);
        return await HumanPage.CreateAsync(page, _humanCfg ?? new HumanConfig()).ConfigureAwait(false);
    }

    /// <summary>Whether the humanize layer is enabled for this context.</summary>
    public bool HumanizeEnabled => _humanize;

    /// <summary>Close the context (and browser, if owned) and stop Playwright.</summary>
    public async Task CloseAsync()
    {
        try
        {
            await _rawContext.CloseAsync().ConfigureAwait(false);
            if (_browser != null)
                await _browser.CloseAsync().ConfigureAwait(false);
        }
        finally
        {
            _playwright.Dispose();
        }
    }

    /// <inheritdoc/>
    public async ValueTask DisposeAsync() => await CloseAsync().ConfigureAwait(false);
}
