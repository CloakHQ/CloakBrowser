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
        // A pure query; the element reads (TextContentAsync, GetAttributeAsync, ...) are
        // humanized instead (see GeneratorDelegationTests).
        innerRec.On("AllTextContentsAsync", Task.FromResult<IReadOnlyList<string>>(new[] { "hello" }));
        innerRec.On("IsVisibleAsync", Task.FromResult(true));

        var human = new HumanizedLocator(inner, new HumanCursor(page), FastConfig());

        Assert.Equal(7, await human.CountAsync());
        Assert.Equal(new[] { "hello" }, await human.AllTextContentsAsync());
        Assert.True(await human.IsVisibleAsync());
        Assert.True(innerRec.WasCalled("CountAsync"));
        Assert.True(innerRec.WasCalled("AllTextContentsAsync"));
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
    public void Filter_unwraps_Has_and_HasNot_and_rewraps_result()
    {
        var (page, _, _) = BuildPage();
        var (inner, innerRec) = Fake.Of<ILocator>();
        var (resultLoc, _) = Fake.Of<ILocator>();
        innerRec.On("Filter", resultLoc);

        var cursor = new HumanCursor(page);
        var (rawHas, _) = Fake.Of<ILocator>();
        var (rawHasNot, _) = Fake.Of<ILocator>();
        var human = new HumanizedLocator(inner, cursor, FastConfig());

        var result = human.Filter(new LocatorFilterOptions
        {
            Has = new HumanizedLocator(rawHas, cursor, FastConfig()),
            HasNot = new HumanizedLocator(rawHasNot, cursor, FastConfig()),
        });

        var opts = (LocatorFilterOptions)innerRec.Last("Filter")!.Args[0]!;
        Assert.Same(rawHas, opts.Has);            // raw locator reached Playwright
        Assert.Same(rawHasNot, opts.HasNot);
        Assert.IsType<HumanizedLocator>(result);  // returned locator stays humanized
    }
}
