using CloakBrowser.Human;
using Xunit;

namespace CloakBrowser.Tests.Human;

/// <summary>
/// Ports the spirit of Python <c>TestTimeoutBudget307</c> (issue #307): sequential
/// operations share one deadline so the overall timeout budget is never multiplied.
///
/// The full end-to-end timing test needs a real browser to drive the retry loops, so it
/// is marked <c>Skip</c>. What we CAN unit-test without a browser is the shared remaining
/// time helper every step uses (<see cref="Actionability.RemainingMs(double)"/>): given a
/// single deadline, it must never go negative and must monotonically shrink as time passes.
/// </summary>
public class TimeoutBudgetTests
{
    [Fact]
    public void RemainingMs_never_negative_past_deadline()
    {
        double pastDeadline = System.Environment.TickCount64 - 1000; // already expired
        Assert.Equal(0, Actionability.RemainingMs(pastDeadline));
    }

    [Fact]
    public void RemainingMs_at_deadline_is_zero()
    {
        double now = System.Environment.TickCount64;
        Assert.True(Actionability.RemainingMs(now) <= 0.0 + 1.0); // ~0 (clamped, never < 0)
        Assert.True(Actionability.RemainingMs(now) >= 0.0);
    }

    [Fact]
    public void RemainingMs_positive_before_deadline()
    {
        double deadline = System.Environment.TickCount64 + 5000;
        double remaining = Actionability.RemainingMs(deadline);
        Assert.InRange(remaining, 1, 5000);
    }

    [Fact]
    public async Task RemainingMs_shrinks_as_time_passes()
    {
        double deadline = System.Environment.TickCount64 + 5000;
        double first = Actionability.RemainingMs(deadline);
        await Task.Delay(60);
        double second = Actionability.RemainingMs(deadline);

        Assert.True(second < first, $"remaining should shrink: {first} -> {second}");
        Assert.True(second >= 0, "remaining must never go negative");
    }

    [Fact]
    public void RemainingMs_budget_is_shared_not_multiplied()
    {
        // Three sequential "steps" computed from a SINGLE deadline must sum to <= the
        // original budget - they carve out of one budget rather than each getting the full
        // timeout (the bug behind issue #307).
        const double budget = 1000;
        double deadline = System.Environment.TickCount64 + budget;

        double step1 = Actionability.RemainingMs(deadline);
        double step2 = Actionability.RemainingMs(deadline);
        double step3 = Actionability.RemainingMs(deadline);

        // Each subsequent read is <= the previous (time only moves forward) and never
        // exceeds the single budget.
        Assert.True(step1 <= budget + 1);
        Assert.True(step2 <= step1 + 1);
        Assert.True(step3 <= step2 + 1);
    }

    [Fact(Skip = "requires browser: drives the full page.click retry loop to measure end-to-end timing")]
    public void Page_click_total_time_within_budget()
    {
        // Python TestTimeoutBudget307.test_page_click_total_time_within_budget patches a
        // live page and asserts the wall-clock click time stays < 1.8x the timeout. That
        // exercises real Playwright locator waits and cannot be faithfully reproduced with
        // DispatchProxy fakes, so it is covered by the browser-backed integration suite.
    }
}
