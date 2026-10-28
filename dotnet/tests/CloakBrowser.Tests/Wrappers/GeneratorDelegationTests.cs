using CloakBrowser.Human;
using CloakBrowser.Wrappers;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests.Wrappers;

/// <summary>
/// Tests that the Roslyn source generator's auto-delegation is correct: every
/// non-intercepted interface member forwards to the inner object verbatim, with
/// arguments and return values passed through, exceptions propagated, and overloads
/// distinguished.
/// </summary>
public class GeneratorDelegationTests
{
    private static (HumanizedLocator human, FakeProxy rec) Locator()
    {
        var (mouse, _) = Fake.Of<IMouse>();
        var (keyboard, _) = Fake.Of<IKeyboard>();
        var (page, pageRec) = Fake.Of<IPage>();
        pageRec.On("Mouse", mouse);
        pageRec.On("Keyboard", keyboard);
        var (inner, rec) = Fake.Of<ILocator>();
        return (new HumanizedLocator(inner, new HumanCursor(page), new HumanConfig()), rec);
    }

    // -----------------------------------------------------------------------
    // Methods delegate with arguments + return values intact.
    // -----------------------------------------------------------------------

    [Fact]
    public async Task Method_with_return_value_delegates()
    {
        var (human, rec) = Locator();
        rec.On("CountAsync", Task.FromResult(42));
        Assert.Equal(42, await human.CountAsync());
        Assert.True(rec.WasCalled("CountAsync"));
    }

    [Fact]
    public async Task Method_arguments_are_forwarded_unchanged()
    {
        var (human, rec) = Locator();
        rec.On("WaitForAsync", Task.CompletedTask);
        var options = new LocatorWaitForOptions();
        await human.WaitForAsync(options);
        Assert.Same(options, rec.Last("WaitForAsync")!.Args[0]);
    }

    [Fact]
    public async Task Method_with_optional_options_delegates_without_throwing()
    {
        var (human, rec) = Locator();
        rec.On("WaitForAsync", Task.CompletedTask);
        // Call without supplying the optional options argument.
        await human.WaitForAsync();
        Assert.True(rec.WasCalled("WaitForAsync"));
    }

    [Fact]
    public async Task Generic_returning_method_delegates_with_type_intact()
    {
        var (human, rec) = Locator();
        rec.On("EvaluateAsync", Task.FromResult(123));
        // ILocator has a generic EvaluateAsync<T>; ensure delegation preserves T=int.
        int result = await human.EvaluateAsync<int>("el => 123");
        Assert.Equal(123, result);
    }

    // -----------------------------------------------------------------------
    // Properties delegate.
    // -----------------------------------------------------------------------

    [Fact]
    public void Property_getter_delegates()
    {
        var (human, rec) = Locator();
        // No handler registered: the getter still delegates and is recorded; the
        // generator returns the inner value (default null for IPage here).
        _ = human.Page;
        Assert.True(rec.WasCalled("Page"));
    }

    // -----------------------------------------------------------------------
    // Exceptions from delegated members propagate unchanged (not swallowed).
    // -----------------------------------------------------------------------

    [Fact]
    public async Task Delegated_exception_propagates_with_same_type_and_message()
    {
        var (human, rec) = Locator();
        rec.On("WaitForAsync", _ => throw new TimeoutException("timed out"));
        var ex = await Assert.ThrowsAsync<TimeoutException>(() => human.WaitForAsync());
        Assert.Equal("timed out", ex.Message);
    }

    // -----------------------------------------------------------------------
    // The marker attribute was generated into the consuming assembly.
    // -----------------------------------------------------------------------

    [Fact]
    public void Generated_marker_attribute_exists()
    {
        var attrType = typeof(HumanizedPage).Assembly
            .GetType("CloakBrowser.Wrappers.GenerateInterfaceDelegationAttribute");
        Assert.NotNull(attrType);
    }

    // -----------------------------------------------------------------------
    // Every wrapper actually implements its full Playwright interface - proof
    // that the generator filled in all non-hand-written members (a missing
    // implementation would not even compile, but this asserts the contract too).
    // -----------------------------------------------------------------------

    [Theory]
    [InlineData(typeof(HumanizedPage), typeof(IPage))]
    [InlineData(typeof(HumanizedLocator), typeof(ILocator))]
    [InlineData(typeof(HumanizedMouse), typeof(IMouse))]
    [InlineData(typeof(HumanizedKeyboard), typeof(IKeyboard))]
    [InlineData(typeof(HumanizedFrame), typeof(IFrame))]
    [InlineData(typeof(HumanizedElementHandle), typeof(IElementHandle))]
    [InlineData(typeof(HumanizedBrowser), typeof(IBrowser))]
    [InlineData(typeof(HumanizedBrowserContext), typeof(IBrowserContext))]
    public void Wrapper_implements_full_interface(System.Type wrapper, System.Type iface)
    {
        Assert.True(iface.IsAssignableFrom(wrapper),
            $"{wrapper.Name} must implement {iface.Name}");
    }

    [Theory]
    [InlineData(typeof(HumanizedPage))]
    [InlineData(typeof(HumanizedLocator))]
    [InlineData(typeof(HumanizedMouse))]
    [InlineData(typeof(HumanizedKeyboard))]
    [InlineData(typeof(HumanizedFrame))]
    [InlineData(typeof(HumanizedElementHandle))]
    [InlineData(typeof(HumanizedBrowser))]
    [InlineData(typeof(HumanizedBrowserContext))]
    public void Wrapper_exposes_Original_and_Inner_escape_hatch(System.Type wrapper)
    {
        Assert.NotNull(wrapper.GetProperty("Original"));
        Assert.NotNull(wrapper.GetProperty("Inner"));
    }

    // -----------------------------------------------------------------------
    // Guard: NO interaction method may be left to the source generator to
    // delegate straight to raw Playwright (that would silently bypass
    // humanization). Previously enforced for Locator only; now covers every
    // interactive wrapper. A future overload that falls through to the
    // generator fails the build here.
    //
    // This is what caught the Frame.SelectOptionAsync / DragAndDropAsync and
    // ElementHandle.SelectOptionAsync / SetCheckedAsync gaps: the generator had
    // been forwarding those raw because no override was hand-written.
    // -----------------------------------------------------------------------

    private static bool IsGenerated(System.Reflection.MethodInfo m) =>
        m.GetCustomAttributes(typeof(System.CodeDom.Compiler.GeneratedCodeAttribute), false).Length > 0;

    public static IEnumerable<object[]> InteractionMethodsByWrapper() => new[]
    {
        // HumanizedPage
        new object[] { typeof(HumanizedPage), "ClickAsync" },
        new object[] { typeof(HumanizedPage), "DblClickAsync" },
        new object[] { typeof(HumanizedPage), "HoverAsync" },
        new object[] { typeof(HumanizedPage), "TapAsync" },
        new object[] { typeof(HumanizedPage), "FillAsync" },
        new object[] { typeof(HumanizedPage), "TypeAsync" },
        new object[] { typeof(HumanizedPage), "PressAsync" },
        new object[] { typeof(HumanizedPage), "CheckAsync" },
        new object[] { typeof(HumanizedPage), "UncheckAsync" },
        new object[] { typeof(HumanizedPage), "SetCheckedAsync" },
        new object[] { typeof(HumanizedPage), "SelectOptionAsync" },
        new object[] { typeof(HumanizedPage), "DragAndDropAsync" },
        // HumanizedFrame
        new object[] { typeof(HumanizedFrame), "ClickAsync" },
        new object[] { typeof(HumanizedFrame), "DblClickAsync" },
        new object[] { typeof(HumanizedFrame), "HoverAsync" },
        new object[] { typeof(HumanizedFrame), "TapAsync" },
        new object[] { typeof(HumanizedFrame), "FillAsync" },
        new object[] { typeof(HumanizedFrame), "TypeAsync" },
        new object[] { typeof(HumanizedFrame), "PressAsync" },
        new object[] { typeof(HumanizedFrame), "CheckAsync" },
        new object[] { typeof(HumanizedFrame), "UncheckAsync" },
        new object[] { typeof(HumanizedFrame), "SetCheckedAsync" },
        new object[] { typeof(HumanizedFrame), "SelectOptionAsync" },
        new object[] { typeof(HumanizedFrame), "DragAndDropAsync" },
        // HumanizedElementHandle (no DragAndDropAsync on IElementHandle)
        new object[] { typeof(HumanizedElementHandle), "ClickAsync" },
        new object[] { typeof(HumanizedElementHandle), "DblClickAsync" },
        new object[] { typeof(HumanizedElementHandle), "HoverAsync" },
        new object[] { typeof(HumanizedElementHandle), "TapAsync" },
        new object[] { typeof(HumanizedElementHandle), "FillAsync" },
        new object[] { typeof(HumanizedElementHandle), "TypeAsync" },
        new object[] { typeof(HumanizedElementHandle), "PressAsync" },
        new object[] { typeof(HumanizedElementHandle), "CheckAsync" },
        new object[] { typeof(HumanizedElementHandle), "UncheckAsync" },
        new object[] { typeof(HumanizedElementHandle), "SetCheckedAsync" },
        new object[] { typeof(HumanizedElementHandle), "SelectOptionAsync" },
        // HumanizedMouse
        new object[] { typeof(HumanizedMouse), "MoveAsync" },
        new object[] { typeof(HumanizedMouse), "ClickAsync" },
        new object[] { typeof(HumanizedMouse), "DblClickAsync" },
        // HumanizedKeyboard
        new object[] { typeof(HumanizedKeyboard), "TypeAsync" },
        // Element reads + event dispatch (isolated world, never Playwright's own path)
        new object[] { typeof(HumanizedPage), "InputValueAsync" },
        new object[] { typeof(HumanizedPage), "TextContentAsync" },
        new object[] { typeof(HumanizedPage), "InnerTextAsync" },
        new object[] { typeof(HumanizedPage), "InnerHTMLAsync" },
        new object[] { typeof(HumanizedPage), "GetAttributeAsync" },
        new object[] { typeof(HumanizedPage), "DispatchEventAsync" },
        new object[] { typeof(HumanizedFrame), "InputValueAsync" },
        new object[] { typeof(HumanizedFrame), "TextContentAsync" },
        new object[] { typeof(HumanizedFrame), "InnerTextAsync" },
        new object[] { typeof(HumanizedFrame), "InnerHTMLAsync" },
        new object[] { typeof(HumanizedFrame), "GetAttributeAsync" },
        new object[] { typeof(HumanizedFrame), "DispatchEventAsync" },
        new object[] { typeof(HumanizedLocator), "InputValueAsync" },
        new object[] { typeof(HumanizedLocator), "TextContentAsync" },
        new object[] { typeof(HumanizedLocator), "InnerTextAsync" },
        new object[] { typeof(HumanizedLocator), "InnerHTMLAsync" },
        new object[] { typeof(HumanizedLocator), "GetAttributeAsync" },
        new object[] { typeof(HumanizedLocator), "DispatchEventAsync" },
        new object[] { typeof(HumanizedElementHandle), "InputValueAsync" },
        new object[] { typeof(HumanizedElementHandle), "TextContentAsync" },
        new object[] { typeof(HumanizedElementHandle), "InnerTextAsync" },
        new object[] { typeof(HumanizedElementHandle), "InnerHTMLAsync" },
        new object[] { typeof(HumanizedElementHandle), "GetAttributeAsync" },
        new object[] { typeof(HumanizedElementHandle), "DispatchEventAsync" },
    };

    /// <summary>Every member that hands out an element handle, frame or frame locator
    /// re-wraps it; otherwise actions on the result would run stock Playwright (visible to
    /// the page through its InjectedScript events).</summary>
    [Theory]
    [InlineData(typeof(HumanizedPage), "QuerySelectorAsync")]
    [InlineData(typeof(HumanizedPage), "QuerySelectorAllAsync")]
    [InlineData(typeof(HumanizedPage), "WaitForSelectorAsync")]
    [InlineData(typeof(HumanizedPage), "FrameLocator")]
    [InlineData(typeof(HumanizedFrame), "QuerySelectorAsync")]
    [InlineData(typeof(HumanizedFrame), "QuerySelectorAllAsync")]
    [InlineData(typeof(HumanizedFrame), "WaitForSelectorAsync")]
    [InlineData(typeof(HumanizedFrame), "FrameElementAsync")]
    [InlineData(typeof(HumanizedFrame), "FrameLocator")]
    [InlineData(typeof(HumanizedLocator), "ElementHandleAsync")]
    [InlineData(typeof(HumanizedLocator), "ElementHandlesAsync")]
    [InlineData(typeof(HumanizedLocator), "FrameLocator")]
    [InlineData(typeof(HumanizedElementHandle), "QuerySelectorAsync")]
    [InlineData(typeof(HumanizedElementHandle), "ContentFrameAsync")]
    [InlineData(typeof(HumanizedElementHandle), "OwnerFrameAsync")]
    public void Handle_and_frame_returning_member_rewraps(System.Type wrapper, string methodName)
    {
        var methods = wrapper.GetMethods(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance)
            .Where(m => m.Name == methodName).ToList();
        Assert.NotEmpty(methods);
        Assert.All(methods, m => Assert.False(IsGenerated(m), $"{wrapper.Name}.{methodName} must re-wrap its result"));
    }

    [Theory]
    [InlineData(typeof(HumanizedLocator), "ContentFrame")]
    public void Frame_locator_property_rewraps(System.Type wrapper, string propertyName)
    {
        var getter = wrapper.GetProperty(propertyName)!.GetGetMethod()!;
        Assert.False(IsGenerated(getter), $"{wrapper.Name}.{propertyName} must re-wrap its result");
    }

    /// <summary>Raw primitives stay raw, like the Python / JS wrappers: a person's
    /// mouse down / up / wheel and key down / up / press / insertText map 1:1 to input.</summary>
    [Theory]
    [InlineData(typeof(HumanizedMouse), "DownAsync")]
    [InlineData(typeof(HumanizedMouse), "UpAsync")]
    [InlineData(typeof(HumanizedMouse), "WheelAsync")]
    [InlineData(typeof(HumanizedKeyboard), "DownAsync")]
    [InlineData(typeof(HumanizedKeyboard), "UpAsync")]
    [InlineData(typeof(HumanizedKeyboard), "PressAsync")]
    [InlineData(typeof(HumanizedKeyboard), "InsertTextAsync")]
    public void Raw_input_primitive_is_delegated(System.Type wrapper, string methodName)
    {
        var methods = wrapper.GetMethods(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance)
            .Where(m => m.Name == methodName).ToList();
        Assert.NotEmpty(methods);
        Assert.All(methods, m => Assert.True(IsGenerated(m), $"{wrapper.Name}.{methodName} should be delegated"));
    }

    [Theory]
    [MemberData(nameof(InteractionMethodsByWrapper))]
    public void Interaction_method_is_humanized_not_generator_delegated(System.Type wrapper, string methodName)
    {
        var methods = wrapper
            .GetMethods(System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance)
            .Where(m => m.Name == methodName)
            .ToList();

        Assert.NotEmpty(methods); // the method exists on the wrapper
        // EVERY overload of an interaction method must be hand-written, not
        // emitted by the generator (which would delegate straight to Playwright).
        Assert.All(methods, m =>
            Assert.False(IsGenerated(m),
                $"{wrapper.Name}.{methodName} must be humanized (hand-written), not generator-delegated"));
    }
}
