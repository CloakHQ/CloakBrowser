using Microsoft.Playwright;

namespace CloakBrowser;

/// <summary>
/// Shared viewport defaulting - the single source of truth behind both
/// <see cref="CloakBrowserHandle"/> and the humanize <c>HumanizedBrowser</c> wrapper, so
/// the default applies no matter which path creates the page/context (mirrors Python's
/// single <c>_default_no_viewport</c> that monkey-patches the raw browser).
///
/// A page/context the caller gave no explicit viewport defaults to
/// <see cref="ViewportSize.NoViewport"/>: headed, it tracks the real OS window (a bare
/// emulated viewport there yields <c>outerWidth &lt; innerWidth</c>, an impossible window);
/// headless, the binary reports coherent dimensions itself. An explicit viewport
/// (including <see cref="ViewportSize.NoViewport"/>) is always honored.
/// </summary>
internal static class ViewportDefaults
{
    public static BrowserNewPageOptions ApplyNoViewport(BrowserNewPageOptions? options)
    {
        var o = options ?? new BrowserNewPageOptions();
        o.ViewportSize ??= ViewportSize.NoViewport;
        return o;
    }

    public static BrowserNewContextOptions ApplyNoViewport(BrowserNewContextOptions? options)
    {
        var o = options ?? new BrowserNewContextOptions();
        o.ViewportSize ??= ViewportSize.NoViewport;
        return o;
    }
}
