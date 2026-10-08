using Microsoft.Playwright;

namespace CloakBrowser.Human;

/// <summary>Options accepted by the humanized action methods on <see cref="HumanPage"/>.</summary>
public sealed class HumanActionOptions
{
    /// <summary>Overall timeout in milliseconds (default 30000; 0 = no limit).</summary>
    public double Timeout { get; set; } = 30000;

    /// <summary>Skip actionability waits and the hit-target check (like Playwright's <c>Force</c>).</summary>
    public bool Force { get; set; }

    /// <summary>Delay in milliseconds between keydown and keyup for press actions.</summary>
    public float? Delay { get; set; }

    /// <summary>Per-call config overrides (snake_case or PascalCase keys), merged on top of the page config.</summary>
    public IReadOnlyDictionary<string, object>? HumanConfig { get; set; }
}

/// <summary>
/// Explicit human-like API over a Playwright <see cref="IPage"/>.
///
/// The transparent wrappers (<c>Humanize.PageAsync</c>, <c>LaunchAsync(Humanize = true)</c>)
/// are the recommended way to humanize; this class exposes the same engine as explicit
/// methods for code that prefers to keep the raw <see cref="IPage"/> untouched. Every call
/// goes through the unified humanize engine: Playwright's selector engine in an isolated
/// world, actionability waits, wheel scrolling, Bezier mouse motion, a hit-target check
/// and human typing. Selectors are resolved in the main frame, non-strict (like
/// <c>page.ClickAsync</c>).
/// </summary>
public sealed class HumanPage
{
    private readonly IPage _page;
    private readonly HumanEngine _engine;

    /// <summary>The underlying raw Playwright page.</summary>
    public IPage Page => _page;

    /// <summary>The page-level humanize config.</summary>
    public HumanConfig Config => _engine.Config;

    /// <summary>Current virtual cursor position.</summary>
    public (double X, double Y) Cursor => (_engine.Cursor.X, _engine.Cursor.Y);

    /// <summary>Wrap <paramref name="page"/>. Prefer <see cref="CreateAsync"/>, which also
    /// places the virtual cursor.</summary>
    public HumanPage(IPage page, HumanConfig? cfg = null)
    {
        _page = page ?? throw new ArgumentNullException(nameof(page));
        _engine = new HumanEngine(page, cfg ?? new HumanConfig(), new CursorPosition());
    }

    /// <summary>Create a <see cref="HumanPage"/> and place the virtual cursor.</summary>
    public static async Task<HumanPage> CreateAsync(IPage page, HumanConfig? cfg = null)
    {
        var hp = new HumanPage(page, cfg);
        try { await hp._engine.EnsureCursorAsync().ConfigureAwait(false); }
        catch (PlaywrightException) { /* viewport not ready yet; done on the first action */ }
        return hp;
    }

    private Target T(string selector) => new(_page.MainFrame, selector);

    private static ActOpts O(HumanActionOptions? o) => o == null
        ? new ActOpts()
        : new ActOpts { Timeout = (float)o.Timeout, Force = o.Force, Delay = o.Delay, HumanConfig = o.HumanConfig };

    // -- navigation ---------------------------------------------------------

    /// <summary>Navigate to a URL (isolated worlds are re-created per document automatically).</summary>
    public Task<IResponse?> GotoAsync(string url, PageGotoOptions? options = null) => _page.GotoAsync(url, options);

    // -- pointer ------------------------------------------------------------

    /// <summary>Human-like click on <paramref name="selector"/>.</summary>
    public Task ClickAsync(string selector, HumanActionOptions? options = null) =>
        _engine.ClickAsync(T(selector), O(options), "HumanPage.ClickAsync");

    /// <summary>Human-like double click (a real mousedown/up x2 sequence).</summary>
    public Task DblClickAsync(string selector, HumanActionOptions? options = null) =>
        _engine.ClickAsync(T(selector), O(options), "HumanPage.DblClickAsync", 2);

    /// <summary>Human-like hover.</summary>
    public Task HoverAsync(string selector, HumanActionOptions? options = null) =>
        _engine.HoverAsync(T(selector), O(options), "HumanPage.HoverAsync");

    /// <summary>Human-like tap (same motion as a click).</summary>
    public Task TapAsync(string selector, HumanActionOptions? options = null) =>
        _engine.TapAsync(T(selector), O(options), "HumanPage.TapAsync");

    /// <summary>Human-like check of a checkbox/radio (no-op if already checked).</summary>
    public Task CheckAsync(string selector, HumanActionOptions? options = null) =>
        _engine.SetCheckedAsync(T(selector), true, O(options), "HumanPage.CheckAsync");

    /// <summary>Human-like uncheck (no-op if already unchecked).</summary>
    public Task UncheckAsync(string selector, HumanActionOptions? options = null) =>
        _engine.SetCheckedAsync(T(selector), false, O(options), "HumanPage.UncheckAsync");

    /// <summary>Click only when the current state differs from <paramref name="checked_"/>.</summary>
    public Task SetCheckedAsync(string selector, bool checked_, HumanActionOptions? options = null) =>
        _engine.SetCheckedAsync(T(selector), checked_, O(options), "HumanPage.SetCheckedAsync");

    /// <summary>Pick options like a person (dropdown: click + arrow keys + Enter; list box: clicks).</summary>
    public Task<IReadOnlyList<string>> SelectOptionAsync(string selector, string[] values, HumanActionOptions? options = null) =>
        _engine.SelectOptionAsync(T(selector),
            values.Select(v => (object)new Dictionary<string, object> { ["valueOrLabel"] = v }).ToList(),
            Array.Empty<IElementHandle>(), O(options), "HumanPage.SelectOptionAsync");

    /// <summary>Human-like drag from the source element to the target element.</summary>
    public Task DragAndDropAsync(string sourceSelector, string targetSelector, HumanActionOptions? options = null) =>
        _engine.DragAsync(T(sourceSelector), T(targetSelector), O(options), "HumanPage.DragAndDropAsync");

    // -- keyboard -----------------------------------------------------------

    /// <summary>Human-like typing into <paramref name="selector"/>; text continues at the end.</summary>
    public Task TypeAsync(string selector, string text, HumanActionOptions? options = null) =>
        _engine.TypeAsync(T(selector), text, O(options), "HumanPage.TypeAsync");

    /// <summary>Same as <see cref="TypeAsync"/> (Playwright's <c>PressSequentially</c>).</summary>
    public Task PressSequentiallyAsync(string selector, string text, HumanActionOptions? options = null) =>
        _engine.TypeAsync(T(selector), text, O(options), "HumanPage.PressSequentiallyAsync");

    /// <summary>Human-like fill: click into the field, select all, delete, type. Date / range /
    /// select-like inputs are set the way a person would; <c>type=color</c> throws.</summary>
    public Task FillAsync(string selector, string value, HumanActionOptions? options = null) =>
        _engine.FillAsync(T(selector), value, O(options), "HumanPage.FillAsync");

    /// <summary>Human-like clear (fill with an empty string).</summary>
    public Task ClearAsync(string selector, HumanActionOptions? options = null) =>
        _engine.FillAsync(T(selector), "", O(options), "HumanPage.ClearAsync");

    /// <summary>Focus the element by clicking it if needed, then press <paramref name="key"/>.</summary>
    public Task PressAsync(string selector, string key, HumanActionOptions? options = null) =>
        _engine.PressAsync(T(selector), key, O(options), "HumanPage.PressAsync");

    /// <summary>Move the cursor over the element, then focus it without a click.</summary>
    public Task FocusAsync(string selector, HumanActionOptions? options = null) =>
        _engine.FocusAsync(T(selector), O(options), "HumanPage.FocusAsync", move: true);

    /// <summary>Wheel-scroll the element into view. Returns true when the element moved.</summary>
    public async Task<bool> ScrollIntoViewIfNeededAsync(string selector, HumanActionOptions? options = null)
    {
        var before = await _page.MainFrame.Locator(selector).First.BoundingBoxAsync(
            new() { Timeout = (float)(options?.Timeout ?? 30000) }).ConfigureAwait(false);
        await _engine.ScrollIntoViewIfNeededAsync(T(selector), O(options), "HumanPage.ScrollIntoViewIfNeededAsync").ConfigureAwait(false);
        var after = await _page.MainFrame.Locator(selector).First.BoundingBoxAsync().ConfigureAwait(false);
        return before != null && after != null && (Math.Abs(before.X - after.X) >= 1 || Math.Abs(before.Y - after.Y) >= 1);
    }

    // -- low level ----------------------------------------------------------

    /// <summary>Move the virtual cursor to absolute (x, y) along a human-like curve.</summary>
    public Task MouseMoveAsync(double x, double y) => _engine.MouseMoveAsync(x, y);

    /// <summary>Move to absolute (x, y) and click there like a person.</summary>
    public Task MouseClickAsync(double x, double y) => _engine.MouseClickAsync(x, y);

    /// <summary>Type into whatever element currently has focus, with human timing.</summary>
    public Task KeyboardTypeAsync(string text) => _engine.KeyboardTypeAsync(text);
}
