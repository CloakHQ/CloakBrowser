using System.Linq;
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

// Raised by the previous humanize layer; the engine no longer throws them.

/// <summary>Base for isolated-world DOM helper failures.</summary>
public class StealthDomError : Exception
{
    public StealthDomError(string message) : base(message) { }
}

public sealed class UnsupportedHumanizeSelectorError : StealthDomError
{
    public UnsupportedHumanizeSelectorError(string selector)
        : base($"Humanized selector '{selector}' is not supported") { }
}

public sealed class StealthWorldUnavailableError : StealthDomError
{
    public StealthWorldUnavailableError() : base("Humanized DOM read requires an active isolated world") { }
}

public sealed class StealthEvaluationError : StealthDomError
{
    public StealthEvaluationError(string selector)
        : base($"Isolated-world DOM evaluation failed for '{selector}'") { }
}

// ---------------------------------------------------------------------------
// Checks (public compatibility facade over the humanize engine)
// ---------------------------------------------------------------------------

/// <summary>
/// Playwright-style actionability checks, callable on their own.
///
/// Kept with the pre-engine signatures so existing callers keep compiling and
/// working. Humanized actions no longer call this class: they run the same checks
/// inside <c>HumanEngine</c> and raise Playwright errors. Here the checks run on that
/// engine too (Playwright's InjectedScript in a CDP isolated world per frame), so
/// they accept every Playwright selector (<c>GetByRole</c>, <c>&gt;&gt;</c> chains,
/// filters, frame locators) and leave no page-observable trace. Failures raise the
/// typed <see cref="ActionabilityError"/> subclasses, as before.
///
/// The optional <see cref="IsolatedWorld"/> arguments are accepted for source
/// compatibility and ignored: the engine manages its own per-frame worlds.
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

    private const string HandleLabel = "<ElementHandle>";
    private static readonly int[] BackoffMs = { 100, 250, 500, 1000 };
    private static readonly string[] StateChecks = { "visible", "enabled", "editable" };
    private static readonly System.Runtime.CompilerServices.ConditionalWeakTable<IPage, HumanEngine> Engines = new();

    private static double NowMs() => Environment.TickCount64;

    /// <summary>
    /// Milliseconds left until <paramref name="deadline"/> (an <see cref="Environment.TickCount64"/>
    /// timestamp), clamped at zero (issue #307).
    /// </summary>
    internal static double RemainingMs(double deadline) => Math.Max(0, deadline - NowMs());

    private static Task BackoffAsync(int attempt, double deadline) =>
        Task.Delay(TimeSpan.FromMilliseconds(Math.Min(BackoffMs[Math.Min(attempt, BackoffMs.Length - 1)],
            Math.Max(1, RemainingMs(deadline)))));

    /// <summary>The engine of a page: the humanized page's own one (shared cursor and
    /// worlds), or a private one for a page that was never humanized.</summary>
    private static HumanEngine EngineOf(IPage page)
    {
        var raw = page is CloakBrowser.Wrappers.HumanizedPage hp ? hp.Original : page;
        if (CloakBrowser.Wrappers.Humanize.TryGetCursor(raw, out var cursor)) return cursor.Engine;
        return Engines.GetValue(raw, p => new HumanEngine(p, new HumanConfig(), new CursorPosition()));
    }

    private static (HumanEngine Engine, Target Target) ForSelector(IPage page, string selector)
    {
        var engine = EngineOf(page);
        return (engine, new Target(engine.Page.MainFrame, selector));
    }

    private static (HumanEngine Engine, Target Target) ForHandle(IElementHandle el)
    {
        var raw = el is CloakBrowser.Wrappers.HumanizedElementHandle h ? h.Original : el;
        var frame = PlaywrightInternals.HandleFrame(raw);
        return (EngineOf(frame.Page), new Target(frame, null, handle: raw));
    }

    /// <summary>Map the engine's last retry reason to the typed error of this API.</summary>
    private static ActionabilityError Typed(string label, string? reason) => reason switch
    {
        null => new ActionabilityError(label, "timeout", "timeout expired before first check"),
        _ when reason.StartsWith("waiting for", StringComparison.Ordinal) => new ElementNotAttachedError(label),
        _ when reason.Contains("detached", StringComparison.Ordinal) => new ElementNotAttachedError(label),
        "element is not visible" => new ElementNotVisibleError(label),
        "element is not enabled" => new ElementNotEnabledError(label),
        "element is not editable" => new ElementNotEditableError(label),
        "element is not attached" => new ElementNotAttachedError(label),
        _ => new ActionabilityError(label, "timeout", reason),
    };

    /// <summary>Run <paramref name="attempt"/> until it succeeds or the budget is spent
    /// (at least once). Retryable failures surface as <paramref name="fail"/>(last reason).</summary>
    private static async Task<T> RetryAsync<T>(double timeoutMs, Func<Task<T>> attempt, Func<string?, Exception> fail)
    {
        double deadline = NowMs() + Math.Max(0, timeoutMs);
        string? reason = null;
        for (int n = 0; ; n++)
        {
            try
            {
                return await attempt().ConfigureAwait(false);
            }
            catch (RetryException r) { reason = r.Message; }
            catch (StaleElementException) { reason = "element was detached from the DOM"; }
            if (NowMs() >= deadline) throw fail(reason);
            await BackoffAsync(n, deadline).ConfigureAwait(false);
        }
    }

    private static string[] States(IReadOnlySet<string> checks) => StateChecks.Where(checks.Contains).ToArray();

    // -----------------------------------------------------------------------
    // Element states: attached, visible, enabled, editable
    // -----------------------------------------------------------------------

    /// <summary>
    /// Wait for the element to be attached and to pass <paramref name="checks"/>
    /// (<c>visible</c>, <c>enabled</c>, <c>editable</c>; <c>pointer_events</c> is checked
    /// at the click point by <see cref="CheckPointerEventsAsync(IPage, string, double, double, double, IsolatedWorld?)"/>).
    /// Throws an <see cref="ActionabilityError"/> subclass when the budget is spent.
    /// Returns immediately when <paramref name="force"/> is true.
    /// </summary>
    public static Task EnsureActionableAsync(
        IPage page,
        string selector,
        IReadOnlySet<string> checks,
        double timeoutMs = 30000,
        bool force = false,
        IsolatedWorld? stealth = null)
    {
        if (force) return Task.CompletedTask;
        var (engine, target) = ForSelector(page, selector);
        var states = States(checks);
        return RetryAsync(timeoutMs, () => engine.AttemptStatesAsync(target, states, false),
            reason => Typed(selector, reason));
    }

    /// <summary>Element-state checks for an <see cref="IElementHandle"/>.</summary>
    public static Task EnsureActionableHandleAsync(
        IElementHandle el,
        IReadOnlySet<string> checks,
        double timeoutMs = 30000,
        bool force = false)
    {
        if (force) return Task.CompletedTask;
        var (engine, target) = ForHandle(el);
        var states = States(checks);
        return RetryAsync(timeoutMs, () => engine.AttemptStatesAsync(target, states, false),
            reason => Typed(HandleLabel, reason));
    }

    // -----------------------------------------------------------------------
    // Stability
    // -----------------------------------------------------------------------

    /// <summary>
    /// Wait until the element's box stops moving (two reads 100 ms apart differ by at
    /// most 1 px). Throws <see cref="ElementNotStableError"/> when the budget is spent,
    /// <see cref="ElementNotAttachedError"/> if the element never appears.
    /// </summary>
    public static Task EnsureStableAsync(IPage page, string selector, double timeoutMs = 5000, IsolatedWorld? stealth = null)
    {
        var (engine, target) = ForSelector(page, selector);
        bool found = false;
        return RetryAsync(timeoutMs, async () =>
        {
            var r = await engine.ResolveAsync(target).ConfigureAwait(false);
            found = true;
            var a = await engine.ElementBoxAsync(r).ConfigureAwait(false);
            await Task.Delay(100).ConfigureAwait(false);
            var b = await engine.ElementBoxAsync(r).ConfigureAwait(false);
            if (Math.Abs(a.X - b.X) > 1 || Math.Abs(a.Y - b.Y) > 1 ||
                Math.Abs(a.Width - b.Width) > 1 || Math.Abs(a.Height - b.Height) > 1)
                throw new RetryException("element is not stable");
            return true;
        }, reason => found ? new ElementNotStableError(selector) : new ElementNotAttachedError(selector));
    }

    // -----------------------------------------------------------------------
    // Pointer events at the actual click point
    // -----------------------------------------------------------------------

    /// <summary>
    /// Wait until a click at viewport point (<paramref name="x"/>, <paramref name="y"/>)
    /// would land on the element: Playwright's hit-target check, also through every
    /// ancestor <c>&lt;iframe&gt;</c>. Throws <see cref="ElementNotReceivingEventsError"/>
    /// naming the covering element when the budget is spent.
    /// </summary>
    public static Task CheckPointerEventsAsync(
        IPage page,
        string selector,
        double x,
        double y,
        double timeoutMs = 5000,
        IsolatedWorld? stealth = null)
    {
        var (engine, target) = ForSelector(page, selector);
        return PointerAsync(engine, target, selector, x, y, timeoutMs);
    }

    /// <summary>
    /// Overload kept for source compatibility. <paramref name="targetId"/> and
    /// <paramref name="gen"/> identified elements in the old resolver and are ignored;
    /// the element is re-resolved from <paramref name="selector"/>.
    /// </summary>
    public static Task CheckPointerEventsAsync(
        IPage page,
        string selector,
        int targetId,
        int gen,
        double x,
        double y,
        double timeoutMs = 5000,
        IsolatedWorld? stealth = null) =>
        CheckPointerEventsAsync(page, selector, x, y, timeoutMs, stealth);

    /// <summary>Pointer-events check for an <see cref="IElementHandle"/>.</summary>
    public static Task CheckPointerEventsHandleAsync(
        IElementHandle el,
        double x,
        double y,
        double timeoutMs = 5000)
    {
        var (engine, target) = ForHandle(el);
        return PointerAsync(engine, target, HandleLabel, x, y, timeoutMs);
    }

    private const string Intercepts = " intercepts pointer events";

    private static Task PointerAsync(HumanEngine engine, Target target, string label, double x, double y, double timeoutMs)
    {
        bool found = false;
        return RetryAsync(timeoutMs, async () =>
        {
            var r = await engine.ResolveAsync(target).ConfigureAwait(false);
            found = true;
            await engine.HitAsync(r, x, y).ConfigureAwait(false);
            return true;
        }, reason =>
        {
            if (!found) return Typed(label, reason);
            if (reason != null && reason.EndsWith(Intercepts, StringComparison.Ordinal))
                return new ElementNotReceivingEventsError(label, reason[..^Intercepts.Length]);
            if (reason == "element is outside of the viewport")
                return new ElementNotReceivingEventsError(label, "nothing: the point is outside the viewport");
            return Typed(label, reason);
        });
    }
}
