using System.Text.RegularExpressions;
using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Transparent humanizing decorator over Playwright's <see cref="ILocator"/>.
///
/// Intercepted (humanized): Click/DblClick/Hover/Tap/Fill/Type/PressSequentially/Press
/// and Check/Uncheck/SetChecked (which route through a humanized click). All other
/// members - assertions, queries, waits, getters - are delegated to the inner locator
/// by the source generator. Locator-returning members are re-wrapped so chaining stays
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

    /// <summary>The CSS/XPath selector this locator was built from (page.Locator(selector)),
    /// or null for chained/GetBy* locators. Drives the isolated-world pre-click reads.</summary>
    internal string? Selector => _selector;

    /// <summary>The original, un-humanized Playwright locator (escape hatch for raw speed).</summary>
    public ILocator Original => _inner;

    /// <summary>Alias of <see cref="Original"/>.</summary>
    public ILocator Inner => _inner;

    private ILocator Wrap(ILocator l, string? selector = null) =>
        Humanize.WrapLocator(l, _cursor, _cfg, selector);

    // -----------------------------------------------------------------------
    // Humanized actions
    // -----------------------------------------------------------------------

    public Task ClickAsync(LocatorClickOptions? options = null) =>
        LocatorHumanizer.ClickAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), _selector);

    public Task DblClickAsync(LocatorDblClickOptions? options = null) =>
        LocatorHumanizer.DblClickAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), _selector);

    public Task HoverAsync(LocatorHoverOptions? options = null) =>
        LocatorHumanizer.HoverAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), _selector);

    public Task TapAsync(LocatorTapOptions? options = null) =>
        LocatorHumanizer.TapAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), _selector);

    public Task FillAsync(string value, LocatorFillOptions? options = null) =>
        LocatorHumanizer.FillAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), value, _selector);

    public Task TypeAsync(string text, LocatorTypeOptions? options = null) =>
        LocatorHumanizer.TypeAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), text, _selector);

    public Task PressSequentiallyAsync(string text, LocatorPressSequentiallyOptions? options = null) =>
        LocatorHumanizer.PressSequentiallyAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), text, _selector);

    public Task PressAsync(string key, LocatorPressOptions? options = null) =>
        LocatorHumanizer.PressAsync(
            _inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options),
            key, OptionReader.Delay(options), _selector);

    public async Task CheckAsync(LocatorCheckOptions? options = null)
    {
        if (_selector == null)
        {
            if (!await _inner.IsCheckedAsync().ConfigureAwait(false))
                await LocatorHumanizer.ClickAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), null).ConfigureAwait(false);
            return;
        }
        var timeout = OptionReader.Timeout(options); var force = OptionReader.Force(options);
        var deadline = Environment.TickCount64 + timeout;
        await LocatorHumanizer.EnsureActionableAsync(_cursor, _selector, Actionability.ChecksCheck,
            Actionability.RemainingMs(deadline), force).ConfigureAwait(false);
        if ((await LocatorHumanizer.SnapshotAsync(_cursor, _selector).ConfigureAwait(false)).Checked != true)
            await LocatorHumanizer.ClickAfterPrecheckAsync(_inner, _cursor, _cfg,
                Actionability.RemainingMs(deadline), force, _selector).ConfigureAwait(false);
    }

    public async Task UncheckAsync(LocatorUncheckOptions? options = null)
    {
        if (_selector == null)
        {
            if (await _inner.IsCheckedAsync().ConfigureAwait(false))
                await LocatorHumanizer.ClickAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), null).ConfigureAwait(false);
            return;
        }
        var timeout = OptionReader.Timeout(options); var force = OptionReader.Force(options);
        var deadline = Environment.TickCount64 + timeout;
        await LocatorHumanizer.EnsureActionableAsync(_cursor, _selector, Actionability.ChecksCheck,
            Actionability.RemainingMs(deadline), force).ConfigureAwait(false);
        if ((await LocatorHumanizer.SnapshotAsync(_cursor, _selector).ConfigureAwait(false)).Checked == true)
            await LocatorHumanizer.ClickAfterPrecheckAsync(_inner, _cursor, _cfg,
                Actionability.RemainingMs(deadline), force, _selector).ConfigureAwait(false);
    }

    public async Task SetCheckedAsync(bool checkedState, LocatorSetCheckedOptions? options = null)
    {
        if (_selector == null)
        {
            bool current;
            try { current = await _inner.IsCheckedAsync().ConfigureAwait(false); }
            catch (System.Exception) { current = !checkedState; }
            if (current != checkedState)
                await LocatorHumanizer.ClickAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), null).ConfigureAwait(false);
            return;
        }
        var timeout = OptionReader.Timeout(options); var force = OptionReader.Force(options);
        var deadline = Environment.TickCount64 + timeout;
        await LocatorHumanizer.EnsureActionableAsync(_cursor, _selector, Actionability.ChecksCheck,
            Actionability.RemainingMs(deadline), force).ConfigureAwait(false);
        var directCurrent = (await LocatorHumanizer.SnapshotAsync(_cursor, _selector).ConfigureAwait(false)).Checked == true;
        if (directCurrent != checkedState)
            await LocatorHumanizer.ClickAfterPrecheckAsync(_inner, _cursor, _cfg,
                Actionability.RemainingMs(deadline), force, _selector).ConfigureAwait(false);
    }

    public async Task DragToAsync(ILocator target, LocatorDragToOptions? options = null)
    {
        var realTarget = target is HumanizedLocator h ? h.Original : target;
        var srcBox = await _inner.BoundingBoxAsync().ConfigureAwait(false);
        var tgtBox = await realTarget.BoundingBoxAsync().ConfigureAwait(false);
        if (srcBox == null || tgtBox == null)
        {
            await _inner.DragToAsync(realTarget, options).ConfigureAwait(false);
            return;
        }
        await _cursor.EnsureInitializedAsync(_cfg).ConfigureAwait(false);
        double sx = srcBox.X + srcBox.Width / 2, sy = srcBox.Y + srcBox.Height / 2;
        double tx = tgtBox.X + tgtBox.Width / 2, ty = tgtBox.Y + tgtBox.Height / 2;
        await HumanMouse.HumanMoveAsync(_cursor.RawMouse, _cursor.X, _cursor.Y, sx, sy, _cfg).ConfigureAwait(false);
        _cursor.Set(sx, sy);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(100, 200)).ConfigureAwait(false);
        await _cursor.RawMouseDownAsync().ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(80, 150)).ConfigureAwait(false);
        await HumanMouse.HumanMoveAsync(_cursor.RawMouse, _cursor.X, _cursor.Y, tx, ty, _cfg).ConfigureAwait(false);
        _cursor.Set(tx, ty);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(80, 150)).ConfigureAwait(false);
        await _cursor.RawMouseUpAsync().ConfigureAwait(false);
    }

    // --- SelectOptionAsync (all ILocator overloads) -------------------------
    // Human pre-roll = curved hover + pause, then delegate the real select (native
    // <select> popups can't be driven by synthetic mouse events). Unwrap any
    // HumanizedElementHandle args so Playwright sees the raw handles.

    public async Task<IReadOnlyList<string>> SelectOptionAsync(string values, LocatorSelectOptionOptions? options = null)
    {
        await LocatorHumanizer.SelectOptionPrologueAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), _selector).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(values, options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(IElementHandle values, LocatorSelectOptionOptions? options = null)
    {
        await LocatorHumanizer.SelectOptionPrologueAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), _selector).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(Unwrap(values), options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(IEnumerable<string> values, LocatorSelectOptionOptions? options = null)
    {
        await LocatorHumanizer.SelectOptionPrologueAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), _selector).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(values, options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(SelectOptionValue values, LocatorSelectOptionOptions? options = null)
    {
        await LocatorHumanizer.SelectOptionPrologueAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), _selector).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(values, options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(IEnumerable<IElementHandle> values, LocatorSelectOptionOptions? options = null)
    {
        await LocatorHumanizer.SelectOptionPrologueAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), _selector).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(values.Select(Unwrap), options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(IEnumerable<SelectOptionValue> values, LocatorSelectOptionOptions? options = null)
    {
        await LocatorHumanizer.SelectOptionPrologueAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), _selector).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(values, options).ConfigureAwait(false);
    }

    // --- ClearAsync ---------------------------------------------------------
    // Human path: focus (humanized click if needed) + select-all + Backspace,
    // instead of an instant value reset.

    public Task ClearAsync(LocatorClearOptions? options = null) =>
        LocatorHumanizer.ClearAsync(_inner, _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), _selector);

    private static IElementHandle Unwrap(IElementHandle handle) =>
        handle is HumanizedElementHandle h ? h.Original : handle;

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
}
