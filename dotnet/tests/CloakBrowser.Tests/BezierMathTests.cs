using CloakBrowser.Human;
using Xunit;

namespace CloakBrowser.Tests;

public class BezierMathTests
{
    // Mirrors Python _FakeRawMouse - records every movement point.
    private sealed class FakeRawMouse : IRawMouse
    {
        public List<(double X, double Y)> Moves { get; } = new();
        public Task MoveAsync(double x, double y) { Moves.Add((x, y)); return Task.CompletedTask; }
        public Task DownAsync() => Task.CompletedTask;
        public Task UpAsync() => Task.CompletedTask;
        public Task WheelAsync(double dx, double dy) => Task.CompletedTask;
    }

    private static HumanConfig Cfg() => new()
    {
        MouseOvershootChance = 0,   // deterministic so the end-point assertion is stable
        MouseBurstPause = (0, 0),
    };

    [Fact]
    public async Task GeneratesMultiplePoints_AndEndsNearTarget()
    {
        var raw = new FakeRawMouse();
        await HumanMouse.HumanMoveAsync(raw, 0, 0, 500, 300, Cfg());

        Assert.True(raw.Moves.Count >= 10, $"too few points: {raw.Moves.Count}");
        var (lx, ly) = raw.Moves[^1];
        Assert.True(Math.Abs(lx - 500) < 10, $"end X off: {lx}");
        Assert.True(Math.Abs(ly - 300) < 10, $"end Y off: {ly}");
    }

    [Fact]
    public async Task NoLargeJumps_BetweenConsecutivePoints()
    {
        var raw = new FakeRawMouse();
        await HumanMouse.HumanMoveAsync(raw, 0, 0, 400, 400, Cfg());

        double total = Math.Sqrt(400 * 400 + 400 * 400);
        double maxJump = total * 0.5;
        for (int i = 1; i < raw.Moves.Count; i++)
        {
            double dx = raw.Moves[i].X - raw.Moves[i - 1].X;
            double dy = raw.Moves[i].Y - raw.Moves[i - 1].Y;
            Assert.True(Math.Sqrt(dx * dx + dy * dy) < maxJump, $"jump too big at {i}");
        }
    }

    [Fact]
    public async Task NotStraightLine_HasDeviation()
    {
        double maxDev = 0;
        for (int t = 0; t < 5; t++)
        {
            var raw = new FakeRawMouse();
            await HumanMouse.HumanMoveAsync(raw, 0, 0, 500, 0, Cfg());
            foreach (var (_, y) in raw.Moves)
                maxDev = Math.Max(maxDev, Math.Abs(y));
        }
        Assert.True(maxDev > 0.5, $"path is basically straight: maxDev={maxDev}");
    }

    [Fact]
    public async Task ShortDistance_StillMovesOrNoOp()
    {
        var raw = new FakeRawMouse();
        await HumanMouse.HumanMoveAsync(raw, 100, 100, 103, 102, Cfg());
        // Python requires >= 1; in .NET dist < 1 -> early return, here dist ~3.6 so it must move.
        Assert.True(raw.Moves.Count >= 1);
    }
}
