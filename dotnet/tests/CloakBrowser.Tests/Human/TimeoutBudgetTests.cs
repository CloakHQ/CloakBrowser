using CloakBrowser.Human;
using Xunit;

namespace CloakBrowser.Tests.Human;

/// <summary>
/// Issue #307: every step of one action (wait, scroll, move, hit-test, retry) carves out
/// of a single <see cref="Deadline"/>, so the timeout budget is never multiplied. The
/// end-to-end timing is checked against a real browser in HumanEngineBrowserTests; here
/// the deadline arithmetic itself.
/// </summary>
public class TimeoutBudgetTests
{
    [Fact]
    public void Remaining_never_negative_after_expiry()
    {
        var d = new Deadline(1);
        Thread.Sleep(20);
        Assert.True(d.Expired);
        Assert.Equal(0, d.Remaining);
    }

    [Fact]
    public async Task Remaining_shrinks_and_never_exceeds_the_budget()
    {
        var d = new Deadline(1000);
        var first = d.Remaining;
        await Task.Delay(30);
        var second = d.Remaining;
        Assert.True(first <= 1000);
        Assert.True(second < first);
        Assert.False(d.Expired);
    }

    [Fact]
    public void Zero_timeout_means_no_limit()
    {
        var d = new Deadline(0);
        Assert.False(d.Expired);
        Assert.True(double.IsPositiveInfinity(d.Remaining));
    }

    [Fact]
    public void Nested_steps_share_the_parent_deadline()
    {
        var d = new Deadline(500);
        var nested = new ActOpts { Deadline = d }.With(o => o.Nested = true);
        Assert.Same(d, nested.Deadline);
    }
}
