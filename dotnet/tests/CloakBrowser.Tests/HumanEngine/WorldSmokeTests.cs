using CloakBrowser.Human;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests.HumanEngine;

/// <summary>The isolated world installs Playwright's InjectedScript and resolves
/// standard selectors with strict mode, without touching the page.</summary>
[Collection("RealBrowser")]
public class WorldSmokeTests
{
    [Fact]
    public void Injected_source_is_found_in_the_driver_package()
    {
        var lit = InjectedSource.FindLiteral();
        Assert.True(lit.Length > 10_000);
        Assert.Contains("InjectedScript", lit);
    }

    [BrowserFact]
    public async Task World_resolves_selectors_and_reports_strict_mode()
    {
        await using var handle = await CloakLauncher.LaunchAsync(new LaunchOptions { Headless = true });
        var page = await handle.RawBrowser.NewPageAsync();
        await page.EvaluateAsync(@"() => { document.body.innerHTML =
            '<div id=wrap><button id=b>Press me</button></div><i class=d>1</i><i class=d>2</i>';
            window.__calls = 0; const q = Document.prototype.querySelectorAll;
            Document.prototype.querySelectorAll = function (...a) { window.__calls++; return q.apply(this, a); }; }");
        var world = new HumanWorld(page);
        var r = (await world.CallAsync(page.MainFrame, "resolve", "internal:role=button[name=\"Press me\"i]", true, 0))!.Value;
        Assert.Equal("ok", r.GetProperty("status").GetString());
        var chain = (await world.CallAsync(page.MainFrame, "resolve", "#wrap >> #b", true, 0))!.Value;
        Assert.Equal("ok", chain.GetProperty("status").GetString());
        var strict = (await world.CallAsync(page.MainFrame, "resolve", ".d", true, 0))!.Value;
        Assert.Equal("strict", strict.GetProperty("status").GetString());
        Assert.StartsWith("strict mode violation", strict.GetProperty("message").GetString());
        Assert.Equal(0, await page.EvaluateAsync<int>("window.__calls"));
    }
}
