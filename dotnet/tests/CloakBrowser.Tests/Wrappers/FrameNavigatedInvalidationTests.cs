using System.Reflection;
using CloakBrowser.Human;
using CloakBrowser.Wrappers;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests.Wrappers;

/// <summary>
/// Regression #507: a click/form/history navigation (not just page.goto) must
/// invalidate the isolated world. bfcache keeps the previous document's context
/// alive, so a stale eval keeps succeeding against the old document and
/// fill()/click() actionability reads fail. Both page wrappers must subscribe to
/// <see cref="IPage.FrameNavigated"/> and invalidate on MAIN-frame navigations only.
/// </summary>
public class FrameNavigatedInvalidationTests
{
    private static HumanConfig FastConfig() => new()
    {
        IdleBetweenActions = false,
        InitialCursorX = (100, 100),
        InitialCursorY = (100, 100),
    };

    /// <summary>Give the world a non-null cached context id so Invalidate() is observable.</summary>
    private static void PrimeContextId(IsolatedWorld world, int id) =>
        typeof(IsolatedWorld).GetField("_contextId", BindingFlags.NonPublic | BindingFlags.Instance)!
            .SetValue(world, id);

    private static int? ReadContextId(IsolatedWorld world) =>
        (int?)typeof(IsolatedWorld).GetField("_contextId", BindingFlags.NonPublic | BindingFlags.Instance)!
            .GetValue(world);

    [Fact]
    public void HumanizedPage_invalidates_world_on_main_frame_nav_only()
    {
        var (mouse, _) = Fake.Of<IMouse>();
        var (keyboard, _) = Fake.Of<IKeyboard>();
        var (page, pageRec) = Fake.Of<IPage>();
        var (mainFrame, _) = Fake.Of<IFrame>();
        var (otherFrame, _) = Fake.Of<IFrame>();

        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);
        pageRec.On("MainFrame", mainFrame);

        EventHandler<IFrame>? handler = null;
        pageRec.On("add_FrameNavigated", args => { handler = (EventHandler<IFrame>)args[0]!; return null; });

        var cursor = new HumanCursor(page);
        // Inject a real isolated world with a primed context id so invalidation is visible.
        var world = new IsolatedWorld(page);
        PrimeContextId(world, 999);
        typeof(HumanCursor).GetField("_stealth", BindingFlags.NonPublic | BindingFlags.Instance)!
            .SetValue(cursor, world);

        _ = new HumanizedPage(page, cursor, FastConfig());

        Assert.NotNull(handler); // construction subscribed to FrameNavigated

        // subframe navigation -> world stays bound
        handler!(page, otherFrame);
        Assert.Equal(999, ReadContextId(world));

        // main-frame navigation -> world invalidated
        handler!(page, mainFrame);
        Assert.Null(ReadContextId(world));
    }

    [Fact]
    public void HumanPage_invalidates_world_on_main_frame_nav_only()
    {
        var (mouse, _) = Fake.Of<IMouse>();
        var (keyboard, _) = Fake.Of<IKeyboard>();
        var (page, pageRec) = Fake.Of<IPage>();
        var (mainFrame, _) = Fake.Of<IFrame>();
        var (otherFrame, _) = Fake.Of<IFrame>();

        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);
        pageRec.On("MainFrame", mainFrame);

        EventHandler<IFrame>? handler = null;
        pageRec.On("add_FrameNavigated", args => { handler = (EventHandler<IFrame>)args[0]!; return null; });

        var human = new HumanPage(page, FastConfig());

        Assert.NotNull(handler);

        var world = new IsolatedWorld(page);
        PrimeContextId(world, 777);
        typeof(HumanPage).GetField("_stealth", BindingFlags.NonPublic | BindingFlags.Instance)!
            .SetValue(human, world);

        handler!(page, otherFrame);
        Assert.Equal(777, ReadContextId(world));

        handler!(page, mainFrame);
        Assert.Null(ReadContextId(world));
    }
}
