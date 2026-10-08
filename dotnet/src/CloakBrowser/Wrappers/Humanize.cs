using System.Collections.Generic;
using System.Linq;
using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Entry points and helpers for the transparent humanize layer.
///
/// The whole point of these wrappers is that user code keeps using the standard
/// Playwright API - <c>page.ClickAsync(...)</c>, <c>page.Locator(...).FillAsync(...)</c>,
/// <c>page.Mouse.MoveAsync(...)</c> - and the interaction methods are automatically
/// routed through the human-like engine. Non-interaction members are forwarded
/// verbatim by the Roslyn source generator, and every object that can perform an
/// interaction (mouse, keyboard, locators, frames, child pages) is returned already
/// wrapped so there are no "raw" leaks.
/// </summary>
public static class Humanize
{
    /// <summary>
    /// Wrap a raw Playwright <see cref="IPage"/> so that all interaction methods are
    /// humanized. Returns a fully-wrapping <see cref="IPage"/> - assign it to an
    /// <c>IPage</c> variable and use the standard API.
    /// </summary>
    public static async Task<IPage> PageAsync(IPage page, HumanConfig? config = null)
    {
        if (page is HumanizedPage) return page; // already wrapped
        var cfg = config ?? new HumanConfig();
        var cursor = new HumanCursor(page);
        await cursor.InitStealthAsync().ConfigureAwait(false);
        await cursor.EnsureInitializedAsync(cfg).ConfigureAwait(false);
        return new HumanizedPage(page, cursor, cfg);
    }

    /// <summary>
    /// Wrap a raw Playwright <see cref="IBrowserContext"/> so every page it produces
    /// (and already contains) is humanized.
    /// </summary>
    public static IBrowserContext Context(IBrowserContext context, HumanConfig? config = null)
    {
        if (context is HumanizedBrowserContext) return context;
        // Memoize per raw context so page.Context returns a stable instance (Playwright's
        // own context is a singleton); a fresh wrapper each access would break reference
        // identity and dictionary-key use.
        return ContextCache.GetValue(context, key => new HumanizedBrowserContext(key, config ?? new HumanConfig()));
    }

    /// <summary>One humanized wrapper per raw context, so identity stays stable across accesses.</summary>
    private static readonly System.Runtime.CompilerServices.ConditionalWeakTable<IBrowserContext, HumanizedBrowserContext> ContextCache = new();

    /// <summary>
    /// Wrap a raw Playwright <see cref="IBrowser"/> so every context/page it produces
    /// is humanized.
    /// </summary>
    public static IBrowser Browser(
        IBrowser browser, HumanConfig? config = null, bool headless = true, bool headlessNoViewport = false)
    {
        if (browser is HumanizedBrowser) return browser;
        return new HumanizedBrowser(browser, config ?? new HumanConfig(), headless, headlessNoViewport);
    }

    /// <summary>
    /// Recover the raw Playwright <see cref="IPage"/> behind any CloakBrowser wrapper
    /// (humanize decorator and/or license-guard proxy). Pass the result to Playwright APIs
    /// that reject wrapped handles, e.g. <c>context.NewCDPSessionAsync(Humanize.Unwrap(page))</c>.
    /// </summary>
    public static IPage Unwrap(IPage page) => (IPage)LicenseGuard.Unwrap(page);

    /// <summary>Recover the raw Playwright <see cref="IFrame"/> behind any CloakBrowser wrapper.</summary>
    public static IFrame Unwrap(IFrame frame) => (IFrame)LicenseGuard.Unwrap(frame);

    /// <summary>Recover the raw Playwright <see cref="IBrowserContext"/> behind any CloakBrowser wrapper.</summary>
    public static IBrowserContext Unwrap(IBrowserContext context) => (IBrowserContext)LicenseGuard.Unwrap(context);

    /// <summary>Recover the raw Playwright <see cref="IElementHandle"/> behind any CloakBrowser wrapper.</summary>
    public static IElementHandle Unwrap(IElementHandle handle) => (IElementHandle)LicenseGuard.Unwrap(handle);

    /// <summary>Recover the raw Playwright <see cref="ILocator"/> behind a CloakBrowser wrapper
    /// (for APIs that down-cast their locator arg, e.g. <c>page.AddLocatorHandlerAsync</c>).</summary>
    public static ILocator Unwrap(ILocator locator) => (ILocator)LicenseGuard.Unwrap(locator);

    // -----------------------------------------------------------------------
    // Internal re-wrap helpers (shared by the wrappers).
    // -----------------------------------------------------------------------

    internal static ILocator WrapLocator(ILocator locator, HumanCursor cursor, HumanConfig cfg, string? selector = null) =>
        locator is HumanizedLocator ? locator : new HumanizedLocator(locator, cursor, cfg, selector);

    internal static IFrameLocator WrapFrameLocator(IFrameLocator frameLocator, HumanCursor cursor, HumanConfig cfg) =>
        frameLocator is HumanizedFrameLocator ? frameLocator : new HumanizedFrameLocator(frameLocator, cursor, cfg);

    internal static IFrame WrapFrame(IFrame frame, HumanCursor cursor, HumanConfig cfg) =>
        frame is HumanizedFrame ? frame : new HumanizedFrame(frame, cursor, cfg);

    internal static IElementHandle WrapElementHandle(IElementHandle handle, HumanCursor cursor, HumanConfig cfg) =>
        handle is HumanizedElementHandle ? handle : new HumanizedElementHandle(handle, cursor, cfg);

    internal static IReadOnlyList<IFrame> WrapFrames(IReadOnlyList<IFrame> frames, HumanCursor cursor, HumanConfig cfg) =>
        frames.Select(f => WrapFrame(f, cursor, cfg)).ToList();

    internal static IReadOnlyList<IElementHandle> WrapHandles(IReadOnlyList<IElementHandle> handles, HumanCursor cursor, HumanConfig cfg) =>
        handles.Select(h => WrapElementHandle(h, cursor, cfg)).ToList();

    /// <summary>Per-page cursor cache so pages from a context/browser share state across re-wraps.</summary>
    private static readonly System.Runtime.CompilerServices.ConditionalWeakTable<IPage, HumanCursor> CursorCache = new();

    /// <summary>The shared humanize state of an already-humanized raw page, if any.</summary>
    internal static bool TryGetCursor(IPage page, out HumanCursor cursor) =>
        CursorCache.TryGetValue(page, out cursor!);

    internal static async Task<IPage> WrapPageAsync(IPage page, HumanConfig cfg)
    {
        if (page is HumanizedPage) return page;
        if (CursorCache.TryGetValue(page, out var existing))
            return new HumanizedPage(page, existing, cfg);

        var cursor = new HumanCursor(page);
        await cursor.InitStealthAsync().ConfigureAwait(false);
        await cursor.EnsureInitializedAsync(cfg).ConfigureAwait(false);
        CursorCache.Add(page, cursor);
        return new HumanizedPage(page, cursor, cfg);
    }

    internal static IReadOnlyList<IPage> WrapPages(IReadOnlyList<IPage> pages, HumanConfig cfg) =>
        pages.Select(p =>
        {
            if (p is HumanizedPage) return p;
            var cursor = CursorCache.GetValue(p, key => new HumanCursor(key));
            return (IPage)new HumanizedPage(p, cursor, cfg);
        }).ToList();
}
