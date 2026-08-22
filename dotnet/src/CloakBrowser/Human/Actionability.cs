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

/// <summary>The selector resolved to a different element before input dispatch.</summary>
public sealed class ElementTargetChangedError : ActionabilityError
{
    public ElementTargetChangedError(string selector)
        : base(selector, "target_identity", "selector resolved to a different element before input dispatch") { }
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
        bool force = false,
        IsolatedWorld? stealth = null)
    {
        if (force)
            return;
        if (stealth == null)
            throw new StealthWorldUnavailableError();

        double deadline = NowMs() + timeoutMs;
        int attempt = 0;
        Exception? lastError = null;

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
                var (status, snapshot) = await StealthDom.ActionableAsync(
                    stealth, selector).ConfigureAwait(false);
                if (status == StealthStatus.Unsupported)
                    throw new UnsupportedHumanizeSelectorError(selector);
                if (status == StealthStatus.EvaluationFailed)
                    throw new StealthEvaluationError(selector);
                if (status == StealthStatus.NotFound)
                    throw new ElementNotAttachedError(selector);
                if (status != StealthStatus.Ok || snapshot == null)
                    throw new StealthEvaluationError(selector);

                var value = snapshot.Value;
                if (checks.Contains("visible") && !value.Visible)
                    throw new ElementNotVisibleError(selector);
                if (checks.Contains("enabled") && !value.Enabled)
                    throw new ElementNotEnabledError(selector);
                if (checks.Contains("editable") && !value.Editable)
                    throw new ElementNotEditableError(selector);
                return;
            }
            catch (Exception error) when (error is ActionabilityError or StealthEvaluationError)
            {
                lastError = error;
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

    private static bool BoxesDiffer(BoundingBox a, BoundingBox b) =>
        Math.Abs(a.X - b.X) > 1
        || Math.Abs(a.Y - b.Y) > 1
        || Math.Abs(a.Width - b.Width) > 1
        || Math.Abs(a.Height - b.Height) > 1;

    /// <summary>Bounding box via the isolated world only.</summary>
    private static async Task<BoundingBox?> ReadBoxAsync(
        IPage page, string selector, IsolatedWorld? stealth, double remainingMs)
    {
        if (stealth == null)
            throw new StealthWorldUnavailableError();

        var (status, target) = await StealthDom.BoxAsync(stealth, selector).ConfigureAwait(false);
        return status switch
        {
            StealthStatus.Ok when target != null => target.Value.Box,
            StealthStatus.NotFound => null,
            StealthStatus.Unsupported => throw new UnsupportedHumanizeSelectorError(selector),
            _ => throw new StealthEvaluationError(selector),
        };
    }

    /// <summary>
    /// Wait for the element's position to stabilize (two samples 100ms apart).
    /// Only call after a scroll - skip if the element was already in the viewport.
    /// </summary>
    public static async Task EnsureStableAsync(IPage page, string selector, double timeoutMs = 5000, IsolatedWorld? stealth = null)
    {
        double deadline = NowMs() + timeoutMs;
        int attempt = 0;

        while (true)
        {
            double remainingMs = Math.Max(0, deadline - NowMs());
            if (remainingMs <= 0)
                throw new ElementNotStableError(selector);

            try
            {
                var box1 = await ReadBoxAsync(page, selector, stealth, remainingMs).ConfigureAwait(false);
                if (box1 == null)
                    throw new ElementNotAttachedError(selector);

                await Task.Delay(100).ConfigureAwait(false);

                var box2 = await ReadBoxAsync(page, selector, stealth, remainingMs).ConfigureAwait(false);
                if (box2 == null)
                    throw new ElementNotAttachedError(selector);

                if (!BoxesDiffer(box1.Value, box2.Value))
                    return;
            }
            catch (StealthEvaluationError)
            {
                if (NowMs() >= deadline)
                    throw;
                await BackoffSleepAsync(attempt).ConfigureAwait(false);
                attempt++;
                continue;
            }

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
    /// Compatibility overload for callers that do not yet carry a canonical target ID.
    /// It snapshots the target in the isolated world, then delegates to identity-aware
    /// revalidation. New interaction paths should pass the original target ID directly.
    /// </summary>
    public static async Task CheckPointerEventsAsync(
        IPage page,
        string selector,
        double x,
        double y,
        double timeoutMs = 5000,
        IsolatedWorld? stealth = null)
    {
        if (stealth == null)
            throw new StealthWorldUnavailableError();

        var (status, snapshot) = await StealthDom.SnapshotAsync(stealth, selector).ConfigureAwait(false);
        var resolved = status switch
        {
            StealthStatus.Ok when snapshot != null => snapshot.Value,
            StealthStatus.NotFound => throw new ElementNotAttachedError(selector),
            StealthStatus.Unsupported => throw new UnsupportedHumanizeSelectorError(selector),
            _ => throw new StealthEvaluationError(selector),
        };
        await CheckPointerEventsAsync(
            page, selector, resolved.TargetId, resolved.Gen, x, y, timeoutMs, stealth).ConfigureAwait(false);
    }

    /// <summary>
    /// Revalidate that the click point still hits the same resolved element.
    /// Callers skip this entirely when force is set (matching Playwright, where
    /// force bypasses all actionability checks).
    /// </summary>
    public static async Task CheckPointerEventsAsync(
        IPage page,
        string selector,
        int targetId,
        int gen,
        double x,
        double y,
        double timeoutMs = 5000,
        IsolatedWorld? stealth = null)
    {
        if (stealth == null)
            throw new StealthWorldUnavailableError();

        double deadline = NowMs() + timeoutMs;
        int attempt = 0;

        while (true)
        {
            var (status, hit, covering, _) = await StealthDom.ValidateAsync(
                stealth, selector, targetId, gen, x, y).ConfigureAwait(false);

            if (status == StealthStatus.Unsupported)
                throw new UnsupportedHumanizeSelectorError(selector);
            if (status == StealthStatus.Stale)
                throw new ElementTargetChangedError(selector);
            if (status == StealthStatus.NotFound)
                throw new ElementNotAttachedError(selector);
            if (status == StealthStatus.EvaluationFailed)
            {
                if (NowMs() >= deadline)
                    throw new StealthEvaluationError(selector);
            }
            else if (status == StealthStatus.Ok && hit)
            {
                return;
            }
            else if (status == StealthStatus.Ok)
            {
                if (NowMs() >= deadline)
                    throw new ElementNotReceivingEventsError(selector, covering);
            }
            else
            {
                throw new StealthEvaluationError(selector);
            }

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
        string? lastMiss = null;

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

            // See the locator variant: an indeterminate result fails open, but a
            // miss that was already determined must not be laundered into a pass
            // by a late attempt that merely errored (#329).
            if (result == null)
            {
                if (lastMiss != null && NowMs() >= deadline)
                    throw new ElementNotReceivingEventsError("<ElementHandle>", lastMiss);
                return;
            }
            if (result.Hit)
                return;

            string covering = result.Covering ?? "unknown";
            lastMiss = covering;

            if (NowMs() >= deadline)
                throw new ElementNotReceivingEventsError("<ElementHandle>", covering);

            await BackoffSleepAsync(attempt).ConfigureAwait(false);
            attempt++;
        }
    }
}
