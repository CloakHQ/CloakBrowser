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

        public Task<(double Y, double MaxY)?> GetScrollStateAsync() =>
            Task.FromResult<(double, double)?>((0, 0));
    }

    /// <summary>Scroll page with a fixed viewport and configurable scroll position.</summary>
    private sealed class ViewportPage : IRawScrollPage
    {
        private readonly (int, int) _size;
        private readonly (double, double)? _scroll;
        public ViewportPage((int, int) size, (double, double)? scroll)
        {
            _size = size;
            _scroll = scroll;
        }

        public (int Width, int Height)? ViewportSize => _size;
        public Task<(int Width, int Height)?> GetLiveWindowSizeAsync() =>
            Task.FromResult<(int, int)?>(_size);
        public Task<(double Y, double MaxY)?> GetScrollStateAsync() =>
            Task.FromResult(_scroll);
    }

    private sealed class CountingMouse : IRawMouse
    {
        public int WheelCalls { get; private set; }
        public Task MoveAsync(double x, double y) => Task.CompletedTask;
        public Task DownAsync() => Task.CompletedTask;
        public Task UpAsync() => Task.CompletedTask;
        public Task WheelAsync(double dx, double dy) { WheelCalls++; return Task.CompletedTask; }
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

    [Fact]
    public async Task Fully_visible_above_zone_at_top_bails_without_scrolling()
    {
        // viewport 720 -> zone [144, 576]; element top=50 is above the zone but
        // fully visible, and the page is pinned at the top (y=0). Must not scroll.
        var page = new ViewportPage((1280, 720), scroll: (0, 2000));
        var mouse = new CountingMouse();
        Func<Task<BoundingBox?>> getBox = () => Task.FromResult<BoundingBox?>(new BoundingBox(200, 50, 50, 30));

        var result = await HumanScroll.HumanScrollIntoViewAsync(page, mouse, getBox, 0, 0, FastConfig());

        Assert.False(result.DidScroll);
        Assert.Equal(0, mouse.WheelCalls);
    }

    [Fact]
    public async Task Fully_visible_above_zone_with_room_still_scrolls()
    {
        // Same element, but the page is scrolled down (y=500) so it CAN scroll up.
        var page = new ViewportPage((1280, 720), scroll: (500, 2000));
        var mouse = new CountingMouse();
        Func<Task<BoundingBox?>> getBox = () => Task.FromResult<BoundingBox?>(new BoundingBox(200, 50, 50, 30));

        await HumanScroll.HumanScrollIntoViewAsync(page, mouse, getBox, 0, 0, FastConfig());

        Assert.True(mouse.WheelCalls > 0);
    }
}
