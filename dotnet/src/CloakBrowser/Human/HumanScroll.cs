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
}

/// <summary>Result of a humanized scroll-into-view operation.</summary>
/// <param name="Box">The element's bounding box after scrolling.</param>
/// <param name="CursorX">The cursor X position after scrolling.</param>
/// <param name="CursorY">The cursor Y position after scrolling.</param>
/// <param name="DidScroll">False when the element was already in the viewport.</param>
public readonly record struct ScrollResult(BoundingBox Box, double CursorX, double CursorY, bool DidScroll);

/// <summary>
/// Human-like scrolling via mouse wheel events.
/// Direct port of Python <c>cloakbrowser/human/scroll.py</c>.
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

    /// <summary>Send one logical scroll as a burst of small wheel events (like real inertia).</summary>
    private static async Task SmoothWheelAsync(IRawMouse raw, int delta, HumanConfig cfg)
    {
        double absD = Math.Abs(delta);
        int sign = delta > 0 ? 1 : -1;
        double sent = 0;
        while (sent < absD)
        {
            double stepSize = HumanRandom.Rand(20, 40);
            double chunk = Math.Min(stepSize, absD - sent);
            await raw.WheelAsync(0, Math.Round(chunk) * sign).ConfigureAwait(false);
            sent += chunk;
            await HumanRandom.SleepMsAsync(HumanRandom.Rand(8, 20)).ConfigureAwait(false);
        }
    }

    /// <summary>
    /// Public smooth-wheel helper for the transparent <c>IMouse.WheelAsync</c> override:
    /// breaks a (deltaX, deltaY) wheel request into the same small-burst-with-inertia
    /// pattern used for scroll-into-view, so direct wheel calls look human too.
    /// </summary>
    public static async Task SmoothWheelAsync(IRawMouse raw, double deltaX, double deltaY, HumanConfig cfg)
    {
        // X axis is sent in one go (horizontal scroll is rarely incremental), Y is
        // chunked for inertia. When both are zero, send a single no-op wheel event so
        // semantics match Playwright's IMouse.WheelAsync(0, 0).
        if (deltaY != 0)
            await SmoothWheelAsync(raw, (int)Math.Round(deltaY), cfg).ConfigureAwait(false);
        if (deltaX != 0)
            await raw.WheelAsync(Math.Round(deltaX), 0).ConfigureAwait(false);
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

        var box = await getBox().ConfigureAwait(false);
        if (box == null)
            throw new InvalidOperationException("Element not found while scrolling into view");

        if (IsInViewport(box.Value, viewportHeight, cfg))
            return new ScrollResult(box.Value, cursorX, cursorY, false);

        // Move cursor into scroll area.
        double scrollAreaX = Math.Round(viewportWidth * HumanRandom.Rand(0.3, 0.7));
        double scrollAreaY = Math.Round(viewportHeight * HumanRandom.Rand(0.3, 0.7));
        await HumanMouse.HumanMoveAsync(raw, cursorX, cursorY, scrollAreaX, scrollAreaY, cfg).ConfigureAwait(false);
        cursorX = scrollAreaX;
        cursorY = scrollAreaY;
        await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ScrollPreMoveDelay)).ConfigureAwait(false);

        // Calculate scroll distance.
        double targetY = viewportHeight * HumanRandom.Rand(cfg.ScrollTargetZone.Min, cfg.ScrollTargetZone.Max);
        double elementCenter = box.Value.Y + box.Value.Height / 2;
        double distanceToScroll = elementCenter - targetY;

        int direction = distanceToScroll > 0 ? 1 : -1;
        double absDistance = Math.Abs(distanceToScroll);
        double avgDelta = (cfg.ScrollDeltaBase.Min + cfg.ScrollDeltaBase.Max) / 2;
        int totalClicks = Math.Max(3, (int)Math.Ceiling(absDistance / avgDelta));
        int accelSteps = HumanRandom.RandIntRange(cfg.ScrollAccelSteps);
        int decelSteps = HumanRandom.RandIntRange(cfg.ScrollDecelSteps);

        // Scroll loop: accelerate -> cruise -> decelerate.
        double scrolled = 0;
        for (int i = 0; i < totalClicks; i++)
        {
            double delta, pause;
            if (i < accelSteps)
            {
                delta = HumanRandom.Rand(80, 100);
                pause = HumanRandom.RandRange(cfg.ScrollPauseSlow);
            }
            else if (i >= totalClicks - decelSteps)
            {
                delta = HumanRandom.Rand(60, 90);
                pause = HumanRandom.RandRange(cfg.ScrollPauseSlow);
            }
            else
            {
                delta = HumanRandom.RandRange(cfg.ScrollDeltaBase);
                pause = HumanRandom.RandRange(cfg.ScrollPauseFast);
            }

            delta *= 1 + (HumanRandom.NextDouble() - 0.5) * 2 * cfg.ScrollDeltaVariance;
            int deltaInt = (int)(Math.Round(delta) * direction);

            await SmoothWheelAsync(raw, deltaInt, cfg).ConfigureAwait(false);
            scrolled += Math.Abs(deltaInt);
            await HumanRandom.SleepMsAsync(pause).ConfigureAwait(false);

            // Check visibility every 3 steps.
            if (i % 3 == 2 || i == totalClicks - 1)
            {
                box = await getBox().ConfigureAwait(false);
                if (box != null && IsInViewport(box.Value, viewportHeight, cfg))
                    break;
            }
            if (scrolled >= absDistance * 1.1)
                break;
        }

        // Optional overshoot + correction.
        if (HumanRandom.NextDouble() < cfg.ScrollOvershootChance)
        {
            int overshootPx = (int)(Math.Round(HumanRandom.RandRange(cfg.ScrollOvershootPx)) * direction);
            await SmoothWheelAsync(raw, overshootPx, cfg).ConfigureAwait(false);
            await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ScrollSettleDelay)).ConfigureAwait(false);
            int corrections = HumanRandom.RandIntRange((1, 2));
            for (int c = 0; c < corrections; c++)
            {
                int corrDelta = (int)(Math.Round(HumanRandom.Rand(40, 80)) * -direction);
                await SmoothWheelAsync(raw, corrDelta, cfg).ConfigureAwait(false);
                await HumanRandom.SleepMsAsync(HumanRandom.Rand(100, 250)).ConfigureAwait(false);
            }
        }

        // Settle.
        await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.ScrollSettleDelay)).ConfigureAwait(false);

        box = await getBox().ConfigureAwait(false);
        if (box == null)
            throw new InvalidOperationException("Element lost after scrolling into view");

        return new ScrollResult(box.Value, cursorX, cursorY, true);
    }
}
