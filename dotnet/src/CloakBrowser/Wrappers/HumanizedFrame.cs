using System.Text.RegularExpressions;
using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Transparent humanizing decorator over Playwright's <see cref="IFrame"/>.
///
/// Frames have no Mouse/Keyboard of their own (those belong to the page), so the
/// selector actions are humanized by resolving <c>frame.Locator(selector)</c> and
/// running the shared locator humanizer with the page's cursor. Locator/frame
/// returning members are re-wrapped; everything else is delegated by the generator.
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
    private IFrame Wrap(IFrame f) => Humanize.WrapFrame(f, _cursor, _cfg);
    private ILocator Loc(string selector) => _inner.Locator(selector);

    // -----------------------------------------------------------------------
    // Humanized selector actions (routed through the locator humanizer).
    // -----------------------------------------------------------------------

    public Task ClickAsync(string selector, FrameClickOptions? options = null) =>
        LocatorHumanizer.ClickAsync(Loc(selector), _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options));

    public Task DblClickAsync(string selector, FrameDblClickOptions? options = null) =>
        LocatorHumanizer.DblClickAsync(Loc(selector), _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options));

    public Task HoverAsync(string selector, FrameHoverOptions? options = null) =>
        LocatorHumanizer.HoverAsync(Loc(selector), _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options));

    public Task TapAsync(string selector, FrameTapOptions? options = null) =>
        LocatorHumanizer.TapAsync(Loc(selector), _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options));

    public Task FillAsync(string selector, string value, FrameFillOptions? options = null) =>
        LocatorHumanizer.FillAsync(Loc(selector), _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), value);

    public Task TypeAsync(string selector, string text, FrameTypeOptions? options = null) =>
        LocatorHumanizer.TypeAsync(Loc(selector), _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), text);

    public Task PressAsync(string selector, string key, FramePressOptions? options = null) =>
        LocatorHumanizer.PressAsync(Loc(selector), _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options), key);

    public async Task CheckAsync(string selector, FrameCheckOptions? options = null)
    {
        if (!await _inner.IsCheckedAsync(selector).ConfigureAwait(false))
            await LocatorHumanizer.ClickAsync(Loc(selector), _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options)).ConfigureAwait(false);
    }

    public async Task UncheckAsync(string selector, FrameUncheckOptions? options = null)
    {
        if (await _inner.IsCheckedAsync(selector).ConfigureAwait(false))
            await LocatorHumanizer.ClickAsync(Loc(selector), _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options)).ConfigureAwait(false);
    }

    public async Task SetCheckedAsync(string selector, bool checkedState, FrameSetCheckedOptions? options = null)
    {
        bool current;
        try { current = await _inner.IsCheckedAsync(selector).ConfigureAwait(false); }
        catch (System.Exception) { current = !checkedState; }
        if (current != checkedState)
            await LocatorHumanizer.ClickAsync(Loc(selector), _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options)).ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // SelectOptionAsync (all 6 IFrame overloads) - humanized pre-roll.
    // Mirrors Python _frame_select_option: hover the <select> (curved move) +
    // pause, then delegate the real select (native popups can't be mouse-driven).
    // Unwrap any HumanizedElementHandle args so Playwright sees raw handles.
    // -----------------------------------------------------------------------

    private static IElementHandle Unwrap(IElementHandle h) => h is HumanizedElementHandle w ? w.Original : h;

    private Task SelectPrologueAsync(string selector, FrameSelectOptionOptions? options) =>
        LocatorHumanizer.SelectOptionPrologueAsync(Loc(selector), _cursor, _cfg, OptionReader.Timeout(options), OptionReader.Force(options));

    public async Task<IReadOnlyList<string>> SelectOptionAsync(string selector, string values, FrameSelectOptionOptions? options = null)
    {
        await SelectPrologueAsync(selector, options).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(selector, values, options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IElementHandle values, FrameSelectOptionOptions? options = null)
    {
        await SelectPrologueAsync(selector, options).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(selector, Unwrap(values), options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IEnumerable<string> values, FrameSelectOptionOptions? options = null)
    {
        await SelectPrologueAsync(selector, options).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(selector, values, options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(string selector, SelectOptionValue values, FrameSelectOptionOptions? options = null)
    {
        await SelectPrologueAsync(selector, options).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(selector, values, options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IEnumerable<IElementHandle> values, FrameSelectOptionOptions? options = null)
    {
        await SelectPrologueAsync(selector, options).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(selector, values.Select(Unwrap), options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IEnumerable<SelectOptionValue> values, FrameSelectOptionOptions? options = null)
    {
        await SelectPrologueAsync(selector, options).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(selector, values, options).ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // DragAndDropAsync - humanized drag. Mirrors Python _frame_drag_and_drop:
    // resolve source/target boxes via frame locators; if both present, drive a
    // curved press-move-release with the page cursor; else delegate raw.
    // -----------------------------------------------------------------------

    public async Task DragAndDropAsync(string source, string target, FrameDragAndDropOptions? options = null)
    {
        LocatorBoundingBoxResult? srcBox, tgtBox;
        try
        {
            srcBox = await _inner.Locator(source).BoundingBoxAsync().ConfigureAwait(false);
            tgtBox = await _inner.Locator(target).BoundingBoxAsync().ConfigureAwait(false);
        }
        catch (System.Exception)
        {
            srcBox = tgtBox = null;
        }

        if (srcBox == null || tgtBox == null)
        {
            await _inner.DragAndDropAsync(source, target, options).ConfigureAwait(false);
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

    // -----------------------------------------------------------------------
    // Locator-returning members - re-wrap.
    // -----------------------------------------------------------------------

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
}
