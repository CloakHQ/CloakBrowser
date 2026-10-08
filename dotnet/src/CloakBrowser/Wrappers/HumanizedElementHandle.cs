using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Transparent humanizing decorator over Playwright's <see cref="IElementHandle"/>.
///
/// Interaction methods run through the unified <see cref="HumanEngine"/>: the handle is
/// identified inside the isolated world by its protocol-level bounding box (no page
/// script runs); when two elements share that exact box the action raises and asks for a
/// Locator instead. Handle-returning queries are re-wrapped; everything else is delegated
/// by the generator.
/// </summary>
[GenerateInterfaceDelegation(typeof(IElementHandle))]
public sealed partial class HumanizedElementHandle : IElementHandle
{
    private readonly IElementHandle _inner;
    private readonly HumanCursor _cursor;
    private readonly HumanConfig _cfg;

    internal HumanizedElementHandle(IElementHandle inner, HumanCursor cursor, HumanConfig cfg)
    {
        _inner = inner;
        _cursor = cursor;
        _cfg = cfg;
    }

    /// <summary>The original, un-humanized Playwright element handle (escape hatch).</summary>
    public IElementHandle Original => _inner;

    /// <summary>Alias of <see cref="Original"/>.</summary>
    public IElementHandle Inner => _inner;

    // -----------------------------------------------------------------------
    // Humanized actions. The handle is located inside the isolated world by its
    // protocol-level bounding box (no page script); an ambiguous box raises.
    // -----------------------------------------------------------------------

    private HumanEngine E => _cursor.EngineFor(_cfg);
    private Target T() => new(PlaywrightInternals.HandleFrame(_inner), null, false, _inner);
    private static ActOpts Opt(object? options) => ActOpts.From(options);

    public Task ClickAsync(ElementHandleClickOptions? options = null) => E.ClickAsync(T(), Opt(options), "ElementHandle.ClickAsync");
    public Task DblClickAsync(ElementHandleDblClickOptions? options = null) => E.ClickAsync(T(), Opt(options), "ElementHandle.DblClickAsync", 2);
    public Task HoverAsync(ElementHandleHoverOptions? options = null) => E.HoverAsync(T(), Opt(options), "ElementHandle.HoverAsync");
    public Task TapAsync(ElementHandleTapOptions? options = null) => E.TapAsync(T(), Opt(options), "ElementHandle.TapAsync");
    public Task FillAsync(string value, ElementHandleFillOptions? options = null) => E.FillAsync(T(), value, Opt(options), "ElementHandle.FillAsync");
    public Task TypeAsync(string text, ElementHandleTypeOptions? options = null) => E.TypeAsync(T(), text, Opt(options), "ElementHandle.TypeAsync");
    public Task PressAsync(string key, ElementHandlePressOptions? options = null) => E.PressAsync(T(), key, Opt(options), "ElementHandle.PressAsync");
    public Task CheckAsync(ElementHandleCheckOptions? options = null) => E.SetCheckedAsync(T(), true, Opt(options), "ElementHandle.CheckAsync");
    public Task UncheckAsync(ElementHandleUncheckOptions? options = null) => E.SetCheckedAsync(T(), false, Opt(options), "ElementHandle.UncheckAsync");
    public Task SetCheckedAsync(bool checkedState, ElementHandleSetCheckedOptions? options = null) =>
        E.SetCheckedAsync(T(), checkedState, Opt(options), "ElementHandle.SetCheckedAsync");
    public Task FocusAsync() => E.FocusAsync(T(), new ActOpts(), "ElementHandle.FocusAsync", move: true);
    public Task ScrollIntoViewIfNeededAsync(ElementHandleScrollIntoViewIfNeededOptions? options = null) =>
        E.ScrollIntoViewIfNeededAsync(T(), Opt(options), "ElementHandle.ScrollIntoViewIfNeededAsync");

    private static ILocator Unwrap(ILocator l) => l is HumanizedLocator w ? w.Original : l;

    // #549: unwrap masked locators in place (rebuilding options would drop future fields).
    public Task<byte[]> ScreenshotAsync(ElementHandleScreenshotOptions? options = null)
    {
        if (options?.Mask != null)
            options.Mask = options.Mask.Select(Unwrap).ToList();
        return _inner.ScreenshotAsync(options);
    }

    private Task<IReadOnlyList<string>> Select(SelectValues v, ElementHandleSelectOptionOptions? options) =>
        E.SelectOptionAsync(T(), v.Options, v.Handles, Opt(options), "ElementHandle.SelectOptionAsync");

    public Task<IReadOnlyList<string>> SelectOptionAsync(string values, ElementHandleSelectOptionOptions? options = null) =>
        Select(SelectValues.Of(new[] { values }), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(IElementHandle values, ElementHandleSelectOptionOptions? options = null) =>
        Select(SelectValues.Of(new[] { values }), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(IEnumerable<string> values, ElementHandleSelectOptionOptions? options = null) =>
        Select(SelectValues.Of(values), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(SelectOptionValue values, ElementHandleSelectOptionOptions? options = null) =>
        Select(SelectValues.Of(new[] { values }), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(IEnumerable<IElementHandle> values, ElementHandleSelectOptionOptions? options = null) =>
        Select(SelectValues.Of(values), options);
    public Task<IReadOnlyList<string>> SelectOptionAsync(IEnumerable<SelectOptionValue> values, ElementHandleSelectOptionOptions? options = null) =>
        Select(SelectValues.Of(values), options);

    // -----------------------------------------------------------------------
    // Handle-returning members - re-wrap.
    // -----------------------------------------------------------------------

    public async Task<IElementHandle?> QuerySelectorAsync(string selector)
    {
        var h = await _inner.QuerySelectorAsync(selector).ConfigureAwait(false);
        return h == null ? null : Humanize.WrapElementHandle(h, _cursor, _cfg);
    }

    public async Task<IReadOnlyList<IElementHandle>> QuerySelectorAllAsync(string selector)
    {
        var hs = await _inner.QuerySelectorAllAsync(selector).ConfigureAwait(false);
        return Humanize.WrapHandles(hs, _cursor, _cfg);
    }

    public async Task<IElementHandle?> WaitForSelectorAsync(string selector, ElementHandleWaitForSelectorOptions? options = null)
    {
        var h = await _inner.WaitForSelectorAsync(selector, options).ConfigureAwait(false);
        return h == null ? null : Humanize.WrapElementHandle(h, _cursor, _cfg);
    }

    public async Task<IFrame?> ContentFrameAsync()
    {
        var f = await _inner.ContentFrameAsync().ConfigureAwait(false);
        return f == null ? null : Humanize.WrapFrame(f, _cursor, _cfg);
    }

    public async Task<IFrame?> OwnerFrameAsync()
    {
        var f = await _inner.OwnerFrameAsync().ConfigureAwait(false);
        return f == null ? null : Humanize.WrapFrame(f, _cursor, _cfg);
    }
}
