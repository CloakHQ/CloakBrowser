using CloakBrowser;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests;

/// <summary>
/// Window-geometry / no_viewport behavior - port of upstream 50bf14b tests
/// (Python tests/test_launch_context.py + test_persistent_context.py, JS
/// js/tests/launch.test.ts + puppeteer.test.ts).
///
/// Headed launches must NOT layer an emulated viewport on top of the real
/// browser window: CDP viewport emulation forces outerWidth &lt; innerWidth, a
/// physically impossible window (= bot tell). Headless also defaults to no
/// viewport: the binary reports coherent dimensions itself.
/// </summary>
public class ViewportTests
{
    // ViewportSize uses reference equality, so compare by the sentinel value that
    // Playwright's ViewportSize.NoViewport carries ({ Width = -1, Height = -1 }).
    private static bool IsNoViewport(ViewportSize? vp) =>
        vp != null && vp.Width == -1 && vp.Height == -1;

    // -----------------------------------------------------------------------
    // ResolveContextViewport - the headless-aware viewport selector used by
    // launch_context / launch_persistent_context.
    // -----------------------------------------------------------------------

    [Fact]
    public void Headless_unset_viewport_uses_no_viewport()
    {
        // Headless reports coherent dimensions natively: no emulated viewport either.
        var vp = CloakLauncher.ResolveContextViewport(new LaunchContextOptions { Headless = true });
        Assert.True(IsNoViewport(vp));
    }

    [Fact]
    public void Headed_unset_viewport_uses_no_viewport()
    {
        // The core fix: headed + no explicit viewport => track the real window.
        var vp = CloakLauncher.ResolveContextViewport(new LaunchContextOptions { Headless = false });
        Assert.True(IsNoViewport(vp));
    }

    [Fact]
    public void Explicit_viewport_honored_when_headed()
    {
        var vp = CloakLauncher.ResolveContextViewport(new LaunchContextOptions
        {
            Headless = false,
            Viewport = (1280, 720),
        });
        Assert.NotNull(vp);
        Assert.Equal(1280, vp!.Width);
        Assert.Equal(720, vp.Height);
    }

    [Fact]
    public void Explicit_viewport_honored_when_headless()
    {
        var vp = CloakLauncher.ResolveContextViewport(new LaunchContextOptions
        {
            Headless = true,
            Viewport = (800, 600),
        });
        Assert.NotNull(vp);
        Assert.Equal(800, vp!.Width);
        Assert.Equal(600, vp.Height);
    }

    [Fact]
    public void Explicit_no_viewport_honored_when_headless()
    {
        // NoViewport always wins, even headless (caller opted out of emulation).
        var vp = CloakLauncher.ResolveContextViewport(new LaunchContextOptions
        {
            Headless = true,
            NoViewport = true,
        });
        Assert.True(IsNoViewport(vp));
    }

    [Fact]
    public void NoViewport_takes_precedence_over_viewport()
    {
        // Explicit NoViewport beats an explicit viewport (matches Python's
        // _drop_conflicting_viewport: no_viewport wins).
        var vp = CloakLauncher.ResolveContextViewport(new LaunchContextOptions
        {
            Headless = true,
            NoViewport = true,
            Viewport = (1920, 1080),
        });
        Assert.True(IsNoViewport(vp));
    }

    // -----------------------------------------------------------------------
    // ViewportDefaults.ApplyNoViewport - the shared default applied on EVERY
    // page/context creation path (the raw handle AND the humanize wrapper),
    // mirroring Python's _default_no_viewport which patches the browser so the
    // default holds regardless of which path creates the page.
    // -----------------------------------------------------------------------

    [Fact]
    public void Default_page_unset_becomes_no_viewport()
    {
        var o = ViewportDefaults.ApplyNoViewport((BrowserNewPageOptions?)null);
        Assert.True(IsNoViewport(o.ViewportSize));
    }

    [Fact]
    public void Default_context_unset_becomes_no_viewport()
    {
        var o = ViewportDefaults.ApplyNoViewport((BrowserNewContextOptions?)null);
        Assert.True(IsNoViewport(o.ViewportSize));
    }

    [Fact]
    public void Default_explicit_viewport_honored()
    {
        var input = new BrowserNewPageOptions { ViewportSize = new ViewportSize { Width = 1024, Height = 768 } };
        var o = ViewportDefaults.ApplyNoViewport(input);
        Assert.Equal(1024, o.ViewportSize!.Width);
        Assert.Equal(768, o.ViewportSize.Height);
    }

    [Fact]
    public void Default_explicit_no_viewport_honored()
    {
        var input = new BrowserNewContextOptions { ViewportSize = ViewportSize.NoViewport };
        var o = ViewportDefaults.ApplyNoViewport(input);
        Assert.True(IsNoViewport(o.ViewportSize));
    }
}
