using System.Text.RegularExpressions;
using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Transparent humanizing decorator over Playwright's <see cref="IPage"/>.
///
/// Selector-based interaction methods (Click/Fill/Type/Hover/Press/Tap/Check/...) are
/// routed through the selector-driven <see cref="HumanPage"/> engine. <c>Mouse</c> and
/// <c>Keyboard</c> return humanized wrappers; <c>Locator</c>/<c>GetBy*</c>/frames return
/// re-wrapped objects so the whole chain stays humanized. Everything else is delegated
/// to the inner page by the source generator.
/// </summary>
[GenerateInterfaceDelegation(typeof(IPage))]
public sealed partial class HumanizedPage : IPage
{
    private readonly IPage _inner;
    private readonly HumanCursor _cursor;
    private readonly HumanConfig _cfg;
    private readonly HumanPage _human;
    private readonly HumanizedMouse _mouse;
    private readonly HumanizedKeyboard _keyboard;

    internal HumanizedPage(IPage inner, HumanCursor cursor, HumanConfig cfg)
    {
        _inner = inner;
        _cursor = cursor;
        _cfg = cfg;
        _human = new HumanPage(inner, cfg);
        _mouse = new HumanizedMouse(inner.Mouse, cursor, cfg);
        _keyboard = new HumanizedKeyboard(inner.Keyboard, cursor, cfg);
    }

    /// <summary>The original, un-humanized Playwright page (escape hatch for raw speed).</summary>
    public IPage Original => _inner;

    /// <summary>Alias of <see cref="Original"/>.</summary>
    public IPage Inner => _inner;

    private HumanActionOptions Opt(object? options) => new()
    {
        Timeout = OptionReader.Timeout(options),
        Force = OptionReader.Force(options),
    };

    private ILocator Wrap(ILocator l) => Humanize.WrapLocator(l, _cursor, _cfg);
    private IFrame Wrap(IFrame f) => Humanize.WrapFrame(f, _cursor, _cfg);

    // -----------------------------------------------------------------------
    // Humanized wrappers for nested objects
    // -----------------------------------------------------------------------

    public IMouse Mouse => _mouse;
    public IKeyboard Keyboard => _keyboard;

    // -----------------------------------------------------------------------
    // Humanized selector actions
    // -----------------------------------------------------------------------

    public Task ClickAsync(string selector, PageClickOptions? options = null) =>
        _human.ClickAsync(selector, Opt(options));

    public Task DblClickAsync(string selector, PageDblClickOptions? options = null) =>
        _human.DblClickAsync(selector, Opt(options));

    public Task HoverAsync(string selector, PageHoverOptions? options = null) =>
        _human.HoverAsync(selector, Opt(options));

    public Task TapAsync(string selector, PageTapOptions? options = null) =>
        _human.TapAsync(selector, Opt(options));

    public Task FillAsync(string selector, string value, PageFillOptions? options = null) =>
        _human.FillAsync(selector, value, Opt(options));

    public Task TypeAsync(string selector, string text, PageTypeOptions? options = null) =>
        _human.TypeAsync(selector, text, Opt(options));

    public Task PressAsync(string selector, string key, PagePressOptions? options = null) =>
        _human.PressAsync(selector, key, Opt(options));

    public Task CheckAsync(string selector, PageCheckOptions? options = null) =>
        _human.CheckAsync(selector, Opt(options));

    public Task UncheckAsync(string selector, PageUncheckOptions? options = null) =>
        _human.UncheckAsync(selector, Opt(options));

    public Task SetCheckedAsync(string selector, bool checkedState, PageSetCheckedOptions? options = null) =>
        _human.SetCheckedAsync(selector, checkedState, Opt(options));

    public Task FocusAsync(string selector, PageFocusOptions? options = null) =>
        _human.FocusAsync(selector, Opt(options));

    public Task DragAndDropAsync(string source, string target, PageDragAndDropOptions? options = null) =>
        _human.DragAndDropAsync(source, target, Opt(options));

    public Task<IReadOnlyList<string>> SelectOptionAsync(string selector, string values, PageSelectOptionOptions? options = null) =>
        _human.SelectOptionAsync(selector, new[] { values }, Opt(options));

    public Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IEnumerable<string> values, PageSelectOptionOptions? options = null) =>
        _human.SelectOptionAsync(selector, values.ToArray(), Opt(options));

    // SelectOption overloads taking handles / SelectOptionValue have no humanized
    // analogue; hover then delegate so the dropdown still gets a human approach.
    public async Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IElementHandle values, PageSelectOptionOptions? options = null)
    {
        await _human.HoverAsync(selector, Opt(options)).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(selector, Unwrap(values), options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IEnumerable<IElementHandle> values, PageSelectOptionOptions? options = null)
    {
        await _human.HoverAsync(selector, Opt(options)).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(selector, values.Select(Unwrap), options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(string selector, SelectOptionValue values, PageSelectOptionOptions? options = null)
    {
        await _human.HoverAsync(selector, Opt(options)).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(selector, values, options).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<string>> SelectOptionAsync(string selector, IEnumerable<SelectOptionValue> values, PageSelectOptionOptions? options = null)
    {
        await _human.HoverAsync(selector, Opt(options)).ConfigureAwait(false);
        return await _inner.SelectOptionAsync(selector, values, options).ConfigureAwait(false);
    }

    private static IElementHandle Unwrap(IElementHandle h) => h is HumanizedElementHandle hh ? hh.Original : h;

    // -----------------------------------------------------------------------
    // Locator-returning members - re-wrap.
    // -----------------------------------------------------------------------

    public ILocator Locator(string selector, PageLocatorOptions? options = null) => Wrap(_inner.Locator(selector, options));
    public ILocator GetByAltText(string text, PageGetByAltTextOptions? options = null) => Wrap(_inner.GetByAltText(text, options));
    public ILocator GetByAltText(Regex text, PageGetByAltTextOptions? options = null) => Wrap(_inner.GetByAltText(text, options));
    public ILocator GetByLabel(string text, PageGetByLabelOptions? options = null) => Wrap(_inner.GetByLabel(text, options));
    public ILocator GetByLabel(Regex text, PageGetByLabelOptions? options = null) => Wrap(_inner.GetByLabel(text, options));
    public ILocator GetByPlaceholder(string text, PageGetByPlaceholderOptions? options = null) => Wrap(_inner.GetByPlaceholder(text, options));
    public ILocator GetByPlaceholder(Regex text, PageGetByPlaceholderOptions? options = null) => Wrap(_inner.GetByPlaceholder(text, options));
    public ILocator GetByRole(AriaRole role, PageGetByRoleOptions? options = null) => Wrap(_inner.GetByRole(role, options));
    public ILocator GetByTestId(string testId) => Wrap(_inner.GetByTestId(testId));
    public ILocator GetByTestId(Regex testId) => Wrap(_inner.GetByTestId(testId));
    public ILocator GetByText(string text, PageGetByTextOptions? options = null) => Wrap(_inner.GetByText(text, options));
    public ILocator GetByText(Regex text, PageGetByTextOptions? options = null) => Wrap(_inner.GetByText(text, options));
    public ILocator GetByTitle(string text, PageGetByTitleOptions? options = null) => Wrap(_inner.GetByTitle(text, options));
    public ILocator GetByTitle(Regex text, PageGetByTitleOptions? options = null) => Wrap(_inner.GetByTitle(text, options));

    // -----------------------------------------------------------------------
    // Frame-returning members - re-wrap.
    // -----------------------------------------------------------------------

    public IReadOnlyList<IFrame> Frames => Humanize.WrapFrames(_inner.Frames, _cursor, _cfg);
    public IFrame MainFrame => Wrap(_inner.MainFrame);
    public IFrame? Frame(string name) { var f = _inner.Frame(name); return f == null ? null : Wrap(f); }
    public IFrame? FrameByUrl(string url) { var f = _inner.FrameByUrl(url); return f == null ? null : Wrap(f); }
    public IFrame? FrameByUrl(Regex url) { var f = _inner.FrameByUrl(url); return f == null ? null : Wrap(f); }
    public IFrame? FrameByUrl(System.Func<string, bool> url) { var f = _inner.FrameByUrl(url); return f == null ? null : Wrap(f); }

    // -----------------------------------------------------------------------
    // Navigation - invalidate the isolated world after a navigation.
    // -----------------------------------------------------------------------

    public async Task<IResponse?> GotoAsync(string url, PageGotoOptions? options = null)
    {
        var resp = await _inner.GotoAsync(url, options).ConfigureAwait(false);
        _cursor.InvalidateStealth();
        return resp;
    }
}
