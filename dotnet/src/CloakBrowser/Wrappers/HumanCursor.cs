using CloakBrowser.Human;
using Microsoft.Playwright;

namespace CloakBrowser.Wrappers;

/// <summary>
/// Per-page shared humanize state: one <see cref="HumanEngine"/> (virtual cursor,
/// per-frame isolated worlds, raw input) shared by a <see cref="HumanizedPage"/>, its
/// <see cref="HumanizedMouse"/> / <see cref="HumanizedKeyboard"/>, and every frame,
/// locator and element handle it produces, so cursor motion is continuous across them.
/// </summary>
internal sealed class HumanCursor
{
    private readonly IPage _page;

    public HumanCursor(IPage page)
    {
        _page = page;
        Engine = new HumanEngine(page, new HumanConfig(), new CursorPosition());
    }

    internal HumanEngine Engine { get; private set; }
    internal IPage Page => _page;

    public double X => Engine.Cursor.X;
    public double Y => Engine.Cursor.Y;

    /// <summary>Bind the page config (first wrap wins; per-call overrides go through <c>HumanConfig</c>).</summary>
    internal HumanEngine EngineFor(HumanConfig cfg)
    {
        if (!ReferenceEquals(Engine.Config, cfg) && !_configured)
            Engine = new HumanEngine(_page, cfg, Engine.Cursor);
        _configured = true;
        return Engine;
    }

    private bool _configured;

    /// <summary>Kept for API compatibility: worlds are created lazily per frame.</summary>
    public Task InitStealthAsync() => Task.CompletedTask;

    public async Task EnsureInitializedAsync(HumanConfig cfg)
    {
        try { await EngineFor(cfg).EnsureCursorAsync(cfg).ConfigureAwait(false); }
        catch (PlaywrightException) { /* viewport may not be ready yet; done on first action */ }
    }
}

/// <summary>SelectOption arguments in the shape the engine's selectPlan understands
/// (Playwright's convertSelectOptionValues).</summary>
internal sealed record SelectValues(IReadOnlyList<object> Options, IReadOnlyList<IElementHandle> Handles)
{
    private static IElementHandle Raw(IElementHandle h) => h is HumanizedElementHandle w ? w.Original : h;

    public static SelectValues Of(IEnumerable<string> values) =>
        new(values.Select(v => (object)new Dictionary<string, object> { ["valueOrLabel"] = v }).ToList(), Array.Empty<IElementHandle>());

    public static SelectValues Of(IEnumerable<IElementHandle> handles) =>
        new(Array.Empty<object>(), handles.Select(Raw).ToList());

    public static SelectValues Of(IEnumerable<SelectOptionValue> values) =>
        new(values.Select(v =>
        {
            var o = new Dictionary<string, object>();
            if (v.Value != null) o["value"] = v.Value;
            if (v.Label != null) o["label"] = v.Label;
            if (v.Index != null) o["index"] = v.Index.Value;
            return (object)o;
        }).ToList(), Array.Empty<IElementHandle>());
}
