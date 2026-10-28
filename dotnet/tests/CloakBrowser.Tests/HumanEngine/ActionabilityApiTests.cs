using CloakBrowser.Human;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests.HumanEngine;

/// <summary>The public <see cref="Actionability"/> API, kept for callers that use it
/// directly, now runs on the engine: typed errors, every Playwright selector.</summary>
[Collection("RealBrowser")]
public class ActionabilityApiTests : IClassFixture<EngineFixture>, IAsyncLifetime
{
    private readonly EngineFixture _f;
    private readonly List<IPage> _pages = new();
    public ActionabilityApiTests(EngineFixture f) => _f = f;

    public Task InitializeAsync() => Task.CompletedTask;
    public async Task DisposeAsync()
    {
        foreach (var p in _pages) { try { await p.CloseAsync(); } catch { } }
    }

    private async Task<IPage> Open(bool humanized)
    {
        var p = humanized ? await _f.Handle!.Browser.NewPageAsync() : await _f.Handle!.RawBrowser.NewPageAsync();
        _pages.Add(p);
        await p.GotoAsync(_f.Url + "index.html");
        return p;
    }

    private static async Task<(double X, double Y)> Center(IPage p, string sel)
    {
        var b = (await p.Locator(sel).BoundingBoxAsync())!;
        return (b.X + b.Width / 2, b.Y + b.Height / 2);
    }

    [BrowserTheory]
    [InlineData(true)]
    [InlineData(false)]
    public async Task Passes_and_accepts_engine_selectors(bool humanized)
    {
        var p = await Open(humanized);
        await Actionability.EnsureActionableAsync(p, "#btn", Actionability.ChecksClick, 2000);
        await Actionability.EnsureActionableAsync(p, "internal:role=button[name=\"Press me\"i]", Actionability.ChecksClick, 2000);
        await Actionability.EnsureActionableAsync(p, "#name", Actionability.ChecksInput, 2000);
        await Actionability.EnsureStableAsync(p, "#btn", 2000);
        var (x, y) = await Center(p, "#btn");
        await Actionability.CheckPointerEventsAsync(p, "#btn", x, y, 2000);
    }

    [BrowserFact]
    public async Task Typed_errors_for_missing_hidden_disabled_readonly()
    {
        var p = await Open(true);
        await p.Locator("#btn").EvaluateAsync("b => { b.insertAdjacentHTML('afterend', " +
            "'<button id=\"hid\" style=\"display:none\">h</button><button id=\"dis\" disabled>d</button><input id=\"ro\" readonly>'); }");
        await Assert.ThrowsAsync<ElementNotAttachedError>(() =>
            Actionability.EnsureActionableAsync(p, "#nope", Actionability.ChecksClick, 300));
        await Assert.ThrowsAsync<ElementNotVisibleError>(() =>
            Actionability.EnsureActionableAsync(p, "#hid", Actionability.ChecksClick, 300));
        await Assert.ThrowsAsync<ElementNotEnabledError>(() =>
            Actionability.EnsureActionableAsync(p, "#dis", Actionability.ChecksClick, 300));
        await Assert.ThrowsAsync<ElementNotEditableError>(() =>
            Actionability.EnsureActionableAsync(p, "#ro", Actionability.ChecksInput, 300));
        await Actionability.EnsureActionableAsync(p, "#dis", Actionability.ChecksClick, 300, force: true);
    }

    [BrowserFact]
    public async Task Covered_point_names_the_covering_element()
    {
        var p = await Open(true);
        await p.Locator("#covered").ScrollIntoViewIfNeededAsync();
        var (x, y) = await Center(p, "#covered");
        var e = await Assert.ThrowsAsync<ElementNotReceivingEventsError>(() =>
            Actionability.CheckPointerEventsAsync(p, "#covered", x, y, 300));
        Assert.Contains("over", e.Message);
        Assert.Equal("pointer_events", e.Check);
    }

    [BrowserFact]
    public async Task Element_handle_variants()
    {
        var p = await Open(true);
        var h = (await p.QuerySelectorAsync("#btn"))!;
        await Actionability.EnsureActionableHandleAsync(h, Actionability.ChecksClick, 2000);
        var (x, y) = await Center(p, "#btn");
        await Actionability.CheckPointerEventsHandleAsync(h, x, y, 2000);
        var c = (await p.QuerySelectorAsync("#covered"))!;
        await c.ScrollIntoViewIfNeededAsync();
        var (cx, cy) = await Center(p, "#covered");
        await Assert.ThrowsAsync<ElementNotReceivingEventsError>(() =>
            Actionability.CheckPointerEventsHandleAsync(c, cx, cy, 300));
    }

    [BrowserFact]
    public async Task Isolated_world_is_still_usable_directly()
    {
        var p = await Open(false);
        var w = new IsolatedWorld(p);
        Assert.True(await w.EvaluateBoolAsync("document.querySelector('#btn') !== null"));
        var v = await w.EvaluateAsync("document.title.length >= 0");
        Assert.True(v!.Value.GetBoolean());
    }
}
