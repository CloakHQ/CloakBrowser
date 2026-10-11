using System.Text.Json;
using System.Text.RegularExpressions;
using CloakBrowser.Human;
using CloakBrowser.Wrappers;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests.HumanEngine;

/// <summary>
/// Element reads (InputValueAsync / TextContentAsync / InnerTextAsync / InnerHTMLAsync /
/// GetAttributeAsync) and DispatchEventAsync: resolved and executed in the humanize
/// isolated world, exactly like the actions. The probe (<c>window.__marks</c>) records
/// what the page observes, and the control test proves the probe works.
/// </summary>
[Collection("RealBrowser")]
public class HumanReadsTests : IClassFixture<EngineFixture>, IAsyncLifetime
{
    private readonly EngineFixture _f;
    private readonly List<IPage> _pages = new();

    public HumanReadsTests(EngineFixture f) => _f = f;

    public Task InitializeAsync() => Task.CompletedTask;

    public async Task DisposeAsync()
    {
        foreach (var p in _pages) { try { await p.CloseAsync(); } catch { } }
    }

    // -----------------------------------------------------------------------
    // Wiring
    // -----------------------------------------------------------------------

    /// <summary>Open a humanized page with the probe armed before the document loads.</summary>
    private async Task<IPage> OpenHumanized(string path = "index.html")
    {
        var p = await _f.Handle!.Browser.NewPageAsync();
        _pages.Add(p);
        await p.AddInitScriptAsync(ProbeScript());
        await p.GotoAsync(_f.Url + path);
        return p;
    }

    private static Task<int> Marks(IFrame f) => f.EvaluateAsync<int>("() => window.__marks.length");
    private static Task<int> Marks(IPage p) => Marks(p.MainFrame);

    /// <summary>Records the events the page observes (<c>window.__marks</c>). The names
    /// are read from the installed driver, so the probe never hard-codes them and
    /// cannot silently go stale when Playwright changes them.</summary>
    private static string ProbeScript()
    {
        var names = JsonSerializer.Serialize(TraceEventNames());
        return "(() => {\n"
             + "  window.__marks = window.__marks || [];\n"
             + $"  const names = {names};\n"
             + "  for (const n of names) document.addEventListener(n, () => window.__marks.push(n), true);\n"
             + "})()";
    }

    /// <summary>Event names from the installed driver's injected script.</summary>
    private static IReadOnlyList<string> TraceEventNames() =>
        Regex.Matches(InjectedSource.FindLiteral(), @"CustomEvent\(\s*\\?(?:""|')([^""\\']+)")
            .Select(m => m.Groups[1].Value)
            .Distinct()
            .OrderBy(n => n, StringComparer.Ordinal)
            .ToList();

    /// <summary>Guards the probe: without names to listen for, the control test below
    /// would be the only thing that notices.</summary>
    [Fact]
    public void The_probe_has_events_to_listen_for()
    {
        Assert.NotEmpty(TraceEventNames());
        Assert.Contains("window.__marks", ProbeScript());
    }

    // -----------------------------------------------------------------------
    // Reads
    // -----------------------------------------------------------------------

    [BrowserFact]
    public async Task Humanized_reads_return_the_values_and_the_probe_stays_empty()
    {
        var p = await OpenHumanized();
        var handle = await p.QuerySelectorAsync("#name");
        await p.FillAsync("#name", "laptop");
        var before = await Marks(p);

        Assert.Equal("laptop", await p.InputValueAsync("#name"));
        Assert.Equal("laptop", await p.Locator("#name").InputValueAsync());
        Assert.Equal("laptop", await handle!.InputValueAsync());
        Assert.Equal("Press me", await p.TextContentAsync("#btn"));
        Assert.Equal("Press me", await p.InnerTextAsync("#btn"));
        Assert.Equal("Press me", await p.InnerHTMLAsync("#btn"));
        Assert.Equal("btn", await p.GetAttributeAsync("#btn", "id"));
        Assert.Equal("Press me", await p.Locator("#btn").TextContentAsync());
        Assert.Equal("Press me", await p.Locator("#btn").InnerTextAsync());

        Assert.Equal(before, await Marks(p));
    }

    [BrowserFact]
    public async Task Humanized_read_waits_for_the_selector_to_match()
    {
        var p = await OpenHumanized();
        await p.EvaluateAsync(@"() => setTimeout(() => {
            const d = document.createElement('div');
            d.id = 'late'; d.textContent = 'ready';
            document.body.appendChild(d);
        }, 300)");

        Assert.Equal("ready", await p.InnerTextAsync("#late", new PageInnerTextOptions { Timeout = 10000 }));
    }

    [BrowserFact]
    public async Task Humanized_read_maps_world_errors_nulls_and_timeouts()
    {
        var p = await OpenHumanized();

        Assert.Null(await p.GetAttributeAsync("#btn", "data-missing"));

        var error = await Assert.ThrowsAsync<PlaywrightException>(() => p.InputValueAsync("#btn"));
        Assert.Contains("Page.InputValueAsync: Error: Node is not an <input>", error.Message);

        var timeout = await Assert.ThrowsAsync<TimeoutException>(
            () => p.Locator("#never-there").InputValueAsync(new LocatorInputValueOptions { Timeout = 300 }));
        Assert.Contains("Locator.InputValueAsync: Timeout", timeout.Message);
    }

    // -----------------------------------------------------------------------
    // Dispatch
    // -----------------------------------------------------------------------

    [BrowserFact]
    public async Task Humanized_dispatch_event_reaches_a_page_listener()
    {
        var p = await OpenHumanized();
        var handle = await p.QuerySelectorAsync("#btn");
        await p.EvaluateAsync(@"() => {
            window.__clicks = [];
            document.addEventListener('click', (e) => window.__clicks.push({
                mouse: e instanceof MouseEvent, bubbles: e.bubbles, x: e.clientX,
            }));
        }");
        var before = await Marks(p);

        await p.DispatchEventAsync("#btn", "click", new { clientX = 7, clientY = 9 });
        await p.Locator("#btn").DispatchEventAsync("click", new { clientX = 3, clientY = 4 });
        await handle!.DispatchEventAsync("click", new { clientX = 5, clientY = 6 });

        var clicks = JsonSerializer.Deserialize<List<JsonElement>>(
            await p.EvaluateAsync<string>("() => JSON.stringify(window.__clicks)"))!;
        Assert.Equal(3, clicks.Count);
        Assert.True(clicks[0].GetProperty("mouse").GetBoolean());
        Assert.True(clicks[0].GetProperty("bubbles").GetBoolean());
        Assert.Equal(7, clicks[0].GetProperty("x").GetInt32());
        Assert.Equal(3, clicks[1].GetProperty("x").GetInt32());
        Assert.Equal(5, clicks[2].GetProperty("x").GetInt32());

        Assert.Equal(before, await Marks(p));
    }

    // -----------------------------------------------------------------------
    // Frames
    // -----------------------------------------------------------------------

    [BrowserFact]
    public async Task Humanized_frame_reads_and_dispatch_run_in_the_frame()
    {
        var p = await OpenHumanized();
        var f = p.Frame("f")!;
        await f.WaitForLoadStateAsync();
        await f.EvaluateAsync(ProbeScript());
        await f.EvaluateAsync(@"() => {
            window.__clicks = [];
            document.addEventListener('click', (e) => window.__clicks.push(e.clientX), true);
        }");
        var before = await Marks(f);

        Assert.Equal("old", await f.InputValueAsync("#finput"));
        Assert.Equal("old", await p.FrameLocator("#frame").Locator("#finput").InputValueAsync());

        await f.DispatchEventAsync("#fcovered", "click", new { clientX = 11 });
        await p.FrameLocator("#frame").Locator("#fcovered").DispatchEventAsync("click", new { clientX = 12 });

        var clicks = JsonSerializer.Deserialize<List<JsonElement>>(
            await f.EvaluateAsync<string>("() => JSON.stringify(window.__clicks)"))!;
        Assert.Equal(new[] { 11, 12 }, clicks.Select(c => c.GetInt32()).ToArray());
        Assert.Equal(before, await Marks(f));
    }

    // -----------------------------------------------------------------------
    // Fallback to Playwright's own call
    // -----------------------------------------------------------------------

    [BrowserFact]
    public async Task Handle_reads_of_hidden_or_same_box_elements_use_the_raw_path_at_once()
    {
        var p = await OpenHumanized();
        await p.EvaluateAsync(@"() => {
            document.head.insertAdjacentHTML('beforeend', '<meta name=""csrf"" content=""tok123"">');
            document.body.insertAdjacentHTML('beforeend', '<input id=""hid"" type=""hidden"" value=""secret"">'
                + '<div id=""outer"" style=""width:90px;height:30px""><div id=""inner"" style=""width:90px;height:30px""></div></div>');
        }");
        var sw = System.Diagnostics.Stopwatch.StartNew();
        Assert.Equal("tok123", await (await p.QuerySelectorAsync("meta[name=csrf]"))!.GetAttributeAsync("content"));
        Assert.Equal("secret", await (await p.QuerySelectorAsync("#hid"))!.InputValueAsync());
        Assert.True(sw.ElapsedMilliseconds < 5000, $"hidden handle reads took {sw.ElapsedMilliseconds}ms");
        // A read must land on the handle's own element, not its same-box wrapper.
        Assert.Equal("inner", await (await p.QuerySelectorAsync("#inner"))!.GetAttributeAsync("id"));
        Assert.Equal("outer", await (await p.QuerySelectorAsync("#outer"))!.GetAttributeAsync("id"));
    }

    [BrowserFact]
    public async Task Dispatch_event_with_a_js_handle_in_event_init_uses_the_raw_path()
    {
        var p = await OpenHumanized();
        await p.EvaluateAsync(@"() => {
            window.__dt = [];
            document.addEventListener('dragstart', (e) => window.__dt.push(e.dataTransfer instanceof DataTransfer));
        }");
        var dt = await p.EvaluateHandleAsync("() => new DataTransfer()");

        await p.DispatchEventAsync("#btn", "dragstart", new { dataTransfer = dt });
        await p.Locator("#btn").DispatchEventAsync("dragstart", new Dictionary<string, object> { ["dataTransfer"] = dt });

        Assert.Equal("[true,true]", await p.EvaluateAsync<string>("() => JSON.stringify(window.__dt)"));
    }

    // -----------------------------------------------------------------------
    // Control: Playwright's own read path is caught by the probe
    // -----------------------------------------------------------------------

    [BrowserFact]
    public async Task The_probe_sees_the_raw_read_path()
    {
        var p = await OpenHumanized();
        var before = await Marks(p);

        // The raw, un-humanized page (escape hatch): Playwright's own read path.
        var raw = Humanize.Unwrap(p);
        Assert.Equal("firstname", await raw.InputValueAsync("#name"));

        Assert.True(await Marks(p) > before,
            "the raw read path is expected to be visible to the page probe");
    }
}
