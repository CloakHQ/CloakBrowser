using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>Humanized locator actions. Direct page.Locator selectors use the canonical isolated DOM world; unknown locator shapes retain the legacy Playwright path.</summary>
internal static class LocatorHumanizer
{
    private static double RemainingMs(double deadline) => Actionability.RemainingMs(deadline);

    private static async Task<IsolatedWorld> WorldAsync(HumanCursor cursor) =>
        await cursor.GetStealthAsync().ConfigureAwait(false) ?? throw new StealthWorldUnavailableError();

    internal static async Task<StealthSnapshot> SnapshotAsync(HumanCursor cursor, string selector)
    {
        var (status, snapshot) = await StealthDom.SnapshotAsync(await WorldAsync(cursor).ConfigureAwait(false), selector).ConfigureAwait(false);
        return status switch
        {
            StealthStatus.Ok when snapshot != null => snapshot.Value,
            StealthStatus.NotFound => throw new ElementNotAttachedError(selector),
            StealthStatus.Unsupported => throw new UnsupportedHumanizeSelectorError(selector),
            _ => throw new StealthEvaluationError(selector),
        };
    }

    internal static async Task EnsureActionableAsync(HumanCursor cursor, string selector,
        IReadOnlySet<string> checks, double timeout, bool force)
    {
        var world = await WorldAsync(cursor).ConfigureAwait(false);
        await Actionability.EnsureActionableAsync(cursor.Page, selector, checks, timeout, force, world).ConfigureAwait(false);
    }

    private static async Task<BoundingBox?> GetBoxAsync(
        IsolatedWorld world, string selector, double timeoutMs)
    {
        double deadline = System.Environment.TickCount64 + System.Math.Max(0, timeoutMs);
        var result = await StealthDom.BoxAsync(world, selector).ConfigureAwait(false);
        while ((result.Status == StealthStatus.NotFound || result.Status == StealthStatus.EvaluationFailed)
            && System.Environment.TickCount64 < deadline)
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

    // Share the canonical page-selector scroll flow: target zone, boundary checks,
    // stability wait and rescroll all remain isolated-world-only.
    private static async Task<StealthSnapshot> EnsureInViewAsync(
        HumanCursor cursor, IsolatedWorld world, string selector,
        HumanConfig cfg, double deadline, bool force)
    {
        var scrollPage = new PlaywrightScrollPage(
            cursor.Page, () => Task.FromResult(world));
        var scroll = await HumanScroll.HumanScrollIntoViewAsync(
            scrollPage, cursor.RawMouse,
            () => GetBoxAsync(world, selector, RemainingMs(deadline)),
            cursor.X, cursor.Y, cfg).ConfigureAwait(false);
        cursor.Set(scroll.CursorX, scroll.CursorY);

        if (!force && scroll.DidScroll)
        {
            await Actionability.EnsureStableAsync(
                cursor.Page, selector, RemainingMs(deadline), world).ConfigureAwait(false);
            var rescroll = await HumanScroll.HumanScrollIntoViewAsync(
                scrollPage, cursor.RawMouse,
                () => GetBoxAsync(world, selector, RemainingMs(deadline)),
                cursor.X, cursor.Y, cfg).ConfigureAwait(false);
            cursor.Set(rescroll.CursorX, rescroll.CursorY);
        }

        return await SnapshotAsync(cursor, selector).ConfigureAwait(false);
    }

    private static async Task<BoundingBox?> GetBoxPlaywrightAsync(ILocator locator, double timeoutMs)
    {
        try
        {
            var box = await locator.First.BoundingBoxAsync(new LocatorBoundingBoxOptions { Timeout = (float)System.Math.Max(1, timeoutMs) }).ConfigureAwait(false);
            return box == null ? null : new BoundingBox(box.X, box.Y, box.Width, box.Height);
        }
        catch (System.Exception) { return null; }
    }

    private static async Task<bool> IsInputPlaywrightAsync(ILocator locator)
    {
        try { return await locator.First.EvaluateAsync<bool>(@"el => { const tag = el.tagName.toLowerCase(); return tag === 'input' || tag === 'textarea' || el.getAttribute('contenteditable') === 'true'; }").ConfigureAwait(false); }
        catch (System.Exception) { return false; }
    }

    private static async Task<bool> IsFocusedLegacyAsync(ILocator locator)
    {
        try { return await locator.First.EvaluateAsync<bool>("el => el === document.activeElement").ConfigureAwait(false); }
        catch (System.Exception) { return false; }
    }

    private static async Task<(double X, double Y, bool IsInput)> MoveLegacyAsync(ILocator locator,
        HumanCursor cursor, HumanConfig cfg, double deadline, bool force)
    {
        await cursor.EnsureInitializedAsync(cfg).ConfigureAwait(false);
        if (cfg.IdleBetweenActions) await HumanMouse.HumanIdleAsync(cursor.RawMouse,
            HumanRandom.Rand(cfg.IdleBetweenDuration.Min, cfg.IdleBetweenDuration.Max), cursor.X, cursor.Y, cfg).ConfigureAwait(false);
        if (!force) await locator.First.ScrollIntoViewIfNeededAsync(new LocatorScrollIntoViewIfNeededOptions { Timeout = (float)RemainingMs(deadline) }).ConfigureAwait(false);
        var box = await GetBoxPlaywrightAsync(locator, RemainingMs(deadline)).ConfigureAwait(false);
        var input = await IsInputPlaywrightAsync(locator).ConfigureAwait(false);
        var target = HumanMouse.ClickTarget(box ?? new BoundingBox(cursor.X, cursor.Y, 1, 1), input, cfg);
        await HumanMouse.HumanMoveAsync(cursor.RawMouse, cursor.X, cursor.Y, target.X, target.Y, cfg).ConfigureAwait(false);
        cursor.Set(target.X, target.Y);
        return (target.X, target.Y, input);
    }

    private static async Task<(double X, double Y, bool IsInput)> MoveDirectAsync(ILocator locator,
        HumanCursor cursor, HumanConfig cfg, double deadline, bool force, string selector, IReadOnlySet<string> checks, bool skipChecks)
    {
        await cursor.EnsureInitializedAsync(cfg).ConfigureAwait(false);
        var world = await WorldAsync(cursor).ConfigureAwait(false);
        if (!force && !skipChecks)
            await Actionability.EnsureActionableAsync(cursor.Page, selector, checks, RemainingMs(deadline), false, world).ConfigureAwait(false);
        if (cfg.IdleBetweenActions) await HumanMouse.HumanIdleAsync(cursor.RawMouse,
            HumanRandom.Rand(cfg.IdleBetweenDuration.Min, cfg.IdleBetweenDuration.Max), cursor.X, cursor.Y, cfg).ConfigureAwait(false);
        var snapshot = await EnsureInViewAsync(
            cursor, world, selector, cfg, deadline, force).ConfigureAwait(false);
        var box = snapshot.Box ?? throw new ElementNotVisibleError(selector);
        var target = HumanMouse.ClickTarget(box, snapshot.IsInput, cfg);
        await HumanMouse.HumanMoveAsync(cursor.RawMouse, cursor.X, cursor.Y, target.X, target.Y, cfg).ConfigureAwait(false);
        cursor.Set(target.X, target.Y);
        // Validate the click point after motion, immediately before the caller's mouse-down.
        // force bypasses it entirely, matching Playwright.
        if (!force)
            await Actionability.CheckPointerEventsAsync(cursor.Page, selector, snapshot.TargetId, snapshot.Gen,
                target.X, target.Y, RemainingMs(deadline), world).ConfigureAwait(false);
        return (target.X, target.Y, snapshot.IsInput);
    }

    private static Task<(double X, double Y, bool IsInput)> MoveAsync(ILocator locator, HumanCursor cursor,
        HumanConfig cfg, double deadline, bool force, string? selector, IReadOnlySet<string> checks, bool skipChecks) =>
        selector == null ? MoveLegacyAsync(locator, cursor, cfg, deadline, force) :
        MoveDirectAsync(locator, cursor, cfg, deadline, force, selector, checks, skipChecks);

    private static async Task ClickInternalAsync(ILocator locator, HumanCursor cursor, HumanConfig cfg,
        double timeout, bool force, string? selector, IReadOnlySet<string> checks, bool skipChecks)
    {
        var deadline = System.Environment.TickCount64 + timeout;
        var target = await MoveAsync(locator, cursor, cfg, deadline, force, selector, checks, skipChecks).ConfigureAwait(false);
        await HumanMouse.HumanClickAsync(cursor.RawMouse, target.IsInput, cfg).ConfigureAwait(false);
    }

    public static Task ClickAsync(ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force, string? selector = null) =>
        ClickInternalAsync(locator, cursor, cfg, timeout, force, selector, Actionability.ChecksClick, false);

    // Used by state-changing wrappers after their ChecksCheck preflight.
    internal static Task ClickAfterPrecheckAsync(ILocator locator, HumanCursor cursor, HumanConfig cfg,
        double timeout, bool force, string? selector) =>
        ClickInternalAsync(locator, cursor, cfg, timeout, force, selector, Actionability.ChecksCheck, selector != null);

    public static async Task DblClickAsync(ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force, string? selector = null)
    {
        var deadline = System.Environment.TickCount64 + timeout;
        await MoveAsync(locator, cursor, cfg, deadline, force, selector, Actionability.ChecksClick, false).ConfigureAwait(false);
        await cursor.RawMouseDownAsync(2).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(30, 60)).ConfigureAwait(false);
        await cursor.RawMouseUpAsync(2).ConfigureAwait(false);
    }

    public static async Task HoverAsync(ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force, string? selector = null)
    {
        var deadline = System.Environment.TickCount64 + timeout;
        await MoveAsync(locator, cursor, cfg, deadline, force, selector, Actionability.ChecksHover, false).ConfigureAwait(false);
    }

    public static Task TapAsync(ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force, string? selector = null) =>
        ClickAsync(locator, cursor, cfg, timeout, force, selector);

    public static async Task FillAsync(ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force, string value, string? selector = null)
    {
        var deadline = System.Environment.TickCount64 + timeout;
        if (selector != null) await EnsureActionableAsync(cursor, selector, Actionability.ChecksInput, RemainingMs(deadline), force).ConfigureAwait(false);
        await ClickInternalAsync(locator, cursor, cfg, RemainingMs(deadline), force, selector, Actionability.ChecksInput, selector != null).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(100, 250)).ConfigureAwait(false);
        await cursor.SelectAllAsync().ConfigureAwait(false); await HumanRandom.SleepMsAsync(HumanRandom.Rand(30, 80)).ConfigureAwait(false);
        await cursor.PressAsync("Backspace").ConfigureAwait(false); await HumanRandom.SleepMsAsync(HumanRandom.Rand(50, 150)).ConfigureAwait(false);
        await cursor.HumanTypeAsync(value, cfg).ConfigureAwait(false);
    }

    public static async Task TypeAsync(ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force, string text, string? selector = null)
    {
        var deadline = System.Environment.TickCount64 + timeout;
        if (selector != null) await EnsureActionableAsync(cursor, selector, Actionability.ChecksInput, RemainingMs(deadline), force).ConfigureAwait(false);
        var focused = selector != null
            ? (await SnapshotAsync(cursor, selector).ConfigureAwait(false)).Focused
            : await IsFocusedLegacyAsync(locator).ConfigureAwait(false);
        if (!focused)
            await ClickInternalAsync(locator, cursor, cfg, RemainingMs(deadline), force, selector, Actionability.ChecksInput, selector != null).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(100, 250)).ConfigureAwait(false); await cursor.HumanTypeAsync(text, cfg).ConfigureAwait(false);
    }

    public static Task PressSequentiallyAsync(ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force, string text, string? selector = null) =>
        TypeAsync(locator, cursor, cfg, timeout, force, text, selector);

    public static async Task PressAsync(ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force, string key, float? delay = null, string? selector = null)
    {
        var deadline = System.Environment.TickCount64 + timeout;
        if (selector != null) await EnsureActionableAsync(cursor, selector, Actionability.ChecksFocus, RemainingMs(deadline), force).ConfigureAwait(false);
        var focused = selector != null ? (await SnapshotAsync(cursor, selector).ConfigureAwait(false)).Focused : await IsFocusedLegacyAsync(locator).ConfigureAwait(false);
        if (!focused) await ClickInternalAsync(locator, cursor, cfg, RemainingMs(deadline), force, selector, Actionability.ChecksFocus, selector != null).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(50, 150)).ConfigureAwait(false); await cursor.PressAsync(key, delay).ConfigureAwait(false);
    }

    public static async Task SelectOptionPrologueAsync(ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force, string? selector = null)
    {
        var deadline = System.Environment.TickCount64 + timeout;
        if (selector != null) await EnsureActionableAsync(cursor, selector, Actionability.ChecksFocus, RemainingMs(deadline), force).ConfigureAwait(false);
        await MoveAsync(locator, cursor, cfg, deadline, force, selector, Actionability.ChecksHover, selector != null).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(100, 300)).ConfigureAwait(false);
    }

    public static async Task ClearAsync(ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force, string? selector = null)
    {
        var deadline = System.Environment.TickCount64 + timeout;
        if (selector != null) await EnsureActionableAsync(cursor, selector, Actionability.ChecksInput, RemainingMs(deadline), force).ConfigureAwait(false);
        var focused = selector != null ? (await SnapshotAsync(cursor, selector).ConfigureAwait(false)).Focused : await IsFocusedLegacyAsync(locator).ConfigureAwait(false);
        if (!focused) await ClickInternalAsync(locator, cursor, cfg, RemainingMs(deadline), force, selector, Actionability.ChecksInput, selector != null).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(50, 100)).ConfigureAwait(false); await cursor.SelectAllAsync().ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(30, 80)).ConfigureAwait(false); await cursor.PressAsync("Backspace").ConfigureAwait(false);
    }
}
