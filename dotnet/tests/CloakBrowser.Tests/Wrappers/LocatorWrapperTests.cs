using CloakBrowser.Human;
using CloakBrowser.Wrappers;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests.Wrappers;

/// <summary>
/// Tests for the transparent <see cref="HumanizedLocator"/> decorator: humanized
/// actions, nested locator re-wrapping (so chains stay humanized), correct delegation
/// of non-interaction members, and exception/cancellation propagation.
/// </summary>
public class LocatorWrapperTests
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

    private static (ILocator locator, FakeProxy locRec) BuildLocator(
        LocatorBoundingBoxResult? box = null, bool evaluateResult = false)
    {
        var (locator, locRec) = Fake.Of<ILocator>();
        // .First returns itself so motion code resolving First works.
        locRec.On("First", locator);
        locRec.On("BoundingBoxAsync", Task.FromResult<LocatorBoundingBoxResult?>(
            box ?? new LocatorBoundingBoxResult { X = 100, Y = 200, Width = 80, Height = 30 }));
        locRec.On("ScrollIntoViewIfNeededAsync", Task.CompletedTask);
        // EvaluateAsync<bool> backs both IsInput and IsFocused checks. The wrapper
        // awaits a Task<bool>, so the handler must return a real Task<bool>.
        locRec.On("EvaluateAsync", Task.FromResult(evaluateResult));
        return (locator, locRec);
    }

    // -----------------------------------------------------------------------
    // Interception
    // -----------------------------------------------------------------------

    [Fact]
    public async Task ClickAsync_runs_humanized_motion_and_press()
    {
        var (page, mouseRec, _) = BuildPage();
        var (locator, _) = BuildLocator();
        var cursor = new HumanCursor(page);
        var human = new HumanizedLocator(locator, cursor, FastConfig());

        await human.ClickAsync();

        Assert.True(mouseRec.CountOf("MoveAsync") >= 1, "should move along a curve");
        Assert.Equal(1, mouseRec.CountOf("DownAsync"));
        Assert.Equal(1, mouseRec.CountOf("UpAsync"));
    }

    [Fact]
    public async Task FillAsync_clears_then_types_via_keyboard()
    {
        var (page, _, kbRec) = BuildPage();
        var (locator, _) = BuildLocator();
        var human = new HumanizedLocator(locator, new HumanCursor(page), FastConfig());

        await human.FillAsync("hi");

        // Select-all + Backspace + per-char typing all go through the page keyboard.
        Assert.True(kbRec.CountOf("PressAsync") >= 2, "select-all + backspace");
        Assert.True(kbRec.CountOf("DownAsync") >= 2, "typed characters");
    }

    [Fact]
    public async Task SelectOptionAsync_runs_humanized_hover_then_delegates()
    {
        var (page, mouseRec, _) = BuildPage();
        var (locator, locRec) = BuildLocator();
        IReadOnlyList<string> selected = new[] { "opt1" };
        locRec.On("SelectOptionAsync", Task.FromResult(selected));
        var human = new HumanizedLocator(locator, new HumanCursor(page), FastConfig());

        var result = await human.SelectOptionAsync("opt1");

        // The cursor must travel to the <select> along a curve before the native select.
        Assert.True(mouseRec.CountOf("MoveAsync") >= 1, "should move the cursor to the element");
        // The real Playwright select is still performed (and its result flows back).
        Assert.True(locRec.WasCalled("SelectOptionAsync"));
        Assert.Equal(new[] { "opt1" }, result);
    }

    [Fact]
    public async Task SelectOptionAsync_overloads_all_humanize_and_delegate()
    {
        IReadOnlyList<string> selected = new[] { "v" };

        // Every ILocator SelectOptionAsync overload should hover (move) then delegate.
        async Task AssertOverload(System.Func<HumanizedLocator, Task> call)
        {
            var (page, mouseRec, _) = BuildPage();
            var (locator, locRec) = BuildLocator();
            locRec.On("SelectOptionAsync", Task.FromResult(selected));
            var human = new HumanizedLocator(locator, new HumanCursor(page), FastConfig());

            await call(human);

            Assert.True(mouseRec.CountOf("MoveAsync") >= 1, "should move the cursor");
            Assert.True(locRec.WasCalled("SelectOptionAsync"), "should delegate to inner");
        }

        var (handle, _) = Fake.Of<IElementHandle>();
        await AssertOverload(h => h.SelectOptionAsync("v"));
        await AssertOverload(h => h.SelectOptionAsync(new[] { "v" }));
        await AssertOverload(h => h.SelectOptionAsync(new SelectOptionValue { Value = "v" }));
        await AssertOverload(h => h.SelectOptionAsync(new[] { new SelectOptionValue { Value = "v" } }));
        await AssertOverload(h => h.SelectOptionAsync(handle));
        await AssertOverload(h => h.SelectOptionAsync(new[] { handle }));
    }

    [Fact]
    public async Task ClearAsync_focuses_selects_all_and_backspaces()
    {
        var (page, mouseRec, kbRec) = BuildPage();
        var (locator, _) = BuildLocator(); // EvaluateAsync(IsFocused) -> false
        var human = new HumanizedLocator(locator, new HumanCursor(page), FastConfig());

        await human.ClearAsync();

        // Not focused -> humanized click to focus the field (curve + press).
        Assert.True(mouseRec.CountOf("MoveAsync") >= 1, "should move the cursor to focus");
        Assert.Equal(1, mouseRec.CountOf("DownAsync"));
        // Then select-all + Backspace via the keyboard (NOT an instant value reset).
        Assert.True(kbRec.CountOf("PressAsync") >= 2, "select-all + backspace");
    }

    [Fact]
    public async Task ClearAsync_when_focused_skips_click_but_still_selects_and_deletes()
    {
        var (page, mouseRec, kbRec) = BuildPage();
        // Field is already focused -> no humanized click, just select-all + backspace.
        var (locator, _) = BuildLocator(evaluateResult: true);
        var human = new HumanizedLocator(locator, new HumanCursor(page), FastConfig());

        await human.ClearAsync();

        Assert.Equal(0, mouseRec.CountOf("DownAsync")); // no focus click needed
        Assert.True(kbRec.CountOf("PressAsync") >= 2, "select-all + backspace");
    }

    [Fact]
    public async Task CheckAsync_clicks_only_when_not_already_checked()
    {
        var (page, mouseRec, _) = BuildPage();
        var (locator, locRec) = BuildLocator();
        locRec.On("IsCheckedAsync", Task.FromResult(true)); // already checked
        var human = new HumanizedLocator(locator, new HumanCursor(page), FastConfig());

        await human.CheckAsync();

        Assert.Equal(0, mouseRec.CountOf("DownAsync")); // no click performed
    }

    [Fact]
    public async Task CheckAsync_clicks_when_unchecked()
    {
        var (page, mouseRec, _) = BuildPage();
        var (locator, locRec) = BuildLocator();
        locRec.On("IsCheckedAsync", Task.FromResult(false));
        var human = new HumanizedLocator(locator, new HumanCursor(page), FastConfig());

        await human.CheckAsync();

        Assert.Equal(1, mouseRec.CountOf("DownAsync")); // click performed
    }

    // -----------------------------------------------------------------------
    // Nested re-wrapping: locator-returning members return humanized locators.
    // -----------------------------------------------------------------------

    [Fact]
    public void Nested_locator_members_return_wrapped_locators()
    {
        var (page, _, _) = BuildPage();
        var (inner, innerRec) = Fake.Of<ILocator>();
        var (child, _) = Fake.Of<ILocator>();
        innerRec.On("First", child);
        innerRec.On("Last", child);
        innerRec.On("Nth", child);
        innerRec.On("Locator", child);
        innerRec.On("GetByTestId", child);
        innerRec.On("GetByText", child);

        var human = new HumanizedLocator(inner, new HumanCursor(page), FastConfig());

        Assert.IsType<HumanizedLocator>(human.First);
        Assert.IsType<HumanizedLocator>(human.Last);
        Assert.IsType<HumanizedLocator>(human.Nth(0));
        Assert.IsType<HumanizedLocator>(human.Locator("a"));
        Assert.IsType<HumanizedLocator>(human.GetByTestId("t"));
        Assert.IsType<HumanizedLocator>(human.GetByText("x"));
    }

    // -----------------------------------------------------------------------
    // Delegation: non-interaction members forward to the inner locator.
    // -----------------------------------------------------------------------

    [Fact]
    public async Task Query_members_delegate_to_inner()
    {
        var (page, _, _) = BuildPage();
        var (inner, innerRec) = Fake.Of<ILocator>();
        innerRec.On("CountAsync", Task.FromResult(7));
        innerRec.On("TextContentAsync", Task.FromResult<string?>("hello"));
        innerRec.On("IsVisibleAsync", Task.FromResult(true));

        var human = new HumanizedLocator(inner, new HumanCursor(page), FastConfig());

        Assert.Equal(7, await human.CountAsync());
        Assert.Equal("hello", await human.TextContentAsync());
        Assert.True(await human.IsVisibleAsync());
        Assert.True(innerRec.WasCalled("CountAsync"));
        Assert.True(innerRec.WasCalled("TextContentAsync"));
    }

    // -----------------------------------------------------------------------
    // Completeness - port of Python test_locator_methods_patched.
    // Every interaction method must be hand-written (humanized/intercepted),
    // NOT left to the source generator to delegate straight to Playwright.
    // The generator marks the members it emits with [GeneratedCode]; an
    // intercepted method carries no such marker.
    // -----------------------------------------------------------------------

    public static IEnumerable<object[]> InteractionMethodNames() => new[]
    {
        new object[] { "ClickAsync" },
        new object[] { "DblClickAsync" },
        new object[] { "HoverAsync" },
        new object[] { "TapAsync" },
        new object[] { "FillAsync" },
        new object[] { "TypeAsync" },
        new object[] { "PressSequentiallyAsync" },
        new object[] { "PressAsync" },
        new object[] { "CheckAsync" },
        new object[] { "UncheckAsync" },
        new object[] { "SetCheckedAsync" },
        new object[] { "DragToAsync" },
        new object[] { "SelectOptionAsync" },
        new object[] { "ClearAsync" },
    };

    private static bool IsGenerated(System.Reflection.MethodInfo m) =>
        m.GetCustomAttributes(typeof(System.CodeDom.Compiler.GeneratedCodeAttribute), false).Length > 0;

    [Theory]
    [MemberData(nameof(InteractionMethodNames))]
    public void Interaction_method_is_humanized_not_generator_delegated(string methodName)
    {
        var methods = typeof(HumanizedLocator)
            .GetMethods(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance)
            .Where(m => m.Name == methodName)
            .ToList();

        Assert.NotEmpty(methods); // the method exists on the wrapper
        // EVERY overload of an interaction method must be hand-written.
        Assert.All(methods, m =>
            Assert.False(IsGenerated(m),
                $"{methodName} must be humanized (hand-written), not generator-delegated"));
    }

    [Fact]
    public void All_fourteen_interaction_methods_are_present_and_humanized()
    {
        var humanizedNames = typeof(HumanizedLocator)
            .GetMethods(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance)
            .Where(m => !IsGenerated(m))
            .Select(m => m.Name)
            .ToHashSet();

        foreach (var row in InteractionMethodNames())
            Assert.Contains((string)row[0], humanizedNames);
    }

    [Fact]
    public void A_non_interaction_member_is_generator_delegated()
    {
        // Sanity check that the [GeneratedCode] discriminator actually works:
        // a pure query like CountAsync is delegated by the generator.
        var count = typeof(HumanizedLocator).GetMethod("CountAsync");
        Assert.NotNull(count);
        Assert.True(IsGenerated(count!), "CountAsync should be generator-delegated");
    }

    // -----------------------------------------------------------------------
    // Escape hatch
    // -----------------------------------------------------------------------

    [Fact]
    public void Original_and_Inner_expose_unwrapped_locator()
    {
        var (page, _, _) = BuildPage();
        var (inner, _) = Fake.Of<ILocator>();
        var human = new HumanizedLocator(inner, new HumanCursor(page), FastConfig());
        Assert.Same(inner, human.Original);
        Assert.Same(inner, human.Inner);
    }

    // -----------------------------------------------------------------------
    // Exception & cancellation propagation
    // -----------------------------------------------------------------------

    [Fact]
    public async Task Inner_exception_during_action_propagates()
    {
        var (page, _, _) = BuildPage();
        var (locator, locRec) = BuildLocator();
        locRec.On("ScrollIntoViewIfNeededAsync", _ => throw new PlaywrightException("detached"));
        var human = new HumanizedLocator(locator, new HumanCursor(page), FastConfig());

        await Assert.ThrowsAsync<PlaywrightException>(() => human.ClickAsync());
    }

    [Fact]
    public async Task Cancellation_propagates_as_OperationCanceled()
    {
        var (page, _, _) = BuildPage();
        var (locator, locRec) = BuildLocator();
        locRec.On("ScrollIntoViewIfNeededAsync", _ => throw new OperationCanceledException());
        var human = new HumanizedLocator(locator, new HumanCursor(page), FastConfig());

        await Assert.ThrowsAsync<OperationCanceledException>(() => human.ClickAsync());
    }
}
