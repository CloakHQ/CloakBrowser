using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Transparent humanizing decorator over Playwright's <see cref="IMouse"/>.
///
/// Intercepted (humanized): <c>MoveAsync</c> (Bezier path; <c>Steps</c> is honoured as a
/// straight Playwright move), <c>ClickAsync</c> / <c>DblClickAsync</c> (curve + real
/// press sequence, <c>Button</c> / <c>ClickCount</c> / <c>Delay</c> honoured). Down/Up/Wheel
/// are deliberate low-level primitives and are delegated unchanged by the generator.
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

    private HumanEngine E => _cursor.EngineFor(_cfg);

    public Task MoveAsync(float x, float y, MouseMoveOptions? options = null) => E.MouseMoveAsync(x, y, options?.Steps);

    public Task ClickAsync(float x, float y, MouseClickOptions? options = null) =>
        E.MouseClickAsync(x, y, options?.Delay, options?.Button, options?.ClickCount);

    public Task DblClickAsync(float x, float y, MouseDblClickOptions? options = null) =>
        E.MouseClickAsync(x, y, options?.Delay, options?.Button, 2);
}
