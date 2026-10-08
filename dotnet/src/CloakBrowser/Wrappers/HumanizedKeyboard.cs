using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Transparent humanizing decorator over Playwright's <see cref="IKeyboard"/>.
///
/// Intercepted (humanized): <c>TypeAsync</c> (per-key timing, safe mistypes, Shift for
/// uppercase and symbols). <c>PressAsync</c>, <c>InsertTextAsync</c>, <c>DownAsync</c> and
/// <c>UpAsync</c> are deliberate primitives and are delegated unchanged by the generator.
/// </summary>
[GenerateInterfaceDelegation(typeof(IKeyboard))]
public sealed partial class HumanizedKeyboard : IKeyboard
{
    private readonly IKeyboard _inner;
    private readonly HumanCursor _cursor;
    private readonly HumanConfig _cfg;

    internal HumanizedKeyboard(IKeyboard inner, HumanCursor cursor, HumanConfig cfg)
    {
        _inner = inner;
        _cursor = cursor;
        _cfg = cfg;
    }

    /// <summary>The original, un-humanized Playwright keyboard (escape hatch for raw speed).</summary>
    public IKeyboard Original => _inner;

    /// <summary>Alias of <see cref="Original"/>.</summary>
    public IKeyboard Inner => _inner;

    public Task TypeAsync(string text, KeyboardTypeOptions? options = null) =>
        _cursor.EngineFor(_cfg).KeyboardTypeAsync(text, options?.Delay);
}
