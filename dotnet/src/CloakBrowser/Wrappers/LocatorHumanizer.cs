using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Humanized actions that operate directly on an <see cref="ILocator"/>.
///
/// The selector-based <see cref="HumanPage"/> drives motion from a CSS/XPath selector;
/// locators don't expose their selector string publicly, so this helper drives the
/// same Bezier-curve / human-typing engine from the locator's own bounding box and
/// the shared <see cref="HumanCursor"/> state of the page it belongs to. The behavior
/// (curves, aim points, timing, typing stealth path) is identical to <see cref="HumanPage"/>;
/// only the element-resolution path differs.
/// </summary>
internal static class LocatorHumanizer
{
    private static double RemainingMs(double deadline) => CloakBrowser.Human.Actionability.RemainingMs(deadline);

    private static async Task<BoundingBox?> GetBoxAsync(ILocator locator, double timeoutMs)
    {
        try
        {
            var box = await locator.First.BoundingBoxAsync(new LocatorBoundingBoxOptions
            {
                Timeout = (float)System.Math.Max(1, timeoutMs),
            }).ConfigureAwait(false);
            return box == null ? null : new BoundingBox(box.X, box.Y, box.Width, box.Height);
        }
        catch (System.Exception)
        {
            return null;
        }
    }

    private static async Task<bool> IsInputAsync(ILocator locator)
    {
        try
        {
            return await locator.First.EvaluateAsync<bool>(
                @"el => {
                    const tag = el.tagName.toLowerCase();
                    return tag === 'input' || tag === 'textarea'
                        || el.getAttribute('contenteditable') === 'true';
                }").ConfigureAwait(false);
        }
        catch (System.Exception) { return false; }
    }

    private static async Task<bool> IsFocusedAsync(ILocator locator)
    {
        try
        {
            return await locator.First.EvaluateAsync<bool>(
                "el => el === document.activeElement").ConfigureAwait(false);
        }
        catch (System.Exception) { return false; }
    }

    // -----------------------------------------------------------------------
    // Core motion-to-target used by click/hover/dblclick.
    // -----------------------------------------------------------------------

    private static async Task<(double X, double Y, bool IsInput)> MoveToTargetAsync(
        ILocator locator, HumanCursor cursor, HumanConfig cfg, double deadline, bool force)
    {
        await cursor.EnsureInitializedAsync(cfg).ConfigureAwait(false);

        if (cfg.IdleBetweenActions)
            await HumanMouse.HumanIdleAsync(cursor.RawMouse,
                HumanRandom.Rand(cfg.IdleBetweenDuration.Min, cfg.IdleBetweenDuration.Max),
                cursor.X, cursor.Y, cfg).ConfigureAwait(false);

        var box = await GetBoxAsync(locator, RemainingMs(deadline)).ConfigureAwait(false);
        bool isInput = await IsInputAsync(locator).ConfigureAwait(false);
        var target = HumanMouse.ClickTarget(
            box ?? new BoundingBox(cursor.X, cursor.Y, 1, 1), isInput, cfg);

        await HumanMouse.HumanMoveAsync(cursor.RawMouse, cursor.X, cursor.Y, target.X, target.Y, cfg)
            .ConfigureAwait(false);
        cursor.Set(target.X, target.Y);
        return (target.X, target.Y, isInput);
    }

    // -----------------------------------------------------------------------
    // Public humanized actions
    // -----------------------------------------------------------------------

    public static async Task ClickAsync(
        ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force)
    {
        double deadline = System.Environment.TickCount64 + timeout;
        // Let Playwright wait for actionability (raises on real problems / cancellation).
        if (!force)
            await locator.First.ScrollIntoViewIfNeededAsync(
                new LocatorScrollIntoViewIfNeededOptions { Timeout = (float)RemainingMs(deadline) })
                .ConfigureAwait(false);
        var t = await MoveToTargetAsync(locator, cursor, cfg, deadline, force).ConfigureAwait(false);
        await HumanMouse.HumanClickAsync(cursor.RawMouse, t.IsInput, cfg).ConfigureAwait(false);
    }

    public static async Task DblClickAsync(
        ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force)
    {
        double deadline = System.Environment.TickCount64 + timeout;
        if (!force)
            await locator.First.ScrollIntoViewIfNeededAsync(
                new LocatorScrollIntoViewIfNeededOptions { Timeout = (float)RemainingMs(deadline) })
                .ConfigureAwait(false);
        await MoveToTargetAsync(locator, cursor, cfg, deadline, force).ConfigureAwait(false);
        await cursor.RawMouseDownAsync(2).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(30, 60)).ConfigureAwait(false);
        await cursor.RawMouseUpAsync(2).ConfigureAwait(false);
    }

    public static async Task HoverAsync(
        ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force)
    {
        double deadline = System.Environment.TickCount64 + timeout;
        if (!force)
            await locator.First.ScrollIntoViewIfNeededAsync(
                new LocatorScrollIntoViewIfNeededOptions { Timeout = (float)RemainingMs(deadline) })
                .ConfigureAwait(false);
        await MoveToTargetAsync(locator, cursor, cfg, deadline, force).ConfigureAwait(false);
    }

    public static async Task TapAsync(
        ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force) =>
        await ClickAsync(locator, cursor, cfg, timeout, force).ConfigureAwait(false);

    public static async Task FillAsync(
        ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force, string value)
    {
        double deadline = System.Environment.TickCount64 + timeout;
        await ClickAsync(locator, cursor, cfg, RemainingMs(deadline), force).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(100, 250)).ConfigureAwait(false);
        await cursor.SelectAllAsync().ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(30, 80)).ConfigureAwait(false);
        await cursor.PressAsync("Backspace").ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(50, 150)).ConfigureAwait(false);
        await cursor.HumanTypeAsync(value, cfg).ConfigureAwait(false);
    }

    public static async Task TypeAsync(
        ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force, string text)
    {
        double deadline = System.Environment.TickCount64 + timeout;
        if (!await IsFocusedAsync(locator).ConfigureAwait(false))
            await ClickAsync(locator, cursor, cfg, RemainingMs(deadline), force).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(100, 250)).ConfigureAwait(false);
        await cursor.HumanTypeAsync(text, cfg).ConfigureAwait(false);
    }

    public static async Task PressSequentiallyAsync(
        ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force, string text) =>
        await TypeAsync(locator, cursor, cfg, timeout, force, text).ConfigureAwait(false);

    public static async Task PressAsync(
        ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force, string key)
    {
        double deadline = System.Environment.TickCount64 + timeout;
        if (!await IsFocusedAsync(locator).ConfigureAwait(false))
            await ClickAsync(locator, cursor, cfg, RemainingMs(deadline), force).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(50, 150)).ConfigureAwait(false);
        await cursor.PressAsync(key).ConfigureAwait(false);
    }

    /// <summary>
    /// Human pre-roll for <c>select_option</c>: move the cursor along a Bezier curve to
    /// the &lt;select&gt; element (humanized hover) and pause, mirroring the Python
    /// <c>_humanized_select_option</c>. The real Playwright select call is performed by
    /// the caller afterwards (native &lt;select&gt; popups can't be driven by mouse).
    /// </summary>
    public static async Task SelectOptionPrologueAsync(
        ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force)
    {
        await HoverAsync(locator, cursor, cfg, timeout, force).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(100, 300)).ConfigureAwait(false);
    }

    /// <summary>
    /// Human <c>clear</c>: focus the field (humanized click if not already focused),
    /// select-all, then press Backspace - instead of an instant value reset. Mirrors the
    /// Python <c>_humanized_clear</c>.
    /// </summary>
    public static async Task ClearAsync(
        ILocator locator, HumanCursor cursor, HumanConfig cfg, double timeout, bool force)
    {
        double deadline = System.Environment.TickCount64 + timeout;
        if (!await IsFocusedAsync(locator).ConfigureAwait(false))
            await ClickAsync(locator, cursor, cfg, RemainingMs(deadline), force).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(50, 100)).ConfigureAwait(false);
        await cursor.SelectAllAsync().ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(30, 80)).ConfigureAwait(false);
        await cursor.PressAsync("Backspace").ConfigureAwait(false);
    }
}
