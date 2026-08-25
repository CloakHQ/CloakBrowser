using System.Reflection;
using System.Text.Json;
using CloakBrowser.Human;
using CloakBrowser.Wrappers;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests.Wrappers;

/// <summary>
/// Tests for the transparent <see cref="HumanizedPage"/> decorator: nested objects
/// (Mouse/Keyboard/Locator/Frame) are returned wrapped, selector actions run through
/// the humanize engine, non-interaction members delegate, and the escape hatch works.
/// </summary>
public class PageWrapperTests
{
    private static HumanConfig FastConfig() => new()
    {
        IdleBetweenActions = false,
        MouseMinSteps = 2,
        MouseMaxSteps = 3,
        MouseBurstPause = (0, 0),
        MouseOvershootChance = 0,
        ClickAimDelayButton = (0, 0),
        ClickHoldButton = (0, 0),
        ClickAimDelayInput = (0, 0),
        ClickHoldInput = (0, 0),
        TypingDelay = 0,
        TypingDelaySpread = 0,
        TypingPauseChance = 0,
        MistypeChance = 0,
        ShiftDownDelay = (0, 0),
        ShiftUpDelay = (0, 0),
        KeyHold = (0, 0),
        InitialCursorX = (100, 100),
        InitialCursorY = (100, 100),
    };

    private static IsolatedWorld BuildFakeWorld(IPage page)
    {
        var (cdp, cdpRec) = Fake.Of<ICDPSession>();
        cdpRec.On("SendAsync", args =>
        {
            string method = (string)args[0]!;
            if (method != "Runtime.evaluate")
                return Task.FromResult<JsonElement?>(null);

            var parameters = (IDictionary<string, object>)args[1]!;
            string expression = (string)parameters["expression"];
            object value = expression == StealthDom.ViewportJs
                ? new { width = 1280, height = 720 }
                : new
                {
                    v = 2, r = "ok", targetId = 1, gen = 3, attached = true,
                    visible = true, enabled = true, editable = true,
                    isInput = false, focused = false, @checked = false, hit = true,
                    box = new { x = 100, y = 200, width = 80, height = 30 },
                };
            return Task.FromResult<JsonElement?>(JsonSerializer.SerializeToElement(new
            {
                result = new { value },
            }));
        });

        var world = new IsolatedWorld(page);
        typeof(IsolatedWorld).GetField("_cdp", BindingFlags.NonPublic | BindingFlags.Instance)!
            .SetValue(world, cdp);
        typeof(IsolatedWorld).GetField("_contextId", BindingFlags.NonPublic | BindingFlags.Instance)!
            .SetValue(world, 42);
        return world;
    }

    private static void InjectWorld(HumanizedPage human, HumanCursor cursor, IsolatedWorld world)
    {
        typeof(HumanCursor).GetField("_stealth", BindingFlags.NonPublic | BindingFlags.Instance)!
            .SetValue(cursor, world);
        typeof(HumanCursor).GetField("_stealthInitialized", BindingFlags.NonPublic | BindingFlags.Instance)!
            .SetValue(cursor, true);

        var humanPage = (HumanPage)typeof(HumanizedPage)
            .GetField("_human", BindingFlags.NonPublic | BindingFlags.Instance)!
            .GetValue(human)!;
        typeof(HumanPage).GetField("_stealth", BindingFlags.NonPublic | BindingFlags.Instance)!
            .SetValue(humanPage, world);
        typeof(HumanPage).GetField("_stealthInitialized", BindingFlags.NonPublic | BindingFlags.Instance)!
            .SetValue(humanPage, true);
    }

    /// <summary>Build a fake page whose isolated world returns an actionable target.</summary>
    private static (HumanizedPage human, FakeProxy pageRec, FakeProxy mouseRec) BuildHumanizedPage()
    {
        var (mouse, mouseRec) = Fake.Of<IMouse>();
        var (keyboard, _) = Fake.Of<IKeyboard>();
        var (page, pageRec) = Fake.Of<IPage>();

        var (locator, locRec) = Fake.Of<ILocator>();
        locRec.On("First", locator);
        locRec.On("Last", locator);
        locRec.On("Nth", locator);
        locRec.On("BoundingBoxAsync", Task.FromResult<LocatorBoundingBoxResult?>(
            new LocatorBoundingBoxResult { X = 100, Y = 200, Width = 80, Height = 30 }));
        locRec.On("IsVisibleAsync", Task.FromResult(true));
        locRec.On("IsEnabledAsync", Task.FromResult(true));
        locRec.On("IsEditableAsync", Task.FromResult(true));
        locRec.On("WaitForAsync", Task.CompletedTask);
        locRec.On("EvaluateAsync", Task.FromResult(
            System.Text.Json.JsonSerializer.SerializeToElement(new { hit = true })));

        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);
        pageRec.On("ViewportSize", new PageViewportSizeResult { Width = 1280, Height = 720 });
        pageRec.On("Locator", locator);
        pageRec.On("EvaluateAsync", Task.FromResult(
            System.Text.Json.JsonSerializer.SerializeToElement(false)));

        var cursor = new HumanCursor(page);
        var human = new HumanizedPage(page, cursor, FastConfig());
        InjectWorld(human, cursor, BuildFakeWorld(page));
        return (human, pageRec, mouseRec);
    }

    // -----------------------------------------------------------------------
    // Nested objects are wrapped
    // -----------------------------------------------------------------------

    [Fact]
    public void Mouse_and_Keyboard_are_humanized_wrappers()
    {
        var (human, _, _) = BuildHumanizedPage();
        Assert.IsType<HumanizedMouse>(human.Mouse);
        Assert.IsType<HumanizedKeyboard>(human.Keyboard);
    }

    [Fact]
    public void Locator_and_GetBy_return_humanized_locators()
    {
        var (human, _, _) = BuildHumanizedPage();
        Assert.IsType<HumanizedLocator>(human.Locator("#a"));
        Assert.IsType<HumanizedLocator>(human.GetByTestId("t"));
        Assert.IsType<HumanizedLocator>(human.GetByText("x"));
        Assert.IsType<HumanizedLocator>(human.GetByRole(AriaRole.Button));
    }

    [Fact]
    public void Locator_threads_selector_for_isolated_world_reads()
    {
        // Regression guard: page.Locator(sel) must carry the selector into the
        // HumanizedLocator so its pre-click reads can resolve in the isolated world.
        // GetBy*/chained locators have no CSS selector -> null -> Playwright fallback.
        var (human, _, _) = BuildHumanizedPage();
        var loc = Assert.IsType<HumanizedLocator>(human.Locator("button:has-text('X')"));
        Assert.Equal("button:has-text('X')", loc.Selector);
        Assert.Equal("button:has-text('X') >> nth=0", Assert.IsType<HumanizedLocator>(loc.First).Selector);
        Assert.Equal("button:has-text('X') >> nth=-1", Assert.IsType<HumanizedLocator>(loc.Last).Selector);
        Assert.Equal("button:has-text('X') >> nth=3", Assert.IsType<HumanizedLocator>(loc.Nth(3)).Selector);
        Assert.Null(Assert.IsType<HumanizedLocator>(loc.First.First).Selector);
        Assert.Null(Assert.IsType<HumanizedLocator>(loc.Nth(1).Nth(0)).Selector);

        var withOptions = Assert.IsType<HumanizedLocator>(human.Locator(
            "button", new PageLocatorOptions { HasTextString = "X" }));
        Assert.Null(withOptions.Selector);

        var byRole = Assert.IsType<HumanizedLocator>(human.GetByRole(AriaRole.Button));
        Assert.Null(byRole.Selector);
    }

    [Fact]
    public void MainFrame_and_Frames_return_humanized_frames()
    {
        var (mouse, _) = Fake.Of<IMouse>();
        var (keyboard, _) = Fake.Of<IKeyboard>();
        var (frame, _) = Fake.Of<IFrame>();
        var (page, pageRec) = Fake.Of<IPage>();
        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);
        pageRec.On("MainFrame", frame);
        pageRec.On("Frames", new List<IFrame> { frame });

        var human = new HumanizedPage(page, new HumanCursor(page), FastConfig());

        Assert.IsType<HumanizedFrame>(human.MainFrame);
        Assert.All(human.Frames, f => Assert.IsType<HumanizedFrame>(f));
    }

    [Theory]
    [InlineData("FrameAttached")]
    [InlineData("FrameDetached")]
    [InlineData("FrameNavigated")]
    public void Frame_events_wrap_payload_and_unsubscribe_exact_delegate(string eventName)
    {
        var (mouse, _) = Fake.Of<IMouse>();
        var (keyboard, _) = Fake.Of<IKeyboard>();
        var (rawFrame, _) = Fake.Of<IFrame>();
        var (page, pageRec) = Fake.Of<IPage>();
        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);

        var human = new HumanizedPage(page, new HumanCursor(page), FastConfig());
        IFrame? observedFrame = null;
        object? observedSender = null;
        EventHandler<IFrame> handler = (sender, frame) =>
        {
            observedSender = sender;
            observedFrame = frame;
        };

        switch (eventName)
        {
            case "FrameAttached": human.FrameAttached += handler; break;
            case "FrameDetached": human.FrameDetached += handler; break;
            case "FrameNavigated": human.FrameNavigated += handler; break;
        }

        var innerHandler = Assert.IsType<EventHandler<IFrame>>(
            pageRec.Last($"add_{eventName}")!.Args[0]);
        innerHandler(page, rawFrame);

        Assert.Same(human, observedSender);
        Assert.IsType<HumanizedFrame>(observedFrame);

        switch (eventName)
        {
            case "FrameAttached": human.FrameAttached -= handler; break;
            case "FrameDetached": human.FrameDetached -= handler; break;
            case "FrameNavigated": human.FrameNavigated -= handler; break;
        }

        var removedHandler = Assert.IsType<EventHandler<IFrame>>(
            pageRec.Last($"remove_{eventName}")!.Args[0]);
        Assert.Same(innerHandler, removedHandler);
    }

    // -----------------------------------------------------------------------
    // Selector action interception drives the humanize engine.
    // -----------------------------------------------------------------------

    [Fact]
    public async Task ClickAsync_selector_runs_humanized_motion()
    {
        var (human, _, mouseRec) = BuildHumanizedPage();

        await human.ClickAsync("#submit");

        Assert.True(mouseRec.CountOf("MoveAsync") >= 1);
        Assert.Equal(1, mouseRec.CountOf("DownAsync"));
        Assert.Equal(1, mouseRec.CountOf("UpAsync"));
    }

    [Fact]
    public async Task PressAsync_selector_forwards_delay()
    {
        var (human, _, _) = BuildHumanizedPage();
        var keyboard = (FakeProxy)(object)human.Original.Keyboard;

        await human.PressAsync("#field", "Control+V", new PagePressOptions { Delay = 300 });

        var options = Assert.IsType<KeyboardPressOptions>(keyboard.Last("PressAsync")!.Args[1]);
        Assert.Equal(300, options.Delay);
    }

    // -----------------------------------------------------------------------
    // Delegation: non-interaction members forward to the inner page.
    // -----------------------------------------------------------------------

    [Fact]
    public async Task TitleAsync_and_Url_delegate_to_inner()
    {
        var (mouse, _) = Fake.Of<IMouse>();
        var (keyboard, _) = Fake.Of<IKeyboard>();
        var (page, pageRec) = Fake.Of<IPage>();
        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);
        pageRec.On("TitleAsync", Task.FromResult("Example Domain"));
        pageRec.On("Url", "https://example.com/");

        var human = new HumanizedPage(page, new HumanCursor(page), FastConfig());

        Assert.Equal("Example Domain", await human.TitleAsync());
        Assert.Equal("https://example.com/", human.Url);
        Assert.True(pageRec.WasCalled("TitleAsync"));
    }

    [Fact]
    public async Task GotoAsync_delegates_and_returns_inner_response()
    {
        var (mouse, _) = Fake.Of<IMouse>();
        var (keyboard, _) = Fake.Of<IKeyboard>();
        var (response, _) = Fake.Of<IResponse>();
        var (page, pageRec) = Fake.Of<IPage>();
        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);
        pageRec.On("GotoAsync", Task.FromResult<IResponse?>(response));

        var human = new HumanizedPage(page, new HumanCursor(page), FastConfig());

        var result = await human.GotoAsync("https://example.com");
        Assert.Same(response, result);
        Assert.True(pageRec.WasCalled("GotoAsync"));
    }

    // -----------------------------------------------------------------------
    // Escape hatch
    // -----------------------------------------------------------------------

    [Fact]
    public void Original_and_Inner_expose_unwrapped_page()
    {
        var (mouse, _) = Fake.Of<IMouse>();
        var (keyboard, _) = Fake.Of<IKeyboard>();
        var (page, pageRec) = Fake.Of<IPage>();
        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);
        var human = new HumanizedPage(page, new HumanCursor(page), FastConfig());
        Assert.Same(page, human.Original);
        Assert.Same(page, human.Inner);
    }

    // -----------------------------------------------------------------------
    // Exception propagation through a delegated member.
    // -----------------------------------------------------------------------

    [Fact]
    public async Task Delegated_member_exception_propagates()
    {
        var (mouse, _) = Fake.Of<IMouse>();
        var (keyboard, _) = Fake.Of<IKeyboard>();
        var (page, pageRec) = Fake.Of<IPage>();
        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);
        pageRec.On("ContentAsync", _ => throw new PlaywrightException("closed"));

        var human = new HumanizedPage(page, new HumanCursor(page), FastConfig());

        await Assert.ThrowsAsync<PlaywrightException>(() => human.ContentAsync());
    }
}
