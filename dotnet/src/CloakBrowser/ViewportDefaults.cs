using Microsoft.Playwright;

namespace CloakBrowser;

/// <summary>
/// Shared headed-launch viewport defaulting - the single source of truth behind both
/// <see cref="CloakBrowserHandle"/> and the humanize <c>HumanizedBrowser</c> wrapper, so
/// the default applies no matter which path creates the page/context (mirrors Python's
/// single <c>_default_no_viewport</c> that monkey-patches the raw browser).
///
/// On a headed launch, a page/context the caller gave no explicit viewport defaults to
/// <see cref="ViewportSize.NoViewport"/> so it tracks the real OS window - a bare emulated
/// viewport on a headed window yields <c>outerWidth &lt; innerWidth</c> (a physically
/// impossible window / bot tell). Headless keeps Playwright's default (coherent there).
/// An explicit viewport (including <see cref="ViewportSize.NoViewport"/>) is always honored.
/// </summary>
internal static class ViewportDefaults
{
    public static BrowserNewPageOptions ApplyHeadedNoViewport(BrowserNewPageOptions? options, bool headless)
    {
        if (headless) return options ?? new BrowserNewPageOptions();
        var o = options ?? new BrowserNewPageOptions();
        o.ViewportSize ??= ViewportSize.NoViewport;
        return o;
    }

    public static BrowserNewContextOptions ApplyHeadedNoViewport(BrowserNewContextOptions? options, bool headless)
    {
        if (headless) return options ?? new BrowserNewContextOptions();
        var o = options ?? new BrowserNewContextOptions();
        o.ViewportSize ??= ViewportSize.NoViewport;
        return o;
    }
}
