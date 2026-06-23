using CloakBrowser.Human;
using CloakBrowser.Wrappers;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests.Wrappers;

/// <summary>
/// Tests for the transparent <see cref="HumanizedMouse"/> / <see cref="HumanizedKeyboard"/>
/// decorators: intercepted methods run humanize logic (multiple inner calls), and the
/// escape-hatch exposes the original object.
/// </summary>
public class MouseKeyboardWrapperTests
{
    // A fast config: no idle, minimal motion steps, tiny ranges, so tests run quickly.
    private static HumanConfig FastConfig() => new()
    {
        IdleBetweenActions = false,
        MouseMinSteps = 2,
        MouseMaxSteps = 3,
        MouseBurstSize = (5, 5),
        MouseBurstPause = (0, 0),
        MouseOvershootChance = 0, // deterministic: no overshoot
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

    private static (IPage page, FakeProxy pageRec, FakeProxy mouseRec, FakeProxy kbRec) BuildPage()
    {
        var (mouse, mouseRec) = Fake.Of<IMouse>();
        var (keyboard, kbRec) = Fake.Of<IKeyboard>();
        var (page, pageRec) = Fake.Of<IPage>();
        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);
        pageRec.On("ViewportSize", new PageViewportSizeResult { Width = 1280, Height = 720 });
        return (page, pageRec, mouseRec, kbRec);
    }

    private static HumanCursor MakeCursor(IPage page)
    {
        var cursor = new HumanCursor(page);
        // Don't call InitStealthAsync (no CDP in a fake) - typing falls back to evaluate.
        return cursor;
    }

    // -----------------------------------------------------------------------
    // Interception: humanized methods produce multiple low-level inner calls.
    // -----------------------------------------------------------------------

    [Fact]
    public async Task Mouse_MoveAsync_is_humanized_into_multiple_inner_moves()
    {
        var (page, _, mouseRec, _) = BuildPage();
        var cfg = FastConfig();
        var cursor = MakeCursor(page);
        var mouse = new HumanizedMouse(page.Mouse, cursor, cfg);

        await mouse.MoveAsync(500, 400);

        // Bezier motion => more than one inner MoveAsync (the single-call API became many).
        Assert.True(mouseRec.CountOf("MoveAsync") > 1,
            $"expected humanized multi-step move, got {mouseRec.CountOf("MoveAsync")}");
    }

    [Fact]
    public async Task Mouse_ClickAsync_moves_then_presses()
    {
        var (page, _, mouseRec, _) = BuildPage();
        var mouse = new HumanizedMouse(page.Mouse, MakeCursor(page), FastConfig());

        await mouse.ClickAsync(300, 300);

        Assert.True(mouseRec.CountOf("MoveAsync") >= 1);
        Assert.Equal(1, mouseRec.CountOf("DownAsync"));
        Assert.Equal(1, mouseRec.CountOf("UpAsync"));
        // Down must come before Up (correct ordering preserved).
        int down = mouseRec.CallNames.ToList().IndexOf("DownAsync");
        int up = mouseRec.CallNames.ToList().IndexOf("UpAsync");
        Assert.True(down < up);
    }

    [Fact]
    public async Task Mouse_WheelAsync_is_chunked_into_multiple_inner_wheels()
    {
        var (page, _, mouseRec, _) = BuildPage();
        var mouse = new HumanizedMouse(page.Mouse, MakeCursor(page), FastConfig());

        await mouse.WheelAsync(0, 300);

        Assert.True(mouseRec.CountOf("WheelAsync") > 1,
            "wheel should be broken into small inertia bursts");
    }

    [Fact]
    public Task Mouse_Original_and_Inner_expose_the_unwrapped_object()
    {
        var (page, _, _, _) = BuildPage();
        var inner = page.Mouse;
        var mouse = new HumanizedMouse(inner, MakeCursor(page), FastConfig());
        Assert.Same(inner, mouse.Original);
        Assert.Same(inner, mouse.Inner);
        return Task.CompletedTask;
    }

    // -----------------------------------------------------------------------
    // Delegation: non-intercepted members forward verbatim to the inner object.
    // -----------------------------------------------------------------------

    [Fact]
    public async Task Keyboard_DownAsync_UpAsync_delegate_to_inner()
    {
        var (page, _, _, kbRec) = BuildPage();
        var kb = new HumanizedKeyboard(page.Keyboard, MakeCursor(page), FastConfig());

        await kb.DownAsync("Shift");
        await kb.UpAsync("Shift");

        Assert.Equal(1, kbRec.CountOf("DownAsync"));
        Assert.Equal(1, kbRec.CountOf("UpAsync"));
        Assert.Equal("Shift", kbRec.Last("DownAsync")!.Args[0]);
    }

    [Fact]
    public async Task Keyboard_TypeAsync_produces_per_character_inner_key_events()
    {
        var (page, _, _, kbRec) = BuildPage();
        var kb = new HumanizedKeyboard(page.Keyboard, MakeCursor(page), FastConfig());

        await kb.TypeAsync("abc");

        // Human typing presses each key down+up individually (not one inner TypeAsync).
        Assert.Equal(0, kbRec.CountOf("TypeAsync"));
        Assert.True(kbRec.CountOf("DownAsync") >= 3, "expected per-char key downs");
        Assert.True(kbRec.CountOf("UpAsync") >= 3, "expected per-char key ups");
    }

    [Fact]
    public Task Keyboard_Original_and_Inner_expose_the_unwrapped_object()
    {
        var (page, _, _, _) = BuildPage();
        var inner = page.Keyboard;
        var kb = new HumanizedKeyboard(inner, MakeCursor(page), FastConfig());
        Assert.Same(inner, kb.Original);
        Assert.Same(inner, kb.Inner);
        return Task.CompletedTask;
    }

    // -----------------------------------------------------------------------
    // Exception propagation: inner failures bubble up unchanged (not swallowed).
    // -----------------------------------------------------------------------

    [Fact]
    public async Task Mouse_inner_exception_propagates()
    {
        var (page, _, mouseRec, _) = BuildPage();
        mouseRec.On("MoveAsync", _ => throw new InvalidOperationException("boom"));
        var mouse = new HumanizedMouse(page.Mouse, MakeCursor(page), FastConfig());

        var ex = await Assert.ThrowsAsync<InvalidOperationException>(() => mouse.ClickAsync(200, 200));
        Assert.Equal("boom", ex.Message);
    }

    [Fact]
    public async Task Keyboard_inner_exception_propagates()
    {
        var (page, _, _, kbRec) = BuildPage();
        kbRec.On("DownAsync", _ => throw new PlaywrightException("kb fail"));
        var kb = new HumanizedKeyboard(page.Keyboard, MakeCursor(page), FastConfig());

        await Assert.ThrowsAsync<PlaywrightException>(() => kb.TypeAsync("a"));
    }
}
