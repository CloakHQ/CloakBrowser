using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Transparent humanizing decorator over Playwright's <see cref="IKeyboard"/>.
///
/// Intercepted (humanized): <c>TypeAsync</c>, <c>PressAsync</c>, <c>InsertTextAsync</c>.
/// Low-level <c>DownAsync</c>/<c>UpAsync</c> are delegated to the inner keyboard by the
/// source generator (they are deliberate single key transitions, not "typing").
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
        _cursor.HumanTypeAsync(text, _cfg);

    public async Task PressAsync(string key, KeyboardPressOptions? options = null)
    {
        // A single human key press: brief aim delay, then the inner press (which
        // already presses down + up). Mirrors the press timing used elsewhere.
        await HumanRandom.SleepMsAsync(HumanRandom.Rand(50, 150)).ConfigureAwait(false);
        await _inner.PressAsync(key, options).ConfigureAwait(false);
    }

    public Task InsertTextAsync(string text) =>
        // InsertText is an atomic IME-style insertion; humanize it as paced typing.
        _cursor.HumanTypeAsync(text, _cfg);
}
