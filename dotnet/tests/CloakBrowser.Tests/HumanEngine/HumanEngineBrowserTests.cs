using System.Diagnostics;
using System.Text.Json;
using CloakBrowser.Human;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests.HumanEngine;

/// <summary>Real-browser launch + fixture site for the engine tests (runs whenever a
/// CloakBrowser binary is configured).</summary>
public sealed class EngineFixture : IAsyncLifetime
{
    public static bool Enabled => BrowserFactAttribute.Available;
    private readonly SiteServer _site = new();
    public string Url => _site.Url;
    public CloakBrowserHandle? Handle { get; private set; }

    public async Task InitializeAsync()
    {
        if (!Enabled) return;
        _site.Start();
        Handle = await CloakLauncher.LaunchAsync(new LaunchOptions { Headless = true, Humanize = true, HumanConfig = SiteServer.Fast });
    }

    public async Task DisposeAsync()
    {
        if (Handle != null) await Handle.DisposeAsync();
        _site.Stop();
    }
}

/// <summary>Port of <c>js/tests/humanizeEngine.test.ts</c> / <c>tests/test_humanize_engine.py</c>.</summary>
[Collection("RealBrowser")]
public class HumanEngineBrowserTests : IClassFixture<EngineFixture>, IAsyncLifetime
{
    private readonly EngineFixture _f;
    private readonly List<IPage> _pages = new();
    public HumanEngineBrowserTests(EngineFixture f) => _f = f;

    public Task InitializeAsync() => Task.CompletedTask;
    public async Task DisposeAsync()
    {
        foreach (var p in _pages) { try { await p.CloseAsync(); } catch { } }
    }

    private async Task<IPage> Open(string path = "index.html")
    {
        var p = await _f.Handle!.Browser.NewPageAsync();
        _pages.Add(p);
        await p.GotoAsync(_f.Url + path);
        return p;
    }

    private async Task<IPage> OpenWith(Dictionary<string, object> overrides)
    {
        var merged = new Dictionary<string, object>(SiteServer.Fast);
        foreach (var (k, v) in overrides) merged[k] = v;
        var ctx = CloakBrowser.Wrappers.Humanize.Context(await _f.Handle!.RawBrowser.NewContextAsync(),
            HumanConfigFactory.Resolve(HumanPreset.Default, merged));
        var p = await ctx.NewPageAsync();
        _pages.Add(p);
        await p.GotoAsync(_f.Url + "index.html");
        return p;
    }

    private static async Task<IFrame> FrameOf(IPage p)
    {
        var f = p.Frame("f")!;
        await f.WaitForLoadStateAsync();
        return f;
    }

    private static async Task<List<JsonElement>> Events(IFrame f, params string[] types)
    {
        var all = JsonSerializer.Deserialize<List<JsonElement>>(await f.EvaluateAsync<string>("JSON.stringify(window.__log)"))!;
        return types.Length == 0 ? all : all.Where(e => types.Contains(e.GetProperty("t").GetString())).ToList();
    }
    private static Task<List<JsonElement>> Events(IPage p, params string[] types) => Events(p.MainFrame, types);
    private static Task Reset(IFrame f) => f.EvaluateAsync("window.__reset(); window.__mainWorldHits.length = 0");
    private static Task Reset(IPage p) => Reset(p.MainFrame);
    private static Task<string> Value(IFrame f, string sel) => f.EvaluateAsync<string>("s => document.querySelector(s).value", sel);
    private static Task<string> Value(IPage p, string sel) => Value(p.MainFrame, sel);
    private static string Targets(IEnumerable<JsonElement> evs) => string.Join(",", evs.Select(e => e.GetProperty("target").GetString()));

    // --- wiring ------------------------------------------------------------

    [BrowserFact]
    public async Task Raw_page_in_the_same_process_is_untouched()
    {
        var p = await _f.Handle!.RawBrowser.NewPageAsync();
        _pages.Add(p);
        await p.GotoAsync(_f.Url + "index.html");
        await Reset(p);
        await p.ClickAsync("#btn");
        await p.FillAsync("#name", "plain");
        Assert.Equal("plain", await Value(p, "#name"));
        Assert.True((await Events(p, "mousemove")).Count < 3, "stock Playwright teleports the mouse");
    }

    [BrowserFact]
    public async Task Humanized_actions_leave_no_side_effects_in_the_page()
    {
        var p = await _f.Handle!.Browser.NewPageAsync();
        _pages.Add(p);
        await p.AddInitScriptAsync(@"(() => {
          const add = EventTarget.prototype.addEventListener;
          const d = window.__engine = { listeners: 0, mutations: 0 };
          EventTarget.prototype.addEventListener = function (t, f, o) {
            if (this === window || this === document) d.listeners++;
            return add.call(this, t, f, o);
          };
          new MutationObserver((m) => { d.mutations += m.length; })
            .observe(document, { subtree: true, childList: true, attributes: true });
        })()");
        await p.GotoAsync(_f.Url + "index.html?nolog");
        var handle = (await p.QuerySelectorAsync("#btn"))!;
        await p.EvaluateAsync("() => { const d = window.__engine; d.listeners = 0; d.mutations = 0; }");
        await p.GetByRole(AriaRole.Button, new() { Name = "Press me" }).ClickAsync();
        await p.Locator("#buttons >> #btn").HoverAsync();
        await handle.ClickAsync();
        await p.FrameLocator("#frame").Locator("#finput").ClickAsync();
        var strict = await Assert.ThrowsAnyAsync<Exception>(() => p.Locator(".dup").ClickAsync(new() { Timeout = 500 }));
        Assert.Contains("strict mode", strict.Message);
        var seen = await p.EvaluateAsync<string>("JSON.stringify(window.__engine)");
        Assert.Equal("{\"listeners\":0,\"mutations\":0}", seen);
    }

    // --- pointer -----------------------------------------------------------

    [BrowserFact]
    public async Task Click_moves_along_a_curve_then_presses()
    {
        var p = await Open();
        await Reset(p);
        await p.ClickAsync("#btn");
        Assert.True((await Events(p, "mousemove")).Count >= 3);
        Assert.Equal("btn", Targets(await Events(p, "click")));
    }

    [BrowserFact]
    public async Task Click_options_are_honoured()
    {
        var p = await Open();
        await Reset(p);
        await p.ClickAsync("#btn", new() { Button = MouseButton.Right, Modifiers = new[] { KeyboardModifier.Shift } });
        var down = (await Events(p, "mousedown")).Last();
        Assert.Equal(2, down.GetProperty("button").GetInt32());
        Assert.True(down.GetProperty("shift").GetBoolean());
        await Reset(p);
        await p.ClickAsync("#btn", new() { ClickCount = 2 });
        Assert.Single(await Events(p, "dblclick"));
        await Reset(p);
        await p.ClickAsync("#btn", new() { Trial = true });
        Assert.Empty(await Events(p, "click"));
    }

    [BrowserFact]
    public async Task Hover_does_not_press_and_dblclick_is_a_real_double_click()
    {
        var p = await Open();
        await Reset(p);
        await p.HoverAsync("#btn");
        Assert.Empty(await Events(p, "mousedown"));
        await Reset(p);
        await p.DblClickAsync("#btn");
        var seq = string.Join(" ", (await Events(p, "mousedown", "click", "dblclick"))
            .Select(e => $"{e.GetProperty("t").GetString()}:{e.GetProperty("detail").GetInt32()}"));
        Assert.Equal("mousedown:1 click:1 mousedown:2 click:2 dblclick:2", seq);
    }

    [BrowserFact]
    public async Task Hover_holds_modifiers_while_the_mouse_moves()
    {
        var p = await Open();
        await p.HoverAsync("#chk");
        await Reset(p);
        await p.HoverAsync("#btn", new() { Modifiers = new[] { KeyboardModifier.Shift } });
        var seq = await Events(p, "mousemove", "keydown", "keyup");
        var moves = seq.Where(e => e.GetProperty("t").GetString() == "mousemove").ToList();
        Assert.NotEmpty(moves);
        Assert.All(moves, e => Assert.True(e.GetProperty("shift").GetBoolean()));
        Assert.Equal("keydown", seq[0].GetProperty("t").GetString());
        Assert.Equal("keyup", seq[^1].GetProperty("t").GetString());
        Assert.Empty(await Events(p, "mousedown"));
    }

    [BrowserFact]
    public async Task Covered_element_times_out_with_the_reason()
    {
        var p = await Open();
        var err = await Assert.ThrowsAsync<TimeoutException>(() => p.ClickAsync("#covered", new() { Timeout = 1000 }));
        Assert.Contains("intercepts pointer events", err.Message);
    }

    [BrowserFact]
    public async Task Strict_mode_violation_and_first()
    {
        var p = await Open();
        var err = await Assert.ThrowsAnyAsync<PlaywrightException>(() => p.Locator(".dup").ClickAsync(new() { Timeout = 1000 }));
        Assert.Contains("strict mode violation", err.Message);
        await p.Locator(".dup").First.ClickAsync();
    }

    [BrowserFact]
    public async Task Page_default_timeout_and_timeout_zero()
    {
        var p = await Open();
        p.SetDefaultTimeout(500);
        var sw = Stopwatch.StartNew();
        await Assert.ThrowsAsync<TimeoutException>(() => p.ClickAsync("#missing"));
        Assert.True(sw.ElapsedMilliseconds < 1500, $"took {sw.ElapsedMilliseconds} ms");
        await p.ClickAsync("#btn", new() { Timeout = 0 });
    }

    [BrowserFact]
    public async Task Standard_locators()
    {
        var p = await Open();
        await p.GetByRole(AriaRole.Button, new() { Name = "Press me" }).ClickAsync();
        await p.Locator("#buttons").Locator("#btn").ClickAsync();
        await p.Locator("button").Filter(new() { HasText = "Press me" }).ClickAsync();
        await p.ClickAsync("#btn:visible");
    }

    // --- keyboard ----------------------------------------------------------

    [BrowserFact]
    public async Task Fill_replaces_press_sequentially_appends_clear_empties()
    {
        var p = await Open();
        await p.FillAsync("#name", "Shaho");
        Assert.Equal("Shaho", await Value(p, "#name"));
        await p.Locator("#name").PressSequentiallyAsync("!");
        Assert.Equal("Shaho!", await Value(p, "#name"));
        await p.Locator("#name").ClearAsync();
        Assert.Equal("", await Value(p, "#name"));
    }

    [BrowserFact]
    public async Task Value_inputs_are_operated_like_a_person()
    {
        var p = await Open();
        await p.EvaluateAsync(@"() => { window.__untrusted = 0;
            for (const t of ['input', 'change'])
              document.addEventListener(t, (e) => { if (!e.isTrusted) window.__untrusted++; }, true); }");
        await p.FillAsync("#date", "2024-01-31");
        await p.FillAsync("#date", "1999-12-05");
        await p.FillAsync("#range", "80");
        Assert.Equal(new[] { "b" }, await p.SelectOptionAsync("#sel", "b"));
        Assert.Equal("1999-12-05", await Value(p, "#date"));
        Assert.Equal("80", await Value(p, "#range"));
        Assert.Equal("b", await Value(p, "#sel"));
        Assert.Equal(0, await p.EvaluateAsync<int>("window.__untrusted"));
        Assert.Contains("native colour picker", (await Assert.ThrowsAnyAsync<PlaywrightException>(() => p.FillAsync("#color", "#ff0000"))).Message);
        Assert.Contains("cannot be filled", (await Assert.ThrowsAnyAsync<PlaywrightException>(() => p.FillAsync("#chk", "x"))).Message);
    }

    [BrowserFact]
    public async Task Unreachable_element_is_not_focused_programmatically()
    {
        var p = await Open();
        var err = await Assert.ThrowsAsync<TimeoutException>(() => p.FillAsync("#neg", "x", new() { Timeout = 1500 }));
        Assert.Contains("outside of the viewport", err.Message);
        Assert.Equal("", await Value(p, "#neg"));
    }

    [BrowserFact]
    public async Task Press_focuses_its_target_first_and_forwards_delay()
    {
        var p = await Open();
        await p.FocusAsync("#fa");
        await (await p.QuerySelectorAsync("#fb"))!.PressAsync("x");
        Assert.Equal("", await Value(p, "#fa"));
        Assert.Equal("x", await Value(p, "#fb"));
        await Reset(p);
        await p.PressAsync("#name", "a", new() { Delay = 150 });
        var ev = await Events(p, "keydown", "keyup");
        Assert.True(ev[^1].GetProperty("ts").GetDouble() - ev[^2].GetProperty("ts").GetDouble() >= 120);
    }

    [BrowserFact]
    public async Task Press_and_type_reach_non_focusable_targets()
    {
        var p = await Open();
        await p.EvaluateAsync("() => { window.__keys = []; document.addEventListener('keydown', e => window.__keys.push(e.key)); }");
        await p.PressAsync("#cv", "ArrowUp");
        await p.Locator("#cv").PressSequentiallyAsync("ab");
        Assert.Equal("[\"ArrowUp\",\"a\",\"b\"]", await p.EvaluateAsync<string>("JSON.stringify(window.__keys)"));
    }

    [BrowserFact]
    public async Task Mistypes_are_corrected_skip_masked_fields_and_use_shift()
    {
        var p = await OpenWith(new() { ["mistype_chance"] = 1.0 });
        await p.FillAsync("#name", "Hello");
        Assert.Equal("Hello", await Value(p, "#name"));
        await p.FillAsync("#hex", "ab");
        Assert.Equal("ab", await Value(p, "#hex"));
        await Reset(p);
        await p.Locator("#name").PressSequentiallyAsync("AB");
        var bad = (await Events(p, "keydown")).Where(e => e.GetProperty("key").GetString() is { Length: 1 } k
            && k[0] is >= 'A' and <= 'Z' && !e.GetProperty("shift").GetBoolean());
        Assert.Empty(bad);
    }

    [BrowserFact]
    public async Task Scroll_overshoot_wheels_past_the_target_and_back()
    {
        var p = await OpenWith(new() { ["scroll_overshoot_chance"] = 1.0, ["scroll_overshoot_px"] = new[] { 120.0, 120.0 } });
        await p.SetViewportSizeAsync(800, 300);
        await Reset(p);
        await p.ClickAsync("#chk");
        var dys = (await Events(p, "wheel")).Select(e => e.GetProperty("dy").GetDouble()).ToList();
        Assert.True(dys.Any(d => d > 0) && dys.Any(d => d < 0), string.Join(",", dys));
        Assert.Equal(new[] { "chk" }, (await Events(p, "click")).Select(e => e.GetProperty("target").GetString()));
    }

    [BrowserFact]
    public async Task Per_call_human_config_through_HumanPage()
    {
        var raw = await _f.Handle!.RawBrowser.NewPageAsync();
        _pages.Add(raw);
        await raw.GotoAsync(_f.Url + "index.html");
        var hp = await HumanPage.CreateAsync(raw, HumanConfigFactory.Resolve(HumanPreset.Default, SiteServer.Fast));
        await Reset(raw);
        await hp.ClickAsync("#btn", new() { HumanConfig = new Dictionary<string, object> { ["click_hold_button"] = new[] { 300.0, 300.0 } } });
        var up = (await Events(raw, "mouseup")).Last().GetProperty("ts").GetDouble();
        var down = (await Events(raw, "mousedown")).Last().GetProperty("ts").GetDouble();
        Assert.True(up - down >= 250, $"held {up - down} ms");
        await hp.FillAsync("#name", "explicit");
        Assert.Equal("explicit", await Value(raw, "#name"));
        Assert.True(raw is not CloakBrowser.Wrappers.HumanizedPage);
    }

    // --- checkable / select ------------------------------------------------

    [BrowserFact]
    public async Task Check_uncheck_set_checked_select_by_index()
    {
        var p = await Open();
        await p.CheckAsync("#chk");
        Assert.True(await p.IsCheckedAsync("#chk"));
        await p.Locator("#chk").UncheckAsync();
        Assert.False(await p.IsCheckedAsync("#chk"));
        await (await p.QuerySelectorAsync("#chk"))!.SetCheckedAsync(true);
        Assert.True(await p.IsCheckedAsync("#chk"));
        Assert.Equal(new[] { "b" }, await p.SelectOptionAsync("#sel", new SelectOptionValue { Index = 1 }));
    }

    // --- frames / handles --------------------------------------------------

    [BrowserFact]
    public async Task Frame_actions()
    {
        var p = await Open();
        var f = await FrameOf(p);
        await f.FillAsync("#finput", "in frame");
        Assert.Equal("in frame", await Value(f, "#finput"));
        await p.FrameLocator("#frame").Locator("#finput").PressSequentiallyAsync("!");
        Assert.Equal("in frame!", await Value(f, "#finput"));
        await Reset(f);
        await f.ClickAsync("#fbottom", new() { Timeout = 5000 });
        Assert.Equal("fbottom", Targets(await Events(f, "click")));
        var err = await Assert.ThrowsAsync<TimeoutException>(() => f.ClickAsync("#fcovered", new() { Timeout = 4000 }));
        Assert.Contains("intercepts pointer events", err.Message);
    }

    [BrowserFact]
    public async Task Element_handle_actions()
    {
        var p = await Open();
        await (await p.QuerySelectorAsync("#name"))!.FillAsync("handle");
        Assert.Equal("handle", await Value(p, "#name"));
        await Reset(p);
        await (await p.QuerySelectorAsync("#btn"))!.ClickAsync();
        Assert.Equal("btn", Targets(await Events(p, "click")));
    }

    [BrowserFact]
    public async Task Stale_handle_after_navigation_throws_instead_of_clicking_the_new_page()
    {
        var p = await Open();
        var h = (await p.QuerySelectorAsync("#btn"))!;
        await h.ClickAsync(); // caches the handle's element id (the first id of this world)
        await p.GotoAsync(_f.Url + "index.html?second");
        // Fill the new document's world so an element there gets the same id again.
        await p.ClickAsync("#chk");
        await Reset(p);
        var sw = System.Diagnostics.Stopwatch.StartNew();
        var e = await Assert.ThrowsAnyAsync<Exception>(() => h.ClickAsync(new() { Timeout = 10000 }));
        Assert.Contains("not attached", e.Message);
        Assert.True(sw.ElapsedMilliseconds < 5000, $"took {sw.ElapsedMilliseconds} ms: should fail fast, not wait for the timeout");
        Assert.Equal("", Targets(await Events(p, "click")));
    }

    [BrowserFact]
    public async Task Mouse_api()
    {
        var p = await Open();
        await Reset(p);
        await p.Mouse.MoveAsync(50, 50, new() { Steps = 1 });
        Assert.Single(await Events(p, "mousemove"));
        var box = (await p.Locator("#btn").BoundingBoxAsync())!;
        await Reset(p);
        await p.Mouse.ClickAsync(box.X + 5, box.Y + 5, new() { Button = MouseButton.Right });
        Assert.Equal(new[] { 2 }, (await Events(p, "mousedown")).Select(e => e.GetProperty("button").GetInt32()));
    }

    [BrowserFact]
    public async Task Select_all_follows_the_persona()
    {
        await using var mac = await CloakLauncher.LaunchAsync(new LaunchOptions
        {
            Headless = true, Humanize = true, HumanConfig = SiteServer.Fast,
            Args = new List<string> { "--fingerprint-platform=macos" },
        });
        var p = await mac.Browser.NewPageAsync();
        await p.GotoAsync(_f.Url + "index.html");
        Assert.Equal("MacIntel", await p.EvaluateAsync<string>("navigator.platform"));
        await p.FillAsync("#name", "old");
        await p.FillAsync("#name", "Mac");
        Assert.Equal("Mac", await Value(p, "#name"));
    }
}
