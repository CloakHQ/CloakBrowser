using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Transparent humanizing decorator over Playwright's <see cref="IMouse"/>.
///
/// Intercepted (humanized): <c>MoveAsync</c>, <c>ClickAsync</c>, <c>DblClickAsync</c>,
/// <c>DownAsync</c>, <c>UpAsync</c>, <c>WheelAsync</c>. Everything else is delegated
/// to the inner mouse by the source generator.
/// </summary>
[GenerateInterfaceDelegation(typeof(IMouse))]
public sealed partial class HumanizedMouse : IMouse
{
    private readonly IMouse _inner;
    private readonly HumanCursor _cursor;
    private readonly HumanConfig _cfg;

    internal HumanizedMouse(IMouse inner, HumanCursor cursor, HumanConfig cfg)
    {
        _inner = inner;
        _cursor = cursor;
        _cfg = cfg;
    }

    /// <summary>The original, un-humanized Playwright mouse (escape hatch for raw speed).</summary>
    public IMouse Original => _inner;

    /// <summary>Alias of <see cref="Original"/>.</summary>
    public IMouse Inner => _inner;

    public async Task MoveAsync(float x, float y, MouseMoveOptions? options = null)
    {
        await _cursor.EnsureInitializedAsync(_cfg).ConfigureAwait(false);
        await HumanMouse.HumanMoveAsync(_cursor.RawMouse, _cursor.X, _cursor.Y, x, y, _cfg).ConfigureAwait(false);
        _cursor.Set(x, y);
    }

    public async Task ClickAsync(float x, float y, MouseClickOptions? options = null)
    {
        await _cursor.EnsureInitializedAsync(_cfg).ConfigureAwait(false);
        await HumanMouse.HumanMoveAsync(_cursor.RawMouse, _cursor.X, _cursor.Y, x, y, _cfg).ConfigureAwait(false);
        _cursor.Set(x, y);
        await HumanMouse.HumanClickAsync(_cursor.RawMouse, isInput: false, _cfg).ConfigureAwait(false);
    }

    public async Task DblClickAsync(float x, float y, MouseDblClickOptions? options = null)
    {
        await _cursor.EnsureInitializedAsync(_cfg).ConfigureAwait(false);
        await HumanMouse.HumanMoveAsync(_cursor.RawMouse, _cursor.X, _cursor.Y, x, y, _cfg).ConfigureAwait(false);
        _cursor.Set(x, y);
        await _cursor.RawMouseDownAsync(2).ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(30, 60)).ConfigureAwait(false);
        await _cursor.RawMouseUpAsync(2).ConfigureAwait(false);
    }

    public async Task DownAsync(MouseDownOptions? options = null)
    {
        await HumanRandom.SleepMsAsync(HumanRandom.RandRange(_cfg.ClickHoldButton)).ConfigureAwait(false);
        await _inner.DownAsync(options).ConfigureAwait(false);
    }

    public async Task UpAsync(MouseUpOptions? options = null)
    {
        await HumanRandom.SleepMsAsync(HumanRandom.RandRange(_cfg.ClickHoldButton)).ConfigureAwait(false);
        await _inner.UpAsync(options).ConfigureAwait(false);
    }

    public async Task WheelAsync(float deltaX, float deltaY)
    {
        await HumanScroll.SmoothWheelAsync(_cursor.RawMouse, deltaX, deltaY, _cfg).ConfigureAwait(false);
    }
}
