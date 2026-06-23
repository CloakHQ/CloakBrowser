using CloakBrowser.Human;
using CloakBrowser.Wrappers;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests.Wrappers;

/// <summary>
/// Ports Python <c>TestFocusCheck</c>: <see cref="HumanizedLocator.PressAsync"/> and
/// <see cref="HumanizedLocator.ClearAsync"/> only perform the humanized focus-click when
/// the element is not already focused. The focus state is probed via
/// <c>EvaluateAsync&lt;bool&gt;("el =&gt; el === document.activeElement")</c>; we mock that
/// to return true/false and assert whether the cursor moved (i.e. whether a click ran).
/// </summary>
public class FocusCheckTests
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

    private static (IPage page, FakeProxy mouseRec, FakeProxy kbRec) BuildPage()
    {
        var (mouse, mouseRec) = Fake.Of<IMouse>();
        var (keyboard, kbRec) = Fake.Of<IKeyboard>();
        var (page, pageRec) = Fake.Of<IPage>();
        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);
        pageRec.On("ViewportSize", new PageViewportSizeResult { Width = 1280, Height = 720 });
        return (page, mouseRec, kbRec);
    }

    private static ILocator BuildLocator(bool focused)
    {
        var (locator, locRec) = Fake.Of<ILocator>();
        locRec.On("First", locator);
        locRec.On("BoundingBoxAsync", Task.FromResult<LocatorBoundingBoxResult?>(
            new LocatorBoundingBoxResult { X = 100, Y = 200, Width = 80, Height = 30 }));
        locRec.On("ScrollIntoViewIfNeededAsync", Task.CompletedTask);
        // IsFocusedAsync / IsInputAsync both go through EvaluateAsync<bool>.
        locRec.On("EvaluateAsync", Task.FromResult(focused));
        return locator;
    }

    // --- PressAsync ---------------------------------------------------------

    [Fact]
    public async Task PressAsync_skips_click_when_focused()
    {
        var (page, mouseRec, kbRec) = BuildPage();
        var human = new HumanizedLocator(BuildLocator(focused: true), new HumanCursor(page), FastConfig());

        await human.PressAsync("Enter");

        Assert.Equal(0, mouseRec.CountOf("MoveAsync"));  // cursor did not move
        Assert.Equal(0, mouseRec.CountOf("DownAsync"));  // no click
        Assert.True(kbRec.CountOf("PressAsync") >= 1, "the key was still pressed");
    }

    [Fact]
    public async Task PressAsync_clicks_when_not_focused()
    {
        var (page, mouseRec, _) = BuildPage();
        var human = new HumanizedLocator(BuildLocator(focused: false), new HumanCursor(page), FastConfig());

        await human.PressAsync("Enter");

        Assert.True(mouseRec.CountOf("MoveAsync") >= 1, "cursor moved to focus the element");
        Assert.Equal(1, mouseRec.CountOf("DownAsync"));  // humanized click happened
    }

    // --- ClearAsync ---------------------------------------------------------

    [Fact]
    public async Task ClearAsync_skips_click_when_focused()
    {
        var (page, mouseRec, kbRec) = BuildPage();
        var human = new HumanizedLocator(BuildLocator(focused: true), new HumanCursor(page), FastConfig());

        await human.ClearAsync();

        Assert.Equal(0, mouseRec.CountOf("MoveAsync"));  // no focus click
        Assert.Equal(0, mouseRec.CountOf("DownAsync"));
        // Still selects-all + Backspace through the keyboard.
        Assert.True(kbRec.CountOf("PressAsync") >= 2, "select-all + Backspace");
    }

    [Fact]
    public async Task ClearAsync_clicks_when_not_focused()
    {
        var (page, mouseRec, _) = BuildPage();
        var human = new HumanizedLocator(BuildLocator(focused: false), new HumanCursor(page), FastConfig());

        await human.ClearAsync();

        Assert.True(mouseRec.CountOf("MoveAsync") >= 1, "cursor moved to focus the element");
        Assert.Equal(1, mouseRec.CountOf("DownAsync"));
    }
}
