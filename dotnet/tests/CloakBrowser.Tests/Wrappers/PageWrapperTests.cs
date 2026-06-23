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

    /// <summary>Build a fake page whose Locator(...) returns an actionable fake locator.</summary>
    private static (HumanizedPage human, FakeProxy pageRec, FakeProxy mouseRec) BuildHumanizedPage()
    {
        var (mouse, mouseRec) = Fake.Of<IMouse>();
        var (keyboard, _) = Fake.Of<IKeyboard>();
        var (page, pageRec) = Fake.Of<IPage>();

        var (locator, locRec) = Fake.Of<ILocator>();
        locRec.On("First", locator);
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
