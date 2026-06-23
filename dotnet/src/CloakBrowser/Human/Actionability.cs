using Microsoft.Playwright;

namespace CloakBrowser.Human;

// ---------------------------------------------------------------------------
// Error hierarchy
// ---------------------------------------------------------------------------

/// <summary>Base for all actionability failures. Mirrors Python <c>ActionabilityError</c>.</summary>
public class ActionabilityError : Exception
{
    /// <summary>The selector or label of the element that failed.</summary>
    public string Selector { get; }

    /// <summary>The name of the check that failed (attached/visible/stable/...).</summary>
    public string Check { get; }

    public ActionabilityError(string selector, string check, string message)
        : base($"Element '{selector}' failed {check} check: {message}")
    {
        Selector = selector;
        Check = check;
    }
}

/// <summary>The element was never attached to the DOM.</summary>
public sealed class ElementNotAttachedError : ActionabilityError
{
    public ElementNotAttachedError(string selector)
        : base(selector, "attached", "element not found in DOM") { }
}

/// <summary>The element is present but not visible.</summary>
public sealed class ElementNotVisibleError : ActionabilityError
{
    public ElementNotVisibleError(string selector)
        : base(selector, "visible", "element is not visible") { }
}

/// <summary>The element's bounding box keeps moving.</summary>
public sealed class ElementNotStableError : ActionabilityError
{
    public ElementNotStableError(string selector)
        : base(selector, "stable", "element position is still changing") { }
}

/// <summary>The element is disabled.</summary>
public sealed class ElementNotEnabledError : ActionabilityError
{
    public ElementNotEnabledError(string selector)
        : base(selector, "enabled", "element is disabled") { }
}

/// <summary>The element is not editable.</summary>
public sealed class ElementNotEditableError : ActionabilityError
{
    public ElementNotEditableError(string selector)
        : base(selector, "editable", "element is not editable") { }
}

/// <summary>The element is covered by another element at the click point.</summary>
public sealed class ElementNotReceivingEventsError : ActionabilityError
{
    public ElementNotReceivingEventsError(string selector, string coveringTag = "unknown")
        : base(selector, "pointer_events", $"element is covered by <{coveringTag}>") { }
}

// ---------------------------------------------------------------------------
// Checks
// ---------------------------------------------------------------------------

/// <summary>
/// Playwright-style actionability checks for the humanize layer.
/// Direct port of Python <c>cloakbrowser/human/actionability.py</c>.
/// Checks: attached, visible, stable, enabled, editable, receives pointer events.
/// Retry loop with backoff matching Playwright internals: [100, 250, 500, 1000]ms.
/// </summary>
public static class Actionability
{
    /// <summary>Checks for a click action.</summary>
    public static readonly IReadOnlySet<string> ChecksClick =
        new HashSet<string> { "attached", "visible", "enabled", "pointer_events" };

    /// <summary>Checks for a hover action.</summary>
    public static readonly IReadOnlySet<string> ChecksHover =
        new HashSet<string> { "attached", "visible", "pointer_events" };

    /// <summary>Checks for a text-input action.</summary>
    public static readonly IReadOnlySet<string> ChecksInput =
        new HashSet<string> { "attached", "visible", "enabled", "editable", "pointer_events" };

    /// <summary>Checks for a focus action.</summary>
    public static readonly IReadOnlySet<string> ChecksFocus =
        new HashSet<string> { "attached", "visible", "enabled" };

    /// <summary>Checks for a check/uncheck action.</summary>
    public static readonly IReadOnlySet<string> ChecksCheck =
        new HashSet<string> { "attached", "visible", "enabled", "pointer_events" };

    private static readonly int[] BackoffMs = { 100, 250, 500, 1000 };

    private static Task BackoffSleepAsync(int attempt)
    {
        int idx = Math.Min(attempt, BackoffMs.Length - 1);
        return Task.Delay(BackoffMs[idx]);
    }

    private static double NowMs() => Environment.TickCount64;

    /// <summary>
    /// Milliseconds left until <paramref name="deadline"/> (an <see cref="Environment.TickCount64"/>
    /// timestamp), clamped at zero. Sequential operations share one deadline so the total
    /// timeout budget is never multiplied (issue #307). Never returns a negative value.
    /// </summary>
    internal static double RemainingMs(double deadline) => Math.Max(0, deadline - NowMs());

    // -----------------------------------------------------------------------
    // Pre-scroll actionability: attached, visible, enabled, editable
    // -----------------------------------------------------------------------

    /// <summary>
    /// Wait for the element to pass actionability checks (pre-scroll). Retries
    /// with backoff until <paramref name="timeoutMs"/> elapsed. Throws a specific
    /// <see cref="ActionabilityError"/> subclass on failure. Returns immediately
    /// when <paramref name="force"/> is true.
    /// </summary>
    public static async Task EnsureActionableAsync(
        IPage page,
        string selector,
        IReadOnlySet<string> checks,
        double timeoutMs = 30000,
        bool force = false)
    {
        if (force)
            return;

        double deadline = NowMs() + timeoutMs;
        int attempt = 0;
        ActionabilityError? lastError = null;

        while (true)
        {
            double remainingMs = Math.Max(0, deadline - NowMs());
            if (remainingMs <= 0)
            {
                if (lastError != null)
                    throw lastError;
                throw new ActionabilityError(selector, "timeout", "timeout expired before first check");
            }

            try
            {
                var loc = page.Locator(selector).First;

                if (checks.Contains("attached"))
                {
                    try
                    {
                        await loc.WaitForAsync(new LocatorWaitForOptions
                        {
                            State = WaitForSelectorState.Attached,
                            Timeout = (float)Math.Max(1, Math.Min(remainingMs, 2000)),
                        }).ConfigureAwait(false);
                    }
                    catch (Exception) { throw new ElementNotAttachedError(selector); }
                }

                if (checks.Contains("visible") && !await loc.IsVisibleAsync().ConfigureAwait(false))
                    throw new ElementNotVisibleError(selector);

                if (checks.Contains("enabled") && !await loc.IsEnabledAsync().ConfigureAwait(false))
                    throw new ElementNotEnabledError(selector);

                if (checks.Contains("editable") && !await loc.IsEditableAsync().ConfigureAwait(false))
                    throw new ElementNotEditableError(selector);

                return;
            }
            catch (ActionabilityError e)
            {
                lastError = e;
                if (NowMs() >= deadline)
                    throw;
                await BackoffSleepAsync(attempt).ConfigureAwait(false);
                attempt++;
            }
        }
    }

    // -----------------------------------------------------------------------
    // Post-scroll stability check
    // -----------------------------------------------------------------------

    private static bool BoxesDiffer(LocatorBoundingBoxResult a, LocatorBoundingBoxResult b) =>
        Math.Abs(a.X - b.X) > 1
        || Math.Abs(a.Y - b.Y) > 1
        || Math.Abs(a.Width - b.Width) > 1
        || Math.Abs(a.Height - b.Height) > 1;

    /// <summary>
    /// Wait for the element's position to stabilize (two samples 100ms apart).
    /// Only call after a scroll - skip if the element was already in the viewport.
    /// </summary>
    public static async Task EnsureStableAsync(IPage page, string selector, double timeoutMs = 5000)
    {
        double deadline = NowMs() + timeoutMs;
        int attempt = 0;

        while (true)
        {
            double remainingMs = Math.Max(0, deadline - NowMs());
            if (remainingMs <= 0)
                throw new ElementNotStableError(selector);

            var loc = page.Locator(selector).First;
            var box1 = await loc.BoundingBoxAsync(new LocatorBoundingBoxOptions
            {
                Timeout = (float)Math.Max(1, Math.Min(remainingMs, 1000)),
            }).ConfigureAwait(false);
            if (box1 == null)
                throw new ElementNotAttachedError(selector);

            await Task.Delay(100).ConfigureAwait(false);

            var box2 = await loc.BoundingBoxAsync(new LocatorBoundingBoxOptions
            {
                Timeout = (float)Math.Max(1, Math.Min(remainingMs, 1000)),
            }).ConfigureAwait(false);
            if (box2 == null)
                throw new ElementNotAttachedError(selector);

            if (!BoxesDiffer(box1, box2))
                return;

            if (NowMs() >= deadline)
                throw new ElementNotStableError(selector);

            await BackoffSleepAsync(attempt).ConfigureAwait(false);
            attempt++;
        }
    }

    // -----------------------------------------------------------------------
    // Pointer-events check (post-scroll, at actual click coordinates)
    // -----------------------------------------------------------------------

    // data.box is page-space (from boundingBox); rect is frame-local. Their delta
    // is the iframe offset, needed to map page-space click coords into the frame's
    // own viewport before elementFromPoint. For main-frame elements the offset is 0.
    internal const string PointerEventsJs = @"(expected, data) => {
    const rect = expected.getBoundingClientRect();
    const frameOffsetX = data.box ? data.box.x - rect.x : 0;
    const frameOffsetY = data.box ? data.box.y - rect.y : 0;
    const target = document.elementFromPoint(data.x - frameOffsetX, data.y - frameOffsetY);
    if (!target) return { hit: false, reason: 'no_element_at_point', covering: 'none' };
    let node = target;
    while (node) { if (node === expected) return { hit: true }; node = node.parentNode; }
    if (expected.contains(target)) return { hit: true };
    return { hit: false, reason: 'covered', covering: target.tagName || 'unknown' };
}";

    /// <summary>
    /// Result of the <c>elementFromPoint</c> pointer-events probe. Internal (not private)
    /// so unit tests can construct a "covered" result without a live browser.
    /// </summary>
    internal sealed class PointerResult
    {
        public bool Hit { get; set; }
        public string? Reason { get; set; }
        public string? Covering { get; set; }
    }

    /// <summary>
    /// Check that <c>elementFromPoint(x, y)</c> hits the expected element. Uses
    /// <c>locator.evaluate()</c> so all Playwright selector types work. Retries
    /// with backoff for transient overlays. Fails open when the result can't be
    /// determined.
    /// </summary>
    public static async Task CheckPointerEventsAsync(
        IPage page,
        string selector,
        double x,
        double y,
        double timeoutMs = 5000)
    {
        double deadline = NowMs() + timeoutMs;
        int attempt = 0;

        while (true)
        {
            PointerResult? result = null;
            try
            {
                var loc = page.Locator(selector).First;
                var box = await loc.BoundingBoxAsync(new LocatorBoundingBoxOptions
                {
                    Timeout = (float)Math.Max(1, Math.Min(deadline - NowMs(), 1000)),
                }).ConfigureAwait(false);
                var data = new
                {
                    x,
                    y,
                    box = box == null ? null : new { x = box.X, y = box.Y, width = box.Width, height = box.Height },
                };
                result = await loc.EvaluateAsync<PointerResult?>(PointerEventsJs, data).ConfigureAwait(false);
            }
            catch (Exception exc)
            {
                CloakLog.Debug($"pointer_events check failed for '{selector}': {exc.Message}");
                result = null;
            }

            // Proceed if the check confirms a hit, or if it could not be determined
            // (null) - failing closed would block legitimate clicks.
            if (result == null || result.Hit)
                return;

            string covering = result.Covering ?? "unknown";

            if (NowMs() >= deadline)
                throw new ElementNotReceivingEventsError(selector, covering);

            await BackoffSleepAsync(attempt).ConfigureAwait(false);
            attempt++;
        }
    }

    // -----------------------------------------------------------------------
    // ElementHandle variants
    // -----------------------------------------------------------------------

    /// <summary>Actionability checks for an <see cref="IElementHandle"/> (no selector needed).</summary>
    public static async Task EnsureActionableHandleAsync(
        IElementHandle el,
        IReadOnlySet<string> checks,
        double timeoutMs = 30000,
        bool force = false)
    {
        if (force)
            return;

        double deadline = NowMs() + timeoutMs;
        int attempt = 0;
        ActionabilityError? lastError = null;
        const string label = "<ElementHandle>";

        while (true)
        {
            double remainingMs = Math.Max(0, deadline - NowMs());
            if (remainingMs <= 0)
            {
                if (lastError != null)
                    throw lastError;
                throw new ActionabilityError(label, "timeout", "timeout expired before first check");
            }

            try
            {
                if (checks.Contains("visible"))
                {
                    try
                    {
                        await el.WaitForElementStateAsync(ElementState.Visible, new ElementHandleWaitForElementStateOptions
                        {
                            Timeout = (float)Math.Max(1, Math.Min(remainingMs, 2000)),
                        }).ConfigureAwait(false);
                    }
                    catch (Exception) { throw new ElementNotVisibleError(label); }
                }

                if (checks.Contains("enabled"))
                {
                    try
                    {
                        await el.WaitForElementStateAsync(ElementState.Enabled, new ElementHandleWaitForElementStateOptions
                        {
                            Timeout = (float)Math.Max(1, Math.Min(remainingMs, 2000)),
                        }).ConfigureAwait(false);
                    }
                    catch (Exception) { throw new ElementNotEnabledError(label); }
                }

                if (checks.Contains("editable"))
                {
                    try
                    {
                        await el.WaitForElementStateAsync(ElementState.Editable, new ElementHandleWaitForElementStateOptions
                        {
                            Timeout = (float)Math.Max(1, Math.Min(remainingMs, 2000)),
                        }).ConfigureAwait(false);
                    }
                    catch (Exception) { throw new ElementNotEditableError(label); }
                }

                return;
            }
            catch (ActionabilityError e)
            {
                lastError = e;
                if (NowMs() >= deadline)
                    throw;
                await BackoffSleepAsync(attempt).ConfigureAwait(false);
                attempt++;
            }
        }
    }

    /// <summary>Pointer-events check for an <see cref="IElementHandle"/>.</summary>
    public static async Task CheckPointerEventsHandleAsync(
        IElementHandle el,
        double x,
        double y,
        double timeoutMs = 5000)
    {
        double deadline = NowMs() + timeoutMs;
        int attempt = 0;

        while (true)
        {
            PointerResult? result = null;
            try
            {
                var box = await el.BoundingBoxAsync().ConfigureAwait(false);
                var data = new
                {
                    x,
                    y,
                    box = box == null ? null : new { x = box.X, y = box.Y, width = box.Width, height = box.Height },
                };
                result = await el.EvaluateAsync<PointerResult?>(PointerEventsJs, data).ConfigureAwait(false);
            }
            catch (Exception)
            {
                result = null;
            }

            if (result == null || result.Hit)
                return;

            string covering = result.Covering ?? "unknown";

            if (NowMs() >= deadline)
                throw new ElementNotReceivingEventsError("<ElementHandle>", covering);

            await BackoffSleepAsync(attempt).ConfigureAwait(false);
            attempt++;
        }
    }
}
