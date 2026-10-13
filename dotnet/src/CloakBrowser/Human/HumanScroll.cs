namespace CloakBrowser.Human;

/// <summary>
/// Page-level operations the scroller needs: the viewport size and a way to
/// fetch a bounding box on demand. Implemented over Playwright's <c>IPage</c>.
/// </summary>
public interface IRawScrollPage
{
    /// <summary>Current viewport size, or null if unavailable.</summary>
    (int Width, int Height)? ViewportSize { get; }

    /// <summary>
    /// Live window dimensions (<c>window.innerWidth</c>/<c>innerHeight</c>), used as a
    /// fallback when <see cref="ViewportSize"/> is null. Headed launches default to
    /// no-viewport so the page tracks the real OS window and <c>ViewportSize</c> is
    /// null there - this keeps humanized scroll working in headed (stealth) mode.
    /// Returns null if the dimensions can't be read.
    /// </summary>
    Task<(int Width, int Height)?> GetLiveWindowSizeAsync();

    /// <summary>
    /// Current scroll offsets (<c>window.scrollY</c>, <c>window.scrollX</c>) and the
    /// maximum scrollable offsets (<c>scrollHeight - clientHeight</c>,
    /// <c>scrollWidth - clientWidth</c>). X is measured from the leftmost scroll
    /// position, so it runs 0..MaxX in RTL documents too. Used to detect when the
    /// page is pinned at a boundary and further scrolling can't help. Returns null
    /// if the values can't be read.
    /// </summary>
    Task<(double Y, double MaxY, double X, double MaxX)?> GetScrollStateAsync();
}

/// <summary>Result of a humanized scroll-into-view operation.</summary>
/// <param name="Box">The element's bounding box after scrolling.</param>
/// <param name="CursorX">The cursor X position after scrolling.</param>
/// <param name="CursorY">The cursor Y position after scrolling.</param>
/// <param name="DidScroll">False when the element was already in the viewport.</param>
public readonly record struct ScrollResult(BoundingBox Box, double CursorX, double CursorY, bool DidScroll);

/// <summary>
/// Human-like scrolling via mouse wheel events.
/// Standalone helper (humanized actions use the engine); mirrors the JS Puppeteer scroller.
/// </summary>
public static class HumanScroll
{
    private static bool IsInViewport(BoundingBox bounds, int viewportHeight, HumanConfig cfg)
    {
        double topEdge = bounds.Y;
        double bottomEdge = bounds.Y + bounds.Height;
        double zoneTop = viewportHeight * cfg.ScrollTargetZone.Min;
        double zoneBottom = viewportHeight * cfg.ScrollTargetZone.Max;
        return topEdge >= zoneTop && bottomEdge <= zoneBottom;
    }

    private static bool IsInViewportX(BoundingBox bounds, int viewportWidth)
    {
        return bounds.X >= 0 && bounds.X + bounds.Width <= viewportWidth;
    }

    /// <summary>CSS pixels per wheel notch: <see cref="HumanConfig.ScrollNotchPx"/> when set,
    /// else 100 (Chrome on Windows; this helper has no persona to ask).</summary>
    private static double NotchPx(HumanConfig cfg) => cfg.ScrollNotchPx > 0 ? cfg.ScrollNotchPx : 100;

    /// <summary>
    /// Turn the wheel by about <paramref name="delta"/> px in whole notches: flicks of a
    /// few notches, quicker inside a flick, with a short pause between flicks. CDP reports
    /// every wheel event as one notch (<c>wheelDeltaY</c> 120), so whole-notch events are
    /// the only ones whose <c>deltaY</c> agrees. Returns the distance actually wheeled.
    /// </summary>
    private static async Task<double> WheelNotchesAsync(IRawMouse raw, double delta, HumanConfig cfg, bool horizontal = false)
    {
        double notch = NotchPx(cfg);
        int sign = delta > 0 ? 1 : -1;
        int notches = (int)Math.Round(Math.Abs(delta) / notch);
        int flick = HumanRandom.RandIntRange((2, 5));
        for (int i = 0; i < notches; i++)
        {
            double d = notch * sign;
            if (horizontal) await raw.WheelAsync(d, 0).ConfigureAwait(false);
            else await raw.WheelAsync(0, d).ConfigureAwait(false);
            if (i == notches - 1) break;
            if (--flick <= 0)
            {
                flick = HumanRandom.RandIntRange((2, 5));
                await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ScrollPauseSlow) + HumanRandom.Rand(40, 120)).ConfigureAwait(false);
            }
            else
            {
                await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ScrollPauseFast)).ConfigureAwait(false);
            }
        }
        return notches * notch * sign;
    }

    /// <summary>
    /// Public smooth-wheel helper for a direct wheel request: each non-zero axis is
    /// turned by a whole number of notches (at least one), like a person would. When
    /// both deltas are zero a single no-op wheel event is sent, matching Playwright's
    /// <c>IMouse.WheelAsync(0, 0)</c>.
    /// </summary>
    public static async Task SmoothWheelAsync(IRawMouse raw, double deltaX, double deltaY, HumanConfig cfg)
    {
        double notch = NotchPx(cfg);
        if (deltaY != 0)
            await WheelNotchesAsync(raw, Math.Sign(deltaY) * Math.Max(notch, Math.Abs(deltaY)), cfg).ConfigureAwait(false);
        if (deltaX != 0)
            await WheelNotchesAsync(raw, Math.Sign(deltaX) * Math.Max(notch, Math.Abs(deltaX)), cfg, horizontal: true).ConfigureAwait(false);
        if (deltaX == 0 && deltaY == 0)
            await raw.WheelAsync(0, 0).ConfigureAwait(false);
    }

    /// <summary>
    /// Humanized scrolling that uses an arbitrary <paramref name="getBox"/> callable
    /// instead of a CSS selector. Runs the accelerate -> cruise -> decelerate ->
    /// overshoot behavior.
    /// </summary>
    /// <returns>(box, cursorX, cursorY, didScroll) - didScroll is false when the
    /// element was already in the viewport.</returns>
    public static async Task<ScrollResult> HumanScrollIntoViewAsync(
        IRawScrollPage page,
        IRawMouse raw,
        Func<Task<BoundingBox?>> getBox,
        double cursorX, double cursorY,
        HumanConfig cfg)
    {
        var viewport = page.ViewportSize;
        if (viewport == null)
            // Headed launches default to no_viewport so the page tracks the real OS
            // window; ViewportSize is then null. Fall back to the live window
            // dimensions so humanize works headed (the stealth-relevant mode).
            viewport = await page.GetLiveWindowSizeAsync().ConfigureAwait(false);
        if (viewport == null || viewport.Value.Height == 0)
            throw new InvalidOperationException("Viewport size not available");

        int viewportHeight = viewport.Value.Height;
        int viewportWidth = viewport.Value.Width;

        var yPass = await ScrollYIntoViewAsync(page, raw, getBox, viewportWidth, viewportHeight, cursorX, cursorY, cfg).ConfigureAwait(false);
        var xPass = await ScrollXIntoViewAsync(page, raw, getBox, yPass.Box, viewportWidth, viewportHeight, yPass.CursorX, yPass.CursorY, cfg).ConfigureAwait(false);
        return xPass with { DidScroll = yPass.DidScroll || xPass.DidScroll };
    }

    /// <summary>Vertical pass: bring the box into <c>ScrollTargetZone</c>.</summary>
    private static async Task<ScrollResult> ScrollYIntoViewAsync(
        IRawScrollPage page,
        IRawMouse raw,
        Func<Task<BoundingBox?>> getBox,
        int viewportWidth, int viewportHeight,
        double cursorX, double cursorY,
        HumanConfig cfg)
    {
        var box = await getBox().ConfigureAwait(false);
        if (box == null)
            throw new InvalidOperationException("Element not found while scrolling into view");

        if (IsInViewport(box.Value, viewportHeight, cfg))
            return new ScrollResult(box.Value, cursorX, cursorY, false);

        // Already fully visible but off-center, with the page pinned at the boundary
        // in the needed direction: scrolling can't help, so don't waste the budget.
        // 1px slack: layout can report a top edge of -1/64 px on an unscrolled page.
        bool fullyVisible = box.Value.Y >= -1 && box.Value.Y + box.Value.Height <= viewportHeight + 1;
        if (fullyVisible)
        {
            double zoneMid = viewportHeight * (cfg.ScrollTargetZone.Min + cfg.ScrollTargetZone.Max) / 2;
            bool needUp = box.Value.Y + box.Value.Height / 2 < zoneMid;
            var scroll = await page.GetScrollStateAsync().ConfigureAwait(false);
            if (scroll != null && (needUp ? scroll.Value.Y <= 0 : scroll.Value.Y >= scroll.Value.MaxY))
                return new ScrollResult(box.Value, cursorX, cursorY, false);
        }

        // Move cursor into scroll area.
        double scrollAreaX = Math.Round(viewportWidth * HumanRandom.Rand(0.3, 0.7));
        double scrollAreaY = Math.Round(viewportHeight * HumanRandom.Rand(0.3, 0.7));
        await HumanMouse.HumanMoveAsync(raw, cursorX, cursorY, scrollAreaX, scrollAreaY, cfg).ConfigureAwait(false);
        cursorX = scrollAreaX;
        cursorY = scrollAreaY;
        await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ScrollPreMoveDelay)).ConfigureAwait(false);

        // Wheel in whole notches, re-measuring between flicks, until the element
        // sits in the target zone (or the page stops moving).
        double notch = NotchPx(cfg);
        double targetY = viewportHeight * HumanRandom.Rand(cfg.ScrollTargetZone.Min, cfg.ScrollTargetZone.Max);
        bool overshot = false;
        int stalled = 0;
        for (int round = 0; round < 40 && stalled < 2; round++)
        {
            double distance = box.Value.Y + box.Value.Height / 2 - targetY;
            if (Math.Abs(distance) < notch / 2 || IsInViewport(box.Value, viewportHeight, cfg)) break;
            int direction = distance > 0 ? 1 : -1;
            int flick = Math.Min((int)Math.Round(Math.Abs(distance) / notch), HumanRandom.RandIntRange((2, 5)));
            double beforeY = box.Value.Y;
            await WheelNotchesAsync(raw, flick * notch * direction, cfg).ConfigureAwait(false);
            await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ScrollPauseSlow)).ConfigureAwait(false);
            var nb = await getBox().ConfigureAwait(false);
            if (nb == null) break;
            box = nb;
            stalled = Math.Abs(box.Value.Y - beforeY) < 1 ? stalled + 1 : 0;
            if (!overshot && HumanRandom.NextDouble() < cfg.ScrollOvershootChance
                && Math.Abs(box.Value.Y + box.Value.Height / 2 - targetY) < notch * 2)
            {
                // Optional overshoot + correction, in whole notches.
                overshot = true;
                int over = Math.Max(1, (int)Math.Round(HumanRandom.RandRange(cfg.ScrollOvershootPx) / notch));
                await WheelNotchesAsync(raw, over * notch * direction, cfg).ConfigureAwait(false);
                await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ScrollSettleDelay)).ConfigureAwait(false);
                await WheelNotchesAsync(raw, -over * notch * direction, cfg).ConfigureAwait(false);
                await HumanRandom.SleepMsAsync(HumanRandom.Rand(100, 250)).ConfigureAwait(false);
                box = await getBox().ConfigureAwait(false) ?? box;
            }
        }

        // Settle.
        await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ScrollSettleDelay)).ConfigureAwait(false);

        box = await getBox().ConfigureAwait(false);
        if (box == null)
            throw new InvalidOperationException("Element lost after scrolling into view");

        return new ScrollResult(box.Value, cursorX, cursorY, true);
    }

    /// <summary>
    /// Horizontal pass: bring the box inside the viewport width (#521). Only
    /// containment is checked here, not <c>ScrollTargetZone</c>: the zone is a
    /// vertical reading position, and horizontal overflow is the exception.
    /// </summary>
    private static async Task<ScrollResult> ScrollXIntoViewAsync(
        IRawScrollPage page,
        IRawMouse raw,
        Func<Task<BoundingBox?>> getBox,
        BoundingBox box,
        int viewportWidth, int viewportHeight,
        double cursorX, double cursorY,
        HumanConfig cfg)
    {
        if (IsInViewportX(box, viewportWidth))
            return new ScrollResult(box, cursorX, cursorY, false);

        double distanceToScroll = box.X + box.Width / 2 - viewportWidth / 2.0;
        // A box wider than the viewport is never contained; once centred, skip the near-zero wheel.
        if (Math.Abs(distanceToScroll) < 1)
            return new ScrollResult(box, cursorX, cursorY, false);

        // Page pinned at the boundary in the needed direction: scrolling can't help.
        var scroll = await page.GetScrollStateAsync().ConfigureAwait(false);
        if (scroll != null && (distanceToScroll < 0 ? scroll.Value.X <= 0 : scroll.Value.X >= scroll.Value.MaxX))
            return new ScrollResult(box, cursorX, cursorY, false);

        double scrollAreaX = Math.Round(viewportWidth * HumanRandom.Rand(0.3, 0.7));
        double scrollAreaY = Math.Round(viewportHeight * HumanRandom.Rand(0.3, 0.7));
        await HumanMouse.HumanMoveAsync(raw, cursorX, cursorY, scrollAreaX, scrollAreaY, cfg).ConfigureAwait(false);
        cursorX = scrollAreaX;
        cursorY = scrollAreaY;
        await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ScrollPreMoveDelay)).ConfigureAwait(false);

        await WheelNotchesAsync(raw, distanceToScroll, cfg, horizontal: true).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ScrollSettleDelay)).ConfigureAwait(false);

        var finalBox = await getBox().ConfigureAwait(false);
        if (finalBox == null)
            throw new InvalidOperationException("Element lost after scrolling into view");

        return new ScrollResult(finalBox.Value, cursorX, cursorY, true);
    }
}
