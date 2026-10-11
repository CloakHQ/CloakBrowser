using System.Text.RegularExpressions;
using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Transparent humanizing decorator over Playwright's <see cref="IFrame"/>.
///
/// Frames have no Mouse/Keyboard of their own (those belong to the page): selector
/// actions and the element reads / DispatchEvent run through the page's
/// <see cref="HumanEngine"/>, resolved in this frame's
/// own isolated world, with wheel scrolling and hit-tests through every ancestor
/// iframe. Locator/frame returning members are re-wrapped; everything else is
/// delegated by the generator.
/// </summary>
[GenerateInterfaceDelegation(typeof(IFrame))]
public sealed partial class HumanizedFrame : IFrame
{
    private readonly IFrame _inner;
    private readonly HumanCursor _cursor;
    private readonly HumanConfig _cfg;

    internal HumanizedFrame(IFrame inner, HumanCursor cursor, HumanConfig cfg)
    {
        _inner = inner;
        _cursor = cursor;
        _cfg = cfg;
    }

    /// <summary>The original, un-humanized Playwright frame (escape hatch for raw speed).</summary>
    public IFrame Original => _inner;

    /// <summary>Alias of <see cref="Original"/>.</summary>
    public IFrame Inner => _inner;

    private ILocator Wrap(ILocator l) => Humanize.WrapLocator(l, _cursor, _cfg);
    private ILocator Wrap(ILocator l, string? selector) => Humanize.WrapLocator(l, _cursor, _cfg, selector);
    private IFrame Wrap(IFrame f) => Humanize.WrapFrame(f, _cursor, _cfg);

    // -----------------------------------------------------------------------
    // Humanized selector actions: resolved in THIS frame's isolated world.
    // -----------------------------------------------------------------------

    private HumanEngine E => _cursor.EngineFor(_cfg);
    private static ActOpts Opt(object? options) => ActOpts.From(options);
    private Target T(string selector, object? options) => new(_inner, selector, ActOpts.From(options).Strict);

    public Task ClickAsync(string selector, FrameClickOptions? options = null) => E.ClickAsync(T(selector, options), Opt(options), "Frame.ClickAsync");
    public Task DblClickAsync(string selector, FrameDblClickOptions? options = null) => E.ClickAsync(T(selector, options), Opt(options), "Frame.DblClickAsync", 2);
    public Task HoverAsync(string selector, FrameHoverOptions? options = null) => E.HoverAsync(T(selector, options), Opt(options), "Frame.HoverAsync");
    public Task TapAsync(string selector, FrameTapOptions? options = null) => E.TapAsync(T(selector, options), Opt(options), "Frame.TapAsync");
    public Task FillAsync(string selector, string value, FrameFillOptions? options = null) => E.FillAsync(T(selector, options), value, Opt(options), "Frame.FillAsync");
    public Task TypeAsync(string selector, string text, FrameTypeOptions? options = null) => E.TypeAsync(T(selector, options), text, Opt(options), "Frame.TypeAsync");
    public Task PressAsync(string selector, string key, FramePressOptions? options = null) => E.PressAsync(T(selector, options), key, Opt(options), "Frame.PressAsync");
    public Task CheckAsync(string selector, FrameCheckOptions? options = null) => E.SetCheckedAsync(T(selector, options), true, Opt(options), "Frame.CheckAsync");
    public Task UncheckAsync(string selector, FrameUncheckOptions? options = null) => E.SetCheckedAsync(T(selector, options), false, Opt(options), "Frame.UncheckAsync");
    public Task SetCheckedAsync(string selector, bool checkedState, FrameSetCheckedOptions? options = null) =>
        E.SetCheckedAsync(T(selector, options), checkedState, Opt(options), "Frame.SetCheckedAsync");
    public Task FocusAsync(string selector, FrameFocusOptions? options = null) => E.FocusAsync(T(selector, options), Opt(options), "Frame.FocusAsync");
    public Task DragAndDropAsync(string source, string target, FrameDragAndDropOptions? options = null) =>
        E.DragAsync(T(source, options), T(target, options), Opt(options), "Frame.DragAndDropAsync");

    // -----------------------------------------------------------------------
    // Element reads and event dispatch: resolved and executed by the engine in THIS
    // frame's isolated world, like the actions above. The raw Playwright methods stay
    // reachable through Original (escape hatch).
    // -----------------------------------------------------------------------

    private Task<string?> Read(string selector, string op, object? options, string api, params object?[] extra) =>
        E.ReadAsync(T(selector, options), op, Opt(options), api, extra);

    public async Task<string> InputValueAsync(string selector, FrameInputValueOptions? options = null) =>
        (await Read(selector, "inputValue", options, "Frame.InputValueAsync").ConfigureAwait(false))!;

    public Task<string?> TextContentAsync(string selector, FrameTextContentOptions? options = null) =>
        Read(selector, "textContent", options, "Frame.TextContentAsync");

    public async Task<string> InnerTextAsync(string selector, FrameInnerTextOptions? options = null) =>
        (await Read(selector, "innerText", options, "Frame.InnerTextAsync").ConfigureAwait(false))!;

    public async Task<string> InnerHTMLAsync(string selector, FrameInnerHTMLOptions? options = null) =>
        (await Read(selector, "innerHTML", options, "Frame.InnerHTMLAsync").ConfigureAwait(false))!;

    public Task<string?> GetAttributeAsync(string selector, string name, FrameGetAttributeOptions? options = null) =>
        Read(selector, "getAttribute", options, "Frame.GetAttributeAsync", name);

    public async Task DispatchEventAsync(string selector, string type, object? eventInit = null, FrameDispatchEventOptions? options = null)
    {
        // A JSHandle in eventInit lives in the main world: Playwright's own call.
        try { await E.DispatchAsync(T(selector, options), Opt(options), "Frame.DispatchEventAsync", type, eventInit).ConfigureAwait(false); }
        catch (RawFallbackException) { await _inner.DispatchEventAsync(selector, type, eventInit, options).ConfigureAwait(false); }
    }

    private Task<IReadOnlyList<string>> Select(string selector, SelectValues v, FrameSelectOptionOptions? options) =>
        E.SelectOptionAsync(T(selector, options), v.Options, v.Handles, Opt(options), "Frame.SelectOptionAsync");

    public Task<IReadOnlyList<string>> SelectOptionAsync(string selector, string values, FrameSelectOptionOptions? options = null) =>
        Select(selector, SelectValues.Of(new[] { values }), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IElementHandle values, FrameSelectOptionOptions? options = null) =>
        Select(selector, SelectValues.Of(new[] { values }), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IEnumerable<string> values, FrameSelectOptionOptions? options = null) =>
        Select(selector, SelectValues.Of(values), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(string selector, SelectOptionValue values, FrameSelectOptionOptions? options = null) =>
        Select(selector, SelectValues.Of(new[] { values }), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IEnumerable<IElementHandle> values, FrameSelectOptionOptions? options = null) =>
        Select(selector, SelectValues.Of(values), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IEnumerable<SelectOptionValue> values, FrameSelectOptionOptions? options = null) =>
        Select(selector, SelectValues.Of(values), options);

    // -----------------------------------------------------------------------
    // Locator-returning members - re-wrap.
    // -----------------------------------------------------------------------

    public IFrameLocator FrameLocator(string selector) => Humanize.WrapFrameLocator(_inner.FrameLocator(selector), _cursor, _cfg);
    public ILocator Locator(string selector, FrameLocatorOptions? options = null) => Wrap(_inner.Locator(selector, options));
    public ILocator GetByAltText(string text, FrameGetByAltTextOptions? options = null) => Wrap(_inner.GetByAltText(text, options));
    public ILocator GetByAltText(Regex text, FrameGetByAltTextOptions? options = null) => Wrap(_inner.GetByAltText(text, options));
    public ILocator GetByLabel(string text, FrameGetByLabelOptions? options = null) => Wrap(_inner.GetByLabel(text, options));
    public ILocator GetByLabel(Regex text, FrameGetByLabelOptions? options = null) => Wrap(_inner.GetByLabel(text, options));
    public ILocator GetByPlaceholder(string text, FrameGetByPlaceholderOptions? options = null) => Wrap(_inner.GetByPlaceholder(text, options));
    public ILocator GetByPlaceholder(Regex text, FrameGetByPlaceholderOptions? options = null) => Wrap(_inner.GetByPlaceholder(text, options));
    public ILocator GetByRole(AriaRole role, FrameGetByRoleOptions? options = null) => Wrap(_inner.GetByRole(role, options));
    public ILocator GetByTestId(string testId) => Wrap(_inner.GetByTestId(testId));
    public ILocator GetByTestId(Regex testId) => Wrap(_inner.GetByTestId(testId));
    public ILocator GetByText(string text, FrameGetByTextOptions? options = null) => Wrap(_inner.GetByText(text, options));
    public ILocator GetByText(Regex text, FrameGetByTextOptions? options = null) => Wrap(_inner.GetByText(text, options));
    public ILocator GetByTitle(string text, FrameGetByTitleOptions? options = null) => Wrap(_inner.GetByTitle(text, options));
    public ILocator GetByTitle(Regex text, FrameGetByTitleOptions? options = null) => Wrap(_inner.GetByTitle(text, options));

    // -----------------------------------------------------------------------
    // Frame-returning members - re-wrap.
    // -----------------------------------------------------------------------

    public IReadOnlyList<IFrame> ChildFrames => Humanize.WrapFrames(_inner.ChildFrames, _cursor, _cfg);
    public IFrame? ParentFrame { get { var f = _inner.ParentFrame; return f == null ? null : Wrap(f); } }

    // -----------------------------------------------------------------------
    // Handle-returning members - re-wrap so handle actions stay humanized.
    // -----------------------------------------------------------------------

    private IElementHandle? H(IElementHandle? h) => h == null ? null : Humanize.WrapElementHandle(h, _cursor, _cfg);

    public async Task<IElementHandle?> QuerySelectorAsync(string selector, FrameQuerySelectorOptions? options = null) =>
        H(await _inner.QuerySelectorAsync(selector, options).ConfigureAwait(false));

    public async Task<IReadOnlyList<IElementHandle>> QuerySelectorAllAsync(string selector) =>
        Humanize.WrapHandles(await _inner.QuerySelectorAllAsync(selector).ConfigureAwait(false), _cursor, _cfg);

    public async Task<IElementHandle?> WaitForSelectorAsync(string selector, FrameWaitForSelectorOptions? options = null) =>
        H(await _inner.WaitForSelectorAsync(selector, options).ConfigureAwait(false));

    public async Task<IElementHandle> FrameElementAsync() =>
        H(await _inner.FrameElementAsync().ConfigureAwait(false))!;
}
