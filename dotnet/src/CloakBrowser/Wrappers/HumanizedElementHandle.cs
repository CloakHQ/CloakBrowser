using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Transparent humanizing decorator over Playwright's <see cref="IElementHandle"/>.
///
/// ElementHandle is a legacy, lower-level surface (Playwright itself recommends
/// <see cref="ILocator"/>). For completeness this wrapper humanizes the common
/// interaction methods (click/dblclick/hover/tap/fill/type/press/check/uncheck) by
/// driving the shared cursor to the handle's bounding box, so the ElementHandle path
/// does NOT silently bypass humanization. Handle-returning queries are re-wrapped;
/// everything else is delegated by the generator.
///
/// Recommendation: prefer Locator / selector-based methods - they get the full
/// actionability + isolated-world stealth path.
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

    private async Task<(double X, double Y, bool IsInput)> MoveToAsync(double timeout, bool force)
    {
        await _cursor.EnsureInitializedAsync(_cfg).ConfigureAwait(false);
        if (!force)
        {
            try { await _inner.ScrollIntoViewIfNeededAsync(new ElementHandleScrollIntoViewIfNeededOptions { Timeout = (float)timeout }).ConfigureAwait(false); }
            catch (System.Exception) { /* best effort */ }
        }
        var box = await _inner.BoundingBoxAsync().ConfigureAwait(false);
        bool isInput;
        try
        {
            isInput = await _inner.EvaluateAsync<bool>(
                @"el => { const t = el.tagName.toLowerCase();
                    return t==='input'||t==='textarea'||el.getAttribute('contenteditable')==='true'; }")
                .ConfigureAwait(false);
        }
        catch (System.Exception) { isInput = false; }

        var bb = box == null ? new BoundingBox(_cursor.X, _cursor.Y, 1, 1)
                             : new BoundingBox(box.X, box.Y, box.Width, box.Height);
        var target = HumanMouse.ClickTarget(bb, isInput, _cfg);
        await HumanMouse.HumanMoveAsync(_cursor.RawMouse, _cursor.X, _cursor.Y, target.X, target.Y, _cfg).ConfigureAwait(false);
        _cursor.Set(target.X, target.Y);
        return (target.X, target.Y, isInput);
    }

    public async Task ClickAsync(ElementHandleClickOptions? options = null)
    {
        var t = await MoveToAsync(OptionReader.Timeout(options), OptionReader.Force(options)).ConfigureAwait(false);
        await HumanMouse.HumanClickAsync(_cursor.RawMouse, t.IsInput, _cfg).ConfigureAwait(false);
    }

    public async Task DblClickAsync(ElementHandleDblClickOptions? options = null)
    {
        await MoveToAsync(OptionReader.Timeout(options), OptionReader.Force(options)).ConfigureAwait(false);
        await _cursor.RawMouseDownAsync(2).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(30, 60)).ConfigureAwait(false);
        await _cursor.RawMouseUpAsync(2).ConfigureAwait(false);
    }

    public Task HoverAsync(ElementHandleHoverOptions? options = null) =>
        MoveToAsync(OptionReader.Timeout(options), OptionReader.Force(options));

    public Task TapAsync(ElementHandleTapOptions? options = null) =>
        ClickAsync(new ElementHandleClickOptions
        {
            Force = OptionReader.Force(options),
            Timeout = (float)OptionReader.Timeout(options),
        });

    public async Task FillAsync(string value, ElementHandleFillOptions? options = null)
    {
        await ClickAsync(new ElementHandleClickOptions { Force = OptionReader.Force(options), Timeout = (float)OptionReader.Timeout(options) }).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(100, 250)).ConfigureAwait(false);
        await _cursor.SelectAllAsync().ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(30, 80)).ConfigureAwait(false);
        await _cursor.PressAsync("Backspace").ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(50, 150)).ConfigureAwait(false);
        await _cursor.HumanTypeAsync(value, _cfg).ConfigureAwait(false);
    }

    public async Task TypeAsync(string text, ElementHandleTypeOptions? options = null)
    {
        await _inner.FocusAsync().ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(50, 150)).ConfigureAwait(false);
        await _cursor.HumanTypeAsync(text, _cfg).ConfigureAwait(false);
    }

    public async Task PressAsync(string key, ElementHandlePressOptions? options = null)
    {
        await _inner.FocusAsync().ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(50, 150)).ConfigureAwait(false);
        await _cursor.PressAsync(key).ConfigureAwait(false);
    }

    public async Task CheckAsync(ElementHandleCheckOptions? options = null)
    {
        if (!await _inner.IsCheckedAsync().ConfigureAwait(false))
            await ClickAsync(new ElementHandleClickOptions { Force = OptionReader.Force(options), Timeout = (float)OptionReader.Timeout(options) }).ConfigureAwait(false);
    }

    public async Task UncheckAsync(ElementHandleUncheckOptions? options = null)
    {
        if (await _inner.IsCheckedAsync().ConfigureAwait(false))
            await ClickAsync(new ElementHandleClickOptions { Force = OptionReader.Force(options), Timeout = (float)OptionReader.Timeout(options) }).ConfigureAwait(false);
    }

    public async Task SetCheckedAsync(bool checkedState, ElementHandleSetCheckedOptions? options = null)
    {
        bool current;
        try { current = await _inner.IsCheckedAsync().ConfigureAwait(false); }
        catch (System.Exception) { current = !checkedState; }
        if (current != checkedState)
            await ClickAsync(new ElementHandleClickOptions { Force = OptionReader.Force(options), Timeout = (float)OptionReader.Timeout(options) }).ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // SelectOptionAsync (all 6 IElementHandle overloads) - humanized pre-roll.
    // Mirrors Python _human_el_select_option: move the cursor to the <select>
    // (curved), click, pause, then delegate the real select (native popups can't
    // be mouse-driven). Unwrap any HumanizedElementHandle args.
    // -----------------------------------------------------------------------

    private static IElementHandle Unwrap(IElementHandle h) => h is HumanizedElementHandle w ? w.Original : h;

    private async Task SelectPrologueAsync(ElementHandleSelectOptionOptions? options)
    {
        var t = await MoveToAsync(OptionReader.Timeout(options), OptionReader.Force(options)).ConfigureAwait(false);
        await HumanMouse.HumanClickAsync(_cursor.RawMouse, t.IsInput, _cfg).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(100, 300)).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(string values, ElementHandleSelectOptionOptions? options = null)
    {
        await SelectPrologueAsync(options).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(values, options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(IElementHandle values, ElementHandleSelectOptionOptions? options = null)
    {
        await SelectPrologueAsync(options).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(Unwrap(values), options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(IEnumerable<string> values, ElementHandleSelectOptionOptions? options = null)
    {
        await SelectPrologueAsync(options).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(values, options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(SelectOptionValue values, ElementHandleSelectOptionOptions? options = null)
    {
        await SelectPrologueAsync(options).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(values, options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(IEnumerable<IElementHandle> values, ElementHandleSelectOptionOptions? options = null)
    {
        await SelectPrologueAsync(options).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(values.Select(Unwrap), options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(IEnumerable<SelectOptionValue> values, ElementHandleSelectOptionOptions? options = null)
    {
        await SelectPrologueAsync(options).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(values, options).ConfigureAwait(false);
    }

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
}
