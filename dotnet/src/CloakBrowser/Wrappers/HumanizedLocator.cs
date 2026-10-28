using System.Text.RegularExpressions;
using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Transparent humanizing decorator over Playwright's <see cref="ILocator"/>.
///
/// Intercepted (humanized, unified engine, strict mode): Click/DblClick/Hover/Tap/Fill/
/// Clear/Type/PressSequentially/Press/Check/Uncheck/SetChecked/SelectOption/Focus/DragTo/
/// ScrollIntoViewIfNeeded and the element reads (InputValue/TextContent/InnerText/
/// InnerHTML/GetAttribute) / DispatchEvent, for every locator shape (GetBy*, chains,
/// Filter, FrameLocator).
/// All other members - assertions, queries, waits, getters - are delegated to the inner
/// locator by the source generator. Locator-returning members are re-wrapped so chaining stays
/// humanized.
/// </summary>
[GenerateInterfaceDelegation(typeof(ILocator))]
public sealed partial class HumanizedLocator : ILocator
{
    private readonly ILocator _inner;
    private readonly HumanCursor _cursor;
    private readonly HumanConfig _cfg;
    private readonly string? _selector;

    internal HumanizedLocator(ILocator inner, HumanCursor cursor, HumanConfig cfg, string? selector = null)
    {
        _inner = inner;
        _cursor = cursor;
        _cfg = cfg;
        _selector = selector;
    }

    /// <summary>The Playwright selector string of this locator (any shape: GetBy*, chains,
    /// filters, frame locators).</summary>
    internal string? Selector => _selector ?? PlaywrightInternals.LocatorParts(_inner).Selector;

    /// <summary>The original, un-humanized Playwright locator (escape hatch for raw speed).</summary>
    public ILocator Original => _inner;

    /// <summary>Alias of <see cref="Original"/>.</summary>
    public ILocator Inner => _inner;

    private ILocator Wrap(ILocator l, string? selector = null) =>
        Humanize.WrapLocator(l, _cursor, _cfg, selector);

    // -----------------------------------------------------------------------
    // Humanized actions: the locator's own frame + selector string, strict mode,
    // resolved by Playwright's engine in the isolated world.
    // -----------------------------------------------------------------------

    private HumanEngine E => _cursor.EngineFor(_cfg);

    private Target T()
    {
        var (frame, selector) = PlaywrightInternals.LocatorParts(_inner);
        return new Target(frame, selector, strict: true);
    }

    private static ActOpts Opt(object? options) => ActOpts.From(options);

    public Task ClickAsync(LocatorClickOptions? options = null) => E.ClickAsync(T(), Opt(options), "Locator.ClickAsync");
    public Task DblClickAsync(LocatorDblClickOptions? options = null) => E.ClickAsync(T(), Opt(options), "Locator.DblClickAsync", 2);
    public Task HoverAsync(LocatorHoverOptions? options = null) => E.HoverAsync(T(), Opt(options), "Locator.HoverAsync");
    public Task TapAsync(LocatorTapOptions? options = null) => E.TapAsync(T(), Opt(options), "Locator.TapAsync");
    public Task FillAsync(string value, LocatorFillOptions? options = null) => E.FillAsync(T(), value, Opt(options), "Locator.FillAsync");
    public Task ClearAsync(LocatorClearOptions? options = null) => E.FillAsync(T(), "", Opt(options), "Locator.ClearAsync");
    public Task TypeAsync(string text, LocatorTypeOptions? options = null) => E.TypeAsync(T(), text, Opt(options), "Locator.TypeAsync");
    public Task PressSequentiallyAsync(string text, LocatorPressSequentiallyOptions? options = null) =>
        E.TypeAsync(T(), text, Opt(options), "Locator.PressSequentiallyAsync");
    public Task PressAsync(string key, LocatorPressOptions? options = null) => E.PressAsync(T(), key, Opt(options), "Locator.PressAsync");
    public Task CheckAsync(LocatorCheckOptions? options = null) => E.SetCheckedAsync(T(), true, Opt(options), "Locator.CheckAsync");
    public Task UncheckAsync(LocatorUncheckOptions? options = null) => E.SetCheckedAsync(T(), false, Opt(options), "Locator.UncheckAsync");
    public Task SetCheckedAsync(bool checkedState, LocatorSetCheckedOptions? options = null) =>
        E.SetCheckedAsync(T(), checkedState, Opt(options), "Locator.SetCheckedAsync");
    public Task FocusAsync(LocatorFocusOptions? options = null) => E.FocusAsync(T(), Opt(options), "Locator.FocusAsync");
    public Task ScrollIntoViewIfNeededAsync(LocatorScrollIntoViewIfNeededOptions? options = null) =>
        E.ScrollIntoViewIfNeededAsync(T(), Opt(options), "Locator.ScrollIntoViewIfNeededAsync");

    public Task DragToAsync(ILocator target, LocatorDragToOptions? options = null)
    {
        var other = target is HumanizedLocator h ? h.Original : target;
        var (frame, selector) = PlaywrightInternals.LocatorParts(other);
        return E.DragAsync(T(), new Target(frame, selector, strict: true), Opt(options), "Locator.DragToAsync");
    }

    // -----------------------------------------------------------------------
    // Element reads and event dispatch: resolved and executed by the engine in this
    // locator's frame's isolated world (strict mode, like the actions above).
    // The raw Playwright methods stay reachable through Original (escape hatch).
    // -----------------------------------------------------------------------

    private Task<string?> Read(string op, string api, object? options, params object?[] extra) =>
        E.ReadAsync(T(), op, Opt(options), api, extra);

    public async Task<string> InputValueAsync(LocatorInputValueOptions? options = null) =>
        (await Read("inputValue", "Locator.InputValueAsync", options).ConfigureAwait(false))!;

    public Task<string?> TextContentAsync(LocatorTextContentOptions? options = null) =>
        Read("textContent", "Locator.TextContentAsync", options);

    public async Task<string> InnerTextAsync(LocatorInnerTextOptions? options = null) =>
        (await Read("innerText", "Locator.InnerTextAsync", options).ConfigureAwait(false))!;

    public async Task<string> InnerHTMLAsync(LocatorInnerHTMLOptions? options = null) =>
        (await Read("innerHTML", "Locator.InnerHTMLAsync", options).ConfigureAwait(false))!;

    public Task<string?> GetAttributeAsync(string name, LocatorGetAttributeOptions? options = null) =>
        Read("getAttribute", "Locator.GetAttributeAsync", options, name);

    public async Task DispatchEventAsync(string type, object? eventInit = null, LocatorDispatchEventOptions? options = null)
    {
        // A JSHandle in eventInit lives in the main world: Playwright's own call.
        try { await E.DispatchAsync(T(), Opt(options), "Locator.DispatchEventAsync", type, eventInit).ConfigureAwait(false); }
        catch (RawFallbackException) { await _inner.DispatchEventAsync(type, eventInit, options).ConfigureAwait(false); }
    }

    private Task<IReadOnlyList<string>> Select(SelectValues v, LocatorSelectOptionOptions? options) =>
        E.SelectOptionAsync(T(), v.Options, v.Handles, Opt(options), "Locator.SelectOptionAsync");

    public Task<IReadOnlyList<string>> SelectOptionAsync(string values, LocatorSelectOptionOptions? options = null) =>
        Select(SelectValues.Of(new[] { values }), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(IElementHandle values, LocatorSelectOptionOptions? options = null) =>
        Select(SelectValues.Of(new[] { values }), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(IEnumerable<string> values, LocatorSelectOptionOptions? options = null) =>
        Select(SelectValues.Of(values), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(SelectOptionValue values, LocatorSelectOptionOptions? options = null) =>
        Select(SelectValues.Of(new[] { values }), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(IEnumerable<IElementHandle> values, LocatorSelectOptionOptions? options = null) =>
        Select(SelectValues.Of(values), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(IEnumerable<SelectOptionValue> values, LocatorSelectOptionOptions? options = null) =>
        Select(SelectValues.Of(values), options);

    // -----------------------------------------------------------------------
    // Locator-returning members - re-wrap so chains stay humanized.
    // -----------------------------------------------------------------------

    // These are the only locator transformations whose selector syntax is supported
    // by the isolated resolver. A second positional transformation cannot be encoded
    // by its one trailing nth component, so repeated chains deliberately become legacy.
    private string? WithNth(int index) =>
        _selector != null && !Regex.IsMatch(_selector, @"\s*>>\s*nth=-?\d+\s*$")
            ? $"{_selector} >> nth={index}"
            : null;

    public ILocator First => Wrap(_inner.First, WithNth(0));
    public ILocator Last => Wrap(_inner.Last, WithNth(-1));
    public ILocator Nth(int index) => Wrap(_inner.Nth(index), WithNth(index));
    public ILocator Or(ILocator locator) =>
        Wrap(_inner.Or(locator is HumanizedLocator h ? h.Original : locator));
    public ILocator And(ILocator locator) =>
        Wrap(_inner.And(locator is HumanizedLocator h ? h.Original : locator));

    // #549: unwrap Has/HasNot in place (rebuilding options would drop future fields).
    public ILocator Filter(LocatorFilterOptions? options = null)
    {
        if (options?.Has is HumanizedLocator has) options.Has = has.Original;
        if (options?.HasNot is HumanizedLocator hasNot) options.HasNot = hasNot.Original;
        return Wrap(_inner.Filter(options));
    }

    public IFrameLocator FrameLocator(string selector) => Humanize.WrapFrameLocator(_inner.FrameLocator(selector), _cursor, _cfg);
    public IFrameLocator ContentFrame => Humanize.WrapFrameLocator(_inner.ContentFrame, _cursor, _cfg);
    public ILocator Locator(string selectorOrLocator, LocatorLocatorOptions? options = null) =>
        Wrap(_inner.Locator(selectorOrLocator, options));
    public ILocator Locator(ILocator selectorOrLocator, LocatorLocatorOptions? options = null) =>
        Wrap(_inner.Locator(selectorOrLocator is HumanizedLocator h ? h.Original : selectorOrLocator, options));

    public ILocator GetByAltText(string text, LocatorGetByAltTextOptions? options = null) => Wrap(_inner.GetByAltText(text, options));
    public ILocator GetByAltText(Regex text, LocatorGetByAltTextOptions? options = null) => Wrap(_inner.GetByAltText(text, options));
    public ILocator GetByLabel(string text, LocatorGetByLabelOptions? options = null) => Wrap(_inner.GetByLabel(text, options));
    public ILocator GetByLabel(Regex text, LocatorGetByLabelOptions? options = null) => Wrap(_inner.GetByLabel(text, options));
    public ILocator GetByPlaceholder(string text, LocatorGetByPlaceholderOptions? options = null) => Wrap(_inner.GetByPlaceholder(text, options));
    public ILocator GetByPlaceholder(Regex text, LocatorGetByPlaceholderOptions? options = null) => Wrap(_inner.GetByPlaceholder(text, options));
    public ILocator GetByRole(AriaRole role, LocatorGetByRoleOptions? options = null) => Wrap(_inner.GetByRole(role, options));
    public ILocator GetByTestId(string testId) => Wrap(_inner.GetByTestId(testId));
    public ILocator GetByTestId(Regex testId) => Wrap(_inner.GetByTestId(testId));
    public ILocator GetByText(string text, LocatorGetByTextOptions? options = null) => Wrap(_inner.GetByText(text, options));
    public ILocator GetByText(Regex text, LocatorGetByTextOptions? options = null) => Wrap(_inner.GetByText(text, options));
    public ILocator GetByTitle(string text, LocatorGetByTitleOptions? options = null) => Wrap(_inner.GetByTitle(text, options));
    public ILocator GetByTitle(Regex text, LocatorGetByTitleOptions? options = null) => Wrap(_inner.GetByTitle(text, options));

    // -----------------------------------------------------------------------
    // Handle-returning members - re-wrap so handle actions stay humanized.
    // -----------------------------------------------------------------------

    public async Task<IElementHandle> ElementHandleAsync(LocatorElementHandleOptions? options = null) =>
        Humanize.WrapElementHandle(await _inner.ElementHandleAsync(options).ConfigureAwait(false), _cursor, _cfg);

    public async Task<IReadOnlyList<IElementHandle>> ElementHandlesAsync() =>
        Humanize.WrapHandles(await _inner.ElementHandlesAsync().ConfigureAwait(false), _cursor, _cfg);
}
