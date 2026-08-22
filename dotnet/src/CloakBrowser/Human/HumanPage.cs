using System.Runtime.InteropServices;
using Microsoft.Playwright;

namespace CloakBrowser.Human;

/// <summary>Options accepted by the humanized action methods on <see cref="HumanPage"/>.</summary>
public sealed class HumanActionOptions
{
    /// <summary>Overall timeout in milliseconds (default 30000).</summary>
    public double Timeout { get; set; } = 30000;

    /// <summary>Skip pre-actionability and coverage rejection; exact target identity remains enforced.</summary>
    public bool Force { get; set; }

    /// <summary>Delay in milliseconds between keydown and keyup for press actions.</summary>
    public float? Delay { get; set; }

    /// <summary>Per-call config overrides (snake_case or PascalCase keys), merged on top of the page config.</summary>
    public IReadOnlyDictionary<string, object>? HumanConfig { get; set; }
}

/// <summary>
/// A human-like wrapper around a Playwright <see cref="IPage"/>.
///
/// .NET's Playwright exposes sealed interfaces (<see cref="IPage"/>, <see cref="ILocator"/>,
/// etc.) that cannot be monkey-patched the way the Python/JS implementations replace
/// methods at runtime. Instead, this wrapper exposes the same humanized behaviors as
/// explicit methods. The underlying real page is always available via <see cref="Page"/>
/// for anything not covered here.
///
/// Direct behavioral port of <c>patch_page</c> in <c>cloakbrowser/human/__init__.py</c>:
/// every action runs Playwright-style actionability checks, a Bezier-curve mouse
/// approach with optional scroll-into-view, pointer-events verification, and human
/// typing through the CDP isolated world / dispatchKeyEvent stealth path.
/// </summary>
public sealed class HumanPage
{
    private static readonly bool IsMac = RuntimeInformation.IsOSPlatform(OSPlatform.OSX);
    private static readonly string SelectAll = IsMac ? "Meta+a" : "Control+a";

    private readonly IPage _page;
    private readonly HumanConfig _cfg;
    private readonly CursorState _cursor = new();

    private readonly IRawMouse _rawMouse;
    private readonly IRawKeyboard _rawKeyboard;
    private readonly IRawScrollPage _scrollPage;
    private readonly IRawEvaluator _evaluator;

    private IsolatedWorld? _stealth;
    private IRawCdpSession? _cdpSession;
    private bool _stealthInitialized;

    /// <summary>The underlying real Playwright page.</summary>
    public IPage Page => _page;

    /// <summary>The resolved behavior configuration for this page.</summary>
    public HumanConfig Config => _cfg;

    /// <summary>The current virtual cursor position (x, y).</summary>
    public (double X, double Y) Cursor => (_cursor.X, _cursor.Y);

    /// <summary>Create a humanized wrapper. Use <see cref="CreateAsync(IPage, HumanConfig?)"/> for the
    /// stealth-enabled variant (recommended).</summary>
    public HumanPage(IPage page, HumanConfig? cfg = null)
    {
        _page = page;
        _cfg = cfg ?? new HumanConfig();
        _rawMouse = new PlaywrightRawMouse(page.Mouse);
        _rawKeyboard = new PlaywrightRawKeyboard(page.Keyboard);
        _scrollPage = new PlaywrightScrollPage(page, GetStealthRequiredAsync);
        _evaluator = new PlaywrightEvaluator(page);

        // Invalidate the isolated world on any main-frame nav, not just goto, so
        // click/form navigations don't leave it bound to a stale doc (#507).
        _page.FrameNavigated += (_, frame) =>
        {
            if (frame == _page.MainFrame) _stealth?.Invalidate();
        };
    }

    /// <summary>
    /// Create a humanized page and initialize the CDP isolated world + dispatchKeyEvent
    /// stealth path. Selector DOM reads fail explicitly when the isolated world is unavailable.
    /// </summary>
    public static async Task<HumanPage> CreateAsync(IPage page, HumanConfig? cfg = null)
    {
        var hp = new HumanPage(page, cfg);
        await hp.InitStealthAsync().ConfigureAwait(false);
        await hp.InitCursorAsync().ConfigureAwait(false);
        return hp;
    }

    private async Task InitStealthAsync()
    {
        if (_stealthInitialized) return;
        _stealthInitialized = true;
        try
        {
            _stealth = new IsolatedWorld(_page);
            var session = await _stealth.GetCdpSessionAsync().ConfigureAwait(false);
            _cdpSession = new PlaywrightCdpSession(session);
        }
        catch (Exception)
        {
            _stealth = null;
            _cdpSession = null;
            CloakLog.Debug("Could not create CDP session - stealth features disabled");
        }
    }

    private async Task InitCursorAsync()
    {
        // Initialize cursor immediately so it doesn't visibly jump from (0,0).
        _cursor.X = HumanRandom.Rand(_cfg.InitialCursorX.Min, _cfg.InitialCursorX.Max);
        _cursor.Y = HumanRandom.Rand(_cfg.InitialCursorY.Min, _cfg.InitialCursorY.Max);
        try
        {
            await _rawMouse.MoveAsync(_cursor.X, _cursor.Y).ConfigureAwait(false);
            _cursor.Initialized = true;
        }
        catch (Exception) { /* viewport may not be ready yet */ }
    }

    private async Task EnsureCursorInitAsync()
    {
        if (!_cursor.Initialized)
        {
            _cursor.X = HumanRandom.Rand(_cfg.InitialCursorX.Min, _cfg.InitialCursorX.Max);
            _cursor.Y = HumanRandom.Rand(_cfg.InitialCursorY.Min, _cfg.InitialCursorY.Max);
            await _rawMouse.MoveAsync(_cursor.X, _cursor.Y).ConfigureAwait(false);
            _cursor.Initialized = true;
        }
    }

    private HumanConfig MergeCfg(HumanActionOptions? opts) =>
        opts?.HumanConfig == null ? _cfg : _cfg.With(opts.HumanConfig);

    private static double RemainingMs(double deadline) => Actionability.RemainingMs(deadline);

    private async Task<IsolatedWorld> GetStealthRequiredAsync()
    {
        await InitStealthAsync().ConfigureAwait(false);
        return _stealth ?? throw new StealthWorldUnavailableError();
    }

    private async Task<StealthSnapshot> SelectorSnapshotAsync(string selector)
    {
        var world = await GetStealthRequiredAsync().ConfigureAwait(false);
        var (status, snapshot) = await StealthDom.SnapshotAsync(world, selector).ConfigureAwait(false);
        return status switch
        {
            StealthStatus.Ok when snapshot != null => snapshot.Value,
            StealthStatus.NotFound => throw new ElementNotAttachedError(selector),
            StealthStatus.Unsupported => throw new UnsupportedHumanizeSelectorError(selector),
            _ => throw new StealthEvaluationError(selector),
        };
    }

    private async Task<bool> IsSelectorFocusedAsync(string selector) =>
        (await SelectorSnapshotAsync(selector).ConfigureAwait(false)).Focused;

    private async Task<BoundingBox?> GetBoxAsync(string selector, double timeoutMs)
    {
        var world = await GetStealthRequiredAsync().ConfigureAwait(false);
        double deadline = Environment.TickCount64 + Math.Max(0, timeoutMs);
        var result = await StealthDom.BoxAsync(world, selector).ConfigureAwait(false);
        while ((result.Status == StealthStatus.NotFound || result.Status == StealthStatus.EvaluationFailed)
            && Environment.TickCount64 < deadline)
        {
            await Task.Delay(50).ConfigureAwait(false);
            result = await StealthDom.BoxAsync(world, selector).ConfigureAwait(false);
        }

        return result.Status switch
        {
            StealthStatus.Ok when result.Target != null => result.Target.Value.Box,
            StealthStatus.NotFound => null,
            StealthStatus.Unsupported => throw new UnsupportedHumanizeSelectorError(selector),
            _ => throw new StealthEvaluationError(selector),
        };
    }

    // Thread the page's isolated world into the shared actionability helpers.
    private async Task EnsureActionableWorldAsync(
        string selector, IReadOnlySet<string> checks, double timeoutMs, bool force)
    {
        var world = await GetStealthRequiredAsync().ConfigureAwait(false);
        await Actionability.EnsureActionableAsync(
            _page, selector, checks, timeoutMs, force, world).ConfigureAwait(false);
    }

    private async Task EnsureStableWorldAsync(string selector, double timeoutMs)
    {
        var world = await GetStealthRequiredAsync().ConfigureAwait(false);
        await Actionability.EnsureStableAsync(_page, selector, timeoutMs, world).ConfigureAwait(false);
    }

    private async Task CheckPointerEventsWorldAsync(
        string selector, int targetId, int gen, double x, double y, double timeoutMs, bool force)
    {
        if (force)
            return;
        var world = await GetStealthRequiredAsync().ConfigureAwait(false);
        await Actionability.CheckPointerEventsAsync(
            _page, selector, targetId, gen, x, y, timeoutMs, world).ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // Navigation
    // -----------------------------------------------------------------------

    /// <summary>Navigate to a URL and invalidate the isolated world afterward.</summary>
    public async Task<IResponse?> GotoAsync(string url, PageGotoOptions? options = null)
    {
        var response = await _page.GotoAsync(url, options).ConfigureAwait(false);
        _stealth?.Invalidate();
        return response;
    }

    // -----------------------------------------------------------------------
    // Click
    // -----------------------------------------------------------------------

    /// <summary>Human-like click on <paramref name="selector"/>.</summary>
    public Task ClickAsync(string selector, HumanActionOptions? options = null) =>
        ClickInternalAsync(selector, options, skipChecks: false);

    private async Task ClickInternalAsync(string selector, HumanActionOptions? options, bool skipChecks)
    {
        await EnsureCursorInitAsync().ConfigureAwait(false);
        var callCfg = MergeCfg(options);
        double timeout = options?.Timeout ?? 30000;
        bool force = options?.Force ?? false;
        double deadline = Environment.TickCount64 + timeout;

        if (!force && !skipChecks)
            await EnsureActionableWorldAsync(selector, Actionability.ChecksClick, RemainingMs(deadline), force).ConfigureAwait(false);
        if (callCfg.IdleBetweenActions)
            await HumanMouse.HumanIdleAsync(_rawMouse, HumanRandom.Rand(callCfg.IdleBetweenDuration.Min, callCfg.IdleBetweenDuration.Max), _cursor.X, _cursor.Y, callCfg).ConfigureAwait(false);

        var scroll = await HumanScroll.HumanScrollIntoViewAsync(
            _scrollPage, _rawMouse, () => GetBoxAsync(selector, RemainingMs(deadline)),
            _cursor.X, _cursor.Y, callCfg).ConfigureAwait(false);
        _cursor.X = scroll.CursorX;
        _cursor.Y = scroll.CursorY;

        if (!force && scroll.DidScroll)
        {
            await EnsureStableWorldAsync(selector, RemainingMs(deadline)).ConfigureAwait(false);
            // Waiting for the reflow to settle can push the element back out of
            // view, and scrolling once before the wait is not enough: the click
            // coords would land outside the viewport and hit nothing (#329).
            var rescroll = await HumanScroll.HumanScrollIntoViewAsync(
                _scrollPage, _rawMouse, () => GetBoxAsync(selector, RemainingMs(deadline)),
                _cursor.X, _cursor.Y, callCfg).ConfigureAwait(false);
            _cursor.X = rescroll.CursorX;
            _cursor.Y = rescroll.CursorY;
        }

        var snapshot = await SelectorSnapshotAsync(selector).ConfigureAwait(false);
        var box = snapshot.Box ?? throw new ElementNotVisibleError(selector);
        var target = HumanMouse.ClickTarget(box, snapshot.IsInput, callCfg);
        await HumanMouse.HumanMoveAsync(
            _rawMouse, _cursor.X, _cursor.Y, target.X, target.Y, callCfg).ConfigureAwait(false);
        _cursor.X = target.X;
        _cursor.Y = target.Y;
        await CheckPointerEventsWorldAsync(
            selector, snapshot.TargetId, snapshot.Gen, target.X, target.Y,
            RemainingMs(deadline), force).ConfigureAwait(false);
        await HumanMouse.HumanClickAsync(_rawMouse, snapshot.IsInput, callCfg).ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // Double-click
    // -----------------------------------------------------------------------

    /// <summary>Human-like double-click on <paramref name="selector"/>.</summary>
    public async Task DblClickAsync(string selector, HumanActionOptions? options = null)
    {
        await EnsureCursorInitAsync().ConfigureAwait(false);
        var callCfg = MergeCfg(options);
        double timeout = options?.Timeout ?? 30000;
        bool force = options?.Force ?? false;
        double deadline = Environment.TickCount64 + timeout;

        if (!force)
            await EnsureActionableWorldAsync(selector, Actionability.ChecksClick, RemainingMs(deadline), force).ConfigureAwait(false);
        if (callCfg.IdleBetweenActions)
            await HumanMouse.HumanIdleAsync(_rawMouse, HumanRandom.Rand(callCfg.IdleBetweenDuration.Min, callCfg.IdleBetweenDuration.Max), _cursor.X, _cursor.Y, callCfg).ConfigureAwait(false);

        var scroll = await HumanScroll.HumanScrollIntoViewAsync(
            _scrollPage, _rawMouse, () => GetBoxAsync(selector, RemainingMs(deadline)),
            _cursor.X, _cursor.Y, callCfg).ConfigureAwait(false);
        _cursor.X = scroll.CursorX;
        _cursor.Y = scroll.CursorY;

        if (!force && scroll.DidScroll)
        {
            await EnsureStableWorldAsync(selector, RemainingMs(deadline)).ConfigureAwait(false);
            // Waiting for the reflow to settle can push the element back out of
            // view, and scrolling once before the wait is not enough: the click
            // coords would land outside the viewport and hit nothing (#329).
            var rescroll = await HumanScroll.HumanScrollIntoViewAsync(
                _scrollPage, _rawMouse, () => GetBoxAsync(selector, RemainingMs(deadline)),
                _cursor.X, _cursor.Y, callCfg).ConfigureAwait(false);
            _cursor.X = rescroll.CursorX;
            _cursor.Y = rescroll.CursorY;
        }

        var snapshot = await SelectorSnapshotAsync(selector).ConfigureAwait(false);
        var box = snapshot.Box ?? throw new ElementNotVisibleError(selector);
        var target = HumanMouse.ClickTarget(box, snapshot.IsInput, callCfg);
        await HumanMouse.HumanMoveAsync(
            _rawMouse, _cursor.X, _cursor.Y, target.X, target.Y, callCfg).ConfigureAwait(false);
        _cursor.X = target.X;
        _cursor.Y = target.Y;
        await CheckPointerEventsWorldAsync(
            selector, snapshot.TargetId, snapshot.Gen, target.X, target.Y,
            RemainingMs(deadline), force).ConfigureAwait(false);
        // Two presses for a double-click via Playwright IMouse click count.
        await _page.Mouse.DownAsync(new MouseDownOptions { ClickCount = 2 }).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(30, 60)).ConfigureAwait(false);
        await _page.Mouse.UpAsync(new MouseUpOptions { ClickCount = 2 }).ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // Hover
    // -----------------------------------------------------------------------

    /// <summary>Human-like hover over <paramref name="selector"/>.</summary>
    public Task HoverAsync(string selector, HumanActionOptions? options = null) =>
        HoverInternalAsync(selector, options, skipChecks: false);

    private async Task HoverInternalAsync(string selector, HumanActionOptions? options, bool skipChecks)
    {
        await EnsureCursorInitAsync().ConfigureAwait(false);
        var callCfg = MergeCfg(options);
        double timeout = options?.Timeout ?? 30000;
        bool force = options?.Force ?? false;
        double deadline = Environment.TickCount64 + timeout;

        if (!force && !skipChecks)
            await EnsureActionableWorldAsync(selector, Actionability.ChecksHover, RemainingMs(deadline), force).ConfigureAwait(false);
        if (callCfg.IdleBetweenActions)
            await HumanMouse.HumanIdleAsync(_rawMouse, HumanRandom.Rand(callCfg.IdleBetweenDuration.Min, callCfg.IdleBetweenDuration.Max), _cursor.X, _cursor.Y, callCfg).ConfigureAwait(false);

        var scroll = await HumanScroll.HumanScrollIntoViewAsync(
            _scrollPage, _rawMouse, () => GetBoxAsync(selector, RemainingMs(deadline)),
            _cursor.X, _cursor.Y, callCfg).ConfigureAwait(false);
        _cursor.X = scroll.CursorX;
        _cursor.Y = scroll.CursorY;

        if (!force && scroll.DidScroll)
        {
            await EnsureStableWorldAsync(selector, RemainingMs(deadline)).ConfigureAwait(false);
            // Waiting for the reflow to settle can push the element back out of
            // view, and scrolling once before the wait is not enough: the click
            // coords would land outside the viewport and hit nothing (#329).
            var rescroll = await HumanScroll.HumanScrollIntoViewAsync(
                _scrollPage, _rawMouse, () => GetBoxAsync(selector, RemainingMs(deadline)),
                _cursor.X, _cursor.Y, callCfg).ConfigureAwait(false);
            _cursor.X = rescroll.CursorX;
            _cursor.Y = rescroll.CursorY;
        }

        var snapshot = await SelectorSnapshotAsync(selector).ConfigureAwait(false);
        var box = snapshot.Box ?? throw new ElementNotVisibleError(selector);
        var target = HumanMouse.ClickTarget(box, false, callCfg);
        await HumanMouse.HumanMoveAsync(
            _rawMouse, _cursor.X, _cursor.Y, target.X, target.Y, callCfg).ConfigureAwait(false);
        _cursor.X = target.X;
        _cursor.Y = target.Y;
        await CheckPointerEventsWorldAsync(
            selector, snapshot.TargetId, snapshot.Gen, target.X, target.Y,
            RemainingMs(deadline), force).ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // Type (append) and Fill (clear + type)
    // -----------------------------------------------------------------------

    /// <summary>Human-like typing into <paramref name="selector"/> (appends to existing value).</summary>
    public async Task TypeAsync(string selector, string text, HumanActionOptions? options = null)
    {
        var callCfg = MergeCfg(options);
        double timeout = options?.Timeout ?? 30000;
        bool force = options?.Force ?? false;
        double deadline = Environment.TickCount64 + timeout;

        if (!force)
            await EnsureActionableWorldAsync(selector, Actionability.ChecksInput, RemainingMs(deadline), force).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.RandRange(callCfg.FieldSwitchDelay)).ConfigureAwait(false);
        await ClickInternalAsync(selector, new HumanActionOptions { Timeout = RemainingMs(deadline), Force = force, HumanConfig = options?.HumanConfig }, skipChecks: true).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(100, 250)).ConfigureAwait(false);
        await HumanKeyboard.HumanTypeAsync(_evaluator, _rawKeyboard, text, callCfg, _cdpSession).ConfigureAwait(false);
    }

    /// <summary>Human-like fill of <paramref name="selector"/> (selects all, deletes, then types).</summary>
    public async Task FillAsync(string selector, string value, HumanActionOptions? options = null)
    {
        var callCfg = MergeCfg(options);
        double timeout = options?.Timeout ?? 30000;
        bool force = options?.Force ?? false;
        double deadline = Environment.TickCount64 + timeout;

        if (!force)
            await EnsureActionableWorldAsync(selector, Actionability.ChecksInput, RemainingMs(deadline), force).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.RandRange(callCfg.FieldSwitchDelay)).ConfigureAwait(false);
        await ClickInternalAsync(selector, new HumanActionOptions { Timeout = RemainingMs(deadline), Force = force, HumanConfig = options?.HumanConfig }, skipChecks: true).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(100, 250)).ConfigureAwait(false);
        await _page.Keyboard.PressAsync(SelectAll).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(30, 80)).ConfigureAwait(false);
        await _page.Keyboard.PressAsync("Backspace").ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(50, 150)).ConfigureAwait(false);
        await HumanKeyboard.HumanTypeAsync(_evaluator, _rawKeyboard, value, callCfg, _cdpSession).ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // Check / Uncheck
    // -----------------------------------------------------------------------

    /// <summary>Human-like check of a checkbox/radio (no-op if already checked).</summary>
    public async Task CheckAsync(string selector, HumanActionOptions? options = null)
    {
        bool force = options?.Force ?? false;
        double timeout = options?.Timeout ?? 30000;
        double deadline = Environment.TickCount64 + timeout;

        if (!force)
            await EnsureActionableWorldAsync(selector, Actionability.ChecksCheck, RemainingMs(deadline), force).ConfigureAwait(false);
        bool checked_ = (await SelectorSnapshotAsync(selector).ConfigureAwait(false)).Checked == true;
        if (!checked_)
            await ClickInternalAsync(selector, new HumanActionOptions { Timeout = RemainingMs(deadline), Force = force, HumanConfig = options?.HumanConfig }, skipChecks: true).ConfigureAwait(false);
    }

    /// <summary>Human-like uncheck of a checkbox (no-op if already unchecked).</summary>
    public async Task UncheckAsync(string selector, HumanActionOptions? options = null)
    {
        bool force = options?.Force ?? false;
        double timeout = options?.Timeout ?? 30000;
        double deadline = Environment.TickCount64 + timeout;

        if (!force)
            await EnsureActionableWorldAsync(selector, Actionability.ChecksCheck, RemainingMs(deadline), force).ConfigureAwait(false);
        bool checked_ = (await SelectorSnapshotAsync(selector).ConfigureAwait(false)).Checked == true;
        if (checked_)
            await ClickInternalAsync(selector, new HumanActionOptions { Timeout = RemainingMs(deadline), Force = force, HumanConfig = options?.HumanConfig }, skipChecks: true).ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // Select option
    // -----------------------------------------------------------------------

    /// <summary>Human-like select of a dropdown option (hovers, then uses Playwright's selectOption).</summary>
    public async Task<IReadOnlyList<string>> SelectOptionAsync(string selector, string[] values, HumanActionOptions? options = null)
    {
        bool force = options?.Force ?? false;
        double timeout = options?.Timeout ?? 30000;
        double deadline = Environment.TickCount64 + timeout;

        if (!force)
            await EnsureActionableWorldAsync(selector, Actionability.ChecksFocus, RemainingMs(deadline), force).ConfigureAwait(false);
        await HoverInternalAsync(selector, new HumanActionOptions { Timeout = RemainingMs(deadline), Force = force, HumanConfig = options?.HumanConfig }, skipChecks: true).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(100, 300)).ConfigureAwait(false);
        return await _page.SelectOptionAsync(selector, values).ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // Press a key while a selector is focused
    // -----------------------------------------------------------------------

    /// <summary>Human-like press of <paramref name="key"/> after focusing <paramref name="selector"/>.</summary>
    public async Task PressAsync(string selector, string key, HumanActionOptions? options = null)
    {
        bool force = options?.Force ?? false;
        double timeout = options?.Timeout ?? 30000;
        double deadline = Environment.TickCount64 + timeout;

        if (!force)
            await EnsureActionableWorldAsync(selector, Actionability.ChecksFocus, RemainingMs(deadline), force).ConfigureAwait(false);
        if (!await IsSelectorFocusedAsync(selector).ConfigureAwait(false))
            await ClickInternalAsync(selector, new HumanActionOptions { Timeout = RemainingMs(deadline), Force = force, HumanConfig = options?.HumanConfig }, skipChecks: true).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(50, 150)).ConfigureAwait(false);
        await HumanKeyboard.PressAsync(_page.Keyboard, key, options?.Delay).ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // Set-checked (drives state to the requested value)
    // -----------------------------------------------------------------------

    /// <summary>Human-like set-checked: clicks only when the current state differs from
    /// the requested <paramref name="checked_"/> value. Port of <c>_humanized_set_checked</c>.</summary>
    public async Task SetCheckedAsync(string selector, bool checked_, HumanActionOptions? options = null)
    {
        bool force = options?.Force ?? false;
        double timeout = options?.Timeout ?? 30000;
        double deadline = Environment.TickCount64 + timeout;

        if (!force)
            await EnsureActionableWorldAsync(selector, Actionability.ChecksCheck, RemainingMs(deadline), force).ConfigureAwait(false);
        bool current = (await SelectorSnapshotAsync(selector).ConfigureAwait(false)).Checked == true;
        if (current != checked_)
            await ClickInternalAsync(selector, new HumanActionOptions { Timeout = RemainingMs(deadline), Force = force, HumanConfig = options?.HumanConfig }, skipChecks: true).ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // Tap (humanized click; mobile gesture maps to the same motion)
    // -----------------------------------------------------------------------

    /// <summary>Human-like tap. Port of <c>_humanized_tap</c> - same motion as a click.</summary>
    public Task TapAsync(string selector, HumanActionOptions? options = null) =>
        ClickAsync(selector, options);

    // -----------------------------------------------------------------------
    // Press sequentially (focus then human-type, no clear)
    // -----------------------------------------------------------------------

    /// <summary>Human-like press-sequentially: focuses (via click if needed) then types the
    /// text with human timing, without clearing. Port of <c>_humanized_press_sequentially</c>.</summary>
    public async Task PressSequentiallyAsync(string selector, string text, HumanActionOptions? options = null)
    {
        bool force = options?.Force ?? false;
        double timeout = options?.Timeout ?? 30000;
        double deadline = Environment.TickCount64 + timeout;

        if (!force)
            await EnsureActionableWorldAsync(selector, Actionability.ChecksInput, RemainingMs(deadline), force).ConfigureAwait(false);
        if (!await IsSelectorFocusedAsync(selector).ConfigureAwait(false))
            await ClickInternalAsync(selector, new HumanActionOptions { Timeout = RemainingMs(deadline), Force = force, HumanConfig = options?.HumanConfig }, skipChecks: true).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(50, 150)).ConfigureAwait(false);
        await HumanKeyboard.HumanTypeAsync(_evaluator, _rawKeyboard, text, MergeCfg(options), _cdpSession).ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // Clear (focus, select-all, backspace)
    // -----------------------------------------------------------------------

    /// <summary>Human-like clear: focuses (via click if needed), selects all, deletes.
    /// Port of <c>_humanized_clear</c>.</summary>
    public async Task ClearAsync(string selector, HumanActionOptions? options = null)
    {
        bool force = options?.Force ?? false;
        double timeout = options?.Timeout ?? 30000;
        double deadline = Environment.TickCount64 + timeout;

        if (!force)
            await EnsureActionableWorldAsync(selector, Actionability.ChecksInput, RemainingMs(deadline), force).ConfigureAwait(false);
        if (!await IsSelectorFocusedAsync(selector).ConfigureAwait(false))
            await ClickInternalAsync(selector, new HumanActionOptions { Timeout = RemainingMs(deadline), Force = force, HumanConfig = options?.HumanConfig }, skipChecks: true).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(50, 100)).ConfigureAwait(false);
        await _page.Keyboard.PressAsync(SelectAll).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(30, 80)).ConfigureAwait(false);
        await _page.Keyboard.PressAsync("Backspace").ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // Focus (human cursor move, then programmatic focus - NO click side-effects)
    // -----------------------------------------------------------------------

    /// <summary>Human-like focus: moves the cursor over the element with a Bezier curve,
    /// then focuses it programmatically (no click, so no onclick/submit/navigation).
    /// Port of <c>_human_el_focus</c> applied to a selector.</summary>
    public async Task FocusAsync(string selector, HumanActionOptions? options = null)
    {
        await EnsureCursorInitAsync().ConfigureAwait(false);
        var callCfg = MergeCfg(options);
        double timeout = options?.Timeout ?? 30000;
        bool force = options?.Force ?? false;
        double deadline = Environment.TickCount64 + timeout;

        if (!force)
            await EnsureActionableWorldAsync(selector, Actionability.ChecksFocus, RemainingMs(deadline), force).ConfigureAwait(false);

        var scroll = await HumanScroll.HumanScrollIntoViewAsync(
            _scrollPage, _rawMouse, () => GetBoxAsync(selector, RemainingMs(deadline)),
            _cursor.X, _cursor.Y, callCfg).ConfigureAwait(false);
        _cursor.X = scroll.CursorX;
        _cursor.Y = scroll.CursorY;
        var box = scroll.Box;
        if (!force && scroll.DidScroll)
        {
            await EnsureStableWorldAsync(selector, RemainingMs(deadline)).ConfigureAwait(false);
            // Waiting for the reflow to settle can push the element back out of
            // view, and scrolling once before the wait is not enough: the click
            // coords would land outside the viewport and hit nothing (#329).
            var rescroll = await HumanScroll.HumanScrollIntoViewAsync(
                _scrollPage, _rawMouse, () => GetBoxAsync(selector, RemainingMs(deadline)),
                _cursor.X, _cursor.Y, callCfg).ConfigureAwait(false);
            _cursor.X = rescroll.CursorX;
            _cursor.Y = rescroll.CursorY;
            box = rescroll.Box;
        }
        var target = HumanMouse.ClickTarget(box, false, callCfg);
        await HumanMouse.HumanMoveAsync(_rawMouse, _cursor.X, _cursor.Y, target.X, target.Y, callCfg).ConfigureAwait(false);
        _cursor.X = target.X;
        _cursor.Y = target.Y;
        // Programmatic focus - never clicks (mirrors stock Playwright el.focus()).
        await _page.FocusAsync(selector).ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // Scroll into view (humanized accelerate->cruise->decelerate->overshoot)
    // -----------------------------------------------------------------------

    /// <summary>Human-like scroll-into-view. Port of <c>_humanized_scroll_into_view_if_needed</c>.
    /// Returns true if a scroll was performed (false when already in viewport).</summary>
    public async Task<bool> ScrollIntoViewIfNeededAsync(string selector, HumanActionOptions? options = null)
    {
        await EnsureCursorInitAsync().ConfigureAwait(false);
        var callCfg = MergeCfg(options);
        double timeout = options?.Timeout ?? 30000;
        var scroll = await HumanScroll.HumanScrollIntoViewAsync(
            _scrollPage, _rawMouse, () => GetBoxAsync(selector, timeout),
            _cursor.X, _cursor.Y, callCfg).ConfigureAwait(false);
        _cursor.X = scroll.CursorX;
        _cursor.Y = scroll.CursorY;
        return scroll.DidScroll;
    }

    // -----------------------------------------------------------------------
    // Drag-and-drop (humanized: move to source center, down, move to target, up)
    // -----------------------------------------------------------------------

    /// <summary>Human-like drag from <paramref name="sourceSelector"/> to
    /// <paramref name="targetSelector"/>. Port of <c>_frame_drag_and_drop</c> / <c>_humanized_drag_to</c>:
    /// moves to the source center, presses, moves to the target center, releases.</summary>
    public async Task DragAndDropAsync(string sourceSelector, string targetSelector, HumanActionOptions? options = null)
    {
        await EnsureCursorInitAsync().ConfigureAwait(false);
        double timeout = options?.Timeout ?? 30000;

        var srcBox = await GetBoxAsync(sourceSelector, timeout).ConfigureAwait(false);
        var tgtBox = await GetBoxAsync(targetSelector, timeout).ConfigureAwait(false);
        if (srcBox == null)
            throw new ElementNotAttachedError(sourceSelector);
        if (tgtBox == null)
            throw new ElementNotAttachedError(targetSelector);

        BoundingBox src = srcBox.Value;
        BoundingBox tgt = tgtBox.Value;
        double sx = src.X + src.Width / 2;
        double sy = src.Y + src.Height / 2;
        double tx = tgt.X + tgt.Width / 2;
        double ty = tgt.Y + tgt.Height / 2;

        await HumanMouse.HumanMoveAsync(_rawMouse, _cursor.X, _cursor.Y, sx, sy, _cfg).ConfigureAwait(false);
        _cursor.X = sx; _cursor.Y = sy;
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(100, 200)).ConfigureAwait(false);
        await _rawMouse.DownAsync().ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(80, 150)).ConfigureAwait(false);
        await HumanMouse.HumanMoveAsync(_rawMouse, _cursor.X, _cursor.Y, tx, ty, _cfg).ConfigureAwait(false);
        _cursor.X = tx; _cursor.Y = ty;
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(80, 150)).ConfigureAwait(false);
        await _rawMouse.UpAsync().ConfigureAwait(false);
    }

    // -----------------------------------------------------------------------
    // Low-level mouse / keyboard
    // -----------------------------------------------------------------------

    /// <summary>Move the virtual cursor to absolute (x, y) with a human-like curve.</summary>
    public async Task MouseMoveAsync(double x, double y)
    {
        await EnsureCursorInitAsync().ConfigureAwait(false);
        await HumanMouse.HumanMoveAsync(_rawMouse, _cursor.X, _cursor.Y, x, y, _cfg).ConfigureAwait(false);
        _cursor.X = x;
        _cursor.Y = y;
    }

    /// <summary>Move to absolute (x, y) and perform a human-like click there.</summary>
    public async Task MouseClickAsync(double x, double y)
    {
        await EnsureCursorInitAsync().ConfigureAwait(false);
        await HumanMouse.HumanMoveAsync(_rawMouse, _cursor.X, _cursor.Y, x, y, _cfg).ConfigureAwait(false);
        _cursor.X = x;
        _cursor.Y = y;
        await HumanMouse.HumanClickAsync(_rawMouse, false, _cfg).ConfigureAwait(false);
    }

    /// <summary>Type text into whatever element currently has focus, with human timing.</summary>
    public Task KeyboardTypeAsync(string text) =>
        HumanKeyboard.HumanTypeAsync(_evaluator, _rawKeyboard, text, _cfg, _cdpSession);

    /// <summary>Mutable cursor position used across actions.</summary>
    private sealed class CursorState
    {
        public double X;
        public double Y;
        public bool Initialized;
    }
}
