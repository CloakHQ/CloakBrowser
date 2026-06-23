using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using CloakBrowser.Human;
using Xunit;

namespace CloakBrowser.Tests;

/// <summary>
/// Tests for the headed no-viewport scroll fallback (port of upstream 9c3ed2d /
/// v0.4.1). Headed launches default to no_viewport so <c>page.ViewportSize</c> is
/// null; human scroll must fall back to the live <c>window.innerWidth/innerHeight</c>
/// instead of crashing with "Viewport size not available".
/// </summary>
public class ScrollFallbackTests
{
    private sealed class FakeRawMouse : IRawMouse
    {
        public Task MoveAsync(double x, double y) => Task.CompletedTask;
        public Task DownAsync() => Task.CompletedTask;
        public Task UpAsync() => Task.CompletedTask;
        public Task WheelAsync(double dx, double dy) => Task.CompletedTask;
    }

    /// <summary>Scroll page whose ViewportSize is null (headed) but live window dims resolve.</summary>
    private sealed class NoViewportPage : IRawScrollPage
    {
        private readonly (int, int)? _live;
        public int LiveCalls { get; private set; }
        public NoViewportPage((int, int)? live) => _live = live;

        public (int Width, int Height)? ViewportSize => null;

        public Task<(int Width, int Height)?> GetLiveWindowSizeAsync()
        {
            LiveCalls++;
            return Task.FromResult(_live);
        }
    }

    // Zero out the timing ranges so the scroll loop runs instantly in tests.
    private static HumanConfig FastConfig() => new()
    {
        IdleBetweenActions = false,
        ScrollPreMoveDelay = (0, 0),
        ScrollPauseFast = (0, 0),
        ScrollPauseSlow = (0, 0),
        ScrollSettleDelay = (0, 0),
        ScrollOvershootChance = 0,
        MouseMinSteps = 1,
        MouseMaxSteps = 2,
    };

    [Fact]
    public async Task Null_viewport_falls_back_to_live_window_dimensions()
    {
        var page = new NoViewportPage((1280, 800));
        var raw = new FakeRawMouse();
        // Element far below the fold so a scroll is required (forces use of viewport height).
        BoundingBox? boxBelowFold = new BoundingBox(100, 5000, 50, 20);
        Func<Task<BoundingBox?>> getBox = () => Task.FromResult(boxBelowFold);

        var result = await HumanScroll.HumanScrollIntoViewAsync(
            page, raw, getBox, cursorX: 0, cursorY: 0, FastConfig());

        Assert.Equal(1, page.LiveCalls); // the fallback was consulted
        Assert.True(result.DidScroll);   // and it actually scrolled (no crash)
    }

    [Fact]
    public async Task Null_viewport_and_no_live_dims_throws()
    {
        var page = new NoViewportPage(null); // live fallback also unavailable
        var raw = new FakeRawMouse();
        Func<Task<BoundingBox?>> getBox = () => Task.FromResult<BoundingBox?>(new BoundingBox(0, 0, 10, 10));

        var ex = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            HumanScroll.HumanScrollIntoViewAsync(page, raw, getBox, 0, 0, FastConfig()));
        Assert.Equal("Viewport size not available", ex.Message);
    }

    [Fact]
    public async Task Null_viewport_with_zero_height_live_dims_throws()
    {
        // A live read that returns a 0 height is treated as unusable (matches the
        // Python `not viewport.get("height")` guard).
        var page = new NoViewportPage((1280, 0));
        var raw = new FakeRawMouse();
        Func<Task<BoundingBox?>> getBox = () => Task.FromResult<BoundingBox?>(new BoundingBox(0, 0, 10, 10));

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            HumanScroll.HumanScrollIntoViewAsync(page, raw, getBox, 0, 0, FastConfig()));
    }
}
