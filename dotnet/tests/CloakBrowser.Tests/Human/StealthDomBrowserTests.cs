using System.Reflection;
using CloakBrowser.Human;
using CloakBrowser.Wrappers;
using Microsoft.Playwright;
using Xunit;

namespace CloakBrowser.Tests.Human;

[Collection("env-serial")]
public class StealthDomBrowserTests
{
    private static bool BrowserAvailable =>
        !string.IsNullOrWhiteSpace(Environment.GetEnvironmentVariable("CLOAKBROWSER_BINARY_PATH"));

    private static LaunchOptions FastLaunchOptions() => new()
    {
        Headless = true,
        Humanize = true,
        BrowserVersion = Environment.GetEnvironmentVariable("CLOAKBROWSER_VERSION"),
        ReleaseChannel = "preview",
        HumanConfig = new Dictionary<string, object>
        {
            ["mouse_min_steps"] = 3,
            ["mouse_max_steps"] = 3,
            ["mouse_burst_pause"] = new[] { 0.0, 0.0 },
            ["idle_between_actions"] = false,
            ["scroll_settle_delay"] = new[] { 0.0, 0.0 },
        },
    };

    [Fact]
    public async Task Hidden_script_text_and_shadow_order_match_direct_locators()
    {
        if (!BrowserAvailable) return;

        await using var browser = await CloakLauncher.LaunchAsync(FastLaunchOptions());
        var page = await browser.NewPageAsync();
        await page.GotoAsync("https://example.com", new PageGotoOptions
        {
            WaitUntil = WaitUntilState.DOMContentLoaded,
        });
        await page.EvaluateAsync(@"() => {
            document.body.innerHTML = `
                <script type='application/json'>Hoy</script>
                <button data-id='light-1'>Hoy</button>
                <div id='host-a'></div>
                <button data-id='light-2'>two</button>
                <div id='host-b'></div>`;
            const a = document.querySelector('#host-a').attachShadow({mode: 'open'});
            a.innerHTML = `<button data-id='shadow-a'>three</button><div id='nested'></div>`;
            a.querySelector('#nested').attachShadow({mode: 'open'}).innerHTML =
                `<button data-id='shadow-nested'>four</button>`;
            document.querySelector('#host-b').attachShadow({mode: 'open'}).innerHTML =
                `<button data-id='shadow-b'>five</button>`;
            window.__textClicks = 0;
            window.__order = [];
            const roots = [document, a, a.querySelector('#nested').shadowRoot,
                document.querySelector('#host-b').shadowRoot];
            for (const root of roots) {
                for (const button of root.querySelectorAll('button')) {
                    button.addEventListener('click', () => {
                        window.__order.push(button.dataset.id);
                        if (button.dataset.id === 'light-1') window.__textClicks++;
                    });
                }
            }
        }");

        await page.Locator("text=Hoy").First.ClickAsync();
        Assert.Equal(1, await page.EvaluateAsync<int>("() => window.__textClicks"));

        await page.EvaluateAsync("() => { window.__order = []; }");
        string[] expected = { "light-1", "light-2", "shadow-a", "shadow-nested", "shadow-b" };
        for (int index = 0; index < expected.Length; index++)
            await page.Locator("button").Nth(index).ClickAsync();

        Assert.Equal(expected, await page.EvaluateAsync<string[]>("() => window.__order"));
    }

    [Fact]
    public async Task Display_contents_text_and_nested_geometry_are_clickable()
    {
        if (!BrowserAvailable) return;

        await using var browser = await CloakLauncher.LaunchAsync(FastLaunchOptions());
        var page = await browser.NewPageAsync();
        await page.GotoAsync("https://example.com", new PageGotoOptions
        {
            WaitUntil = WaitUntilState.DOMContentLoaded,
        });
        await page.EvaluateAsync(@"() => {
            document.body.innerHTML = `
                <ul><li id='target' style='display:contents'>Hoy</li></ul>
                <div id='nested' style='display:contents'><span>nested</span></div>`;
            window.__targetClicks = 0;
            window.__nestedClicks = 0;
            document.querySelector('#target').addEventListener('click', () => window.__targetClicks++);
            document.querySelector('#nested').addEventListener('click', () => window.__nestedClicks++);
        }");

        Assert.Equal(0, await page.EvaluateAsync<double>(
            "() => document.querySelector('#target').getBoundingClientRect().width"));
        await page.ClickAsync("text=Hoy", new PageClickOptions { Timeout = 3000 });
        await page.ClickAsync("#nested", new PageClickOptions { Timeout = 3000 });
        Assert.Equal(1, await page.EvaluateAsync<int>("() => window.__targetClicks"));
        Assert.Equal(1, await page.EvaluateAsync<int>("() => window.__nestedClicks"));
    }

    [Fact]
    public async Task Text_css_and_actionability_state_match_direct_selector_behavior()
    {
        if (!BrowserAvailable) return;

        await using var browser = await CloakLauncher.LaunchAsync(FastLaunchOptions());
        var page = await browser.NewPageAsync();
        await page.GotoAsync("https://example.com", new PageGotoOptions
        {
            WaitUntil = WaitUntilState.DOMContentLoaded,
        });
        await page.EvaluateAsync(@"() => {
            document.body.innerHTML = `
                <button id='regex-target'>Alpha42</button>
                <button id='nested-target'>Hello<span>World</span></button>
                <input id='value-target' type='button' value='Submit Me'>
                <button id='normalized-target'>foo\u200bbar</button>
                <article>Wanted<button id='structural-target'>Go</button></article>
                <article>Other<button id='wrong-target'>Wanted</button></article>
                <span class='anchor'>anchor</span><button id='adjacent-target'>adjacent</button>
                <fieldset disabled><input id='disabled-target'></fieldset>
                <div role='group' aria-disabled='true'><button id='aria-disabled'>disabled</button></div>
                <div id='readonly-target' role='textbox' contenteditable='true' aria-readonly='true'>edit</div>
                <input id='check-target' type='checkbox'>`;
            window.__clickedIds = [];
            for (const element of document.querySelectorAll('button,input[type=button]')) {
                element.addEventListener('click', () => window.__clickedIds.push(element.id));
            }
        }");

        // Exercise the source-compatible pointer overload against a real isolated
        // world; it must snapshot a target ID and delegate to exact validation.
        object unguardedPage = page is IGuardedProxy guarded ? guarded.GuardTarget : page;
        var humanizedPage = Assert.IsType<HumanizedPage>(unguardedPage);
        var cursor = Assert.IsType<HumanCursor>(typeof(HumanizedPage)
            .GetField("_cursor", BindingFlags.NonPublic | BindingFlags.Instance)!
            .GetValue(humanizedPage));
        var world = await cursor.GetStealthAsync();
        Assert.NotNull(world);
        var boxRead = await StealthDom.BoxAsync(world!, "#regex-target");
        Assert.Equal(StealthStatus.Ok, boxRead.Status);
        var probeBox = boxRead.Target!.Value.Box;
        await Actionability.CheckPointerEventsAsync(
            page, "#regex-target", probeBox.X + probeBox.Width / 2,
            probeBox.Y + probeBox.Height / 2, 3000, world);

        string[] selectors =
        {
            "text=/^Alpha\\d+$/",
            "text=\"Hello\"",
            "text=Submit Me",
            "text=foobar",
            "article:has-text(\"Wanted\") > button",
            ".anchor + button",
        };
        foreach (string selector in selectors)
            await page.Locator(selector).First.ClickAsync(new LocatorClickOptions { Timeout = 3000 });

        Assert.Equal(new[]
        {
            "regex-target", "nested-target", "value-target", "normalized-target",
            "structural-target", "adjacent-target",
        }, await page.EvaluateAsync<string[]>("() => window.__clickedIds"));

        await Assert.ThrowsAsync<ElementNotEnabledError>(() =>
            page.ClickAsync("#disabled-target", new PageClickOptions { Timeout = 300 }));
        await Assert.ThrowsAsync<ElementNotEnabledError>(() =>
            page.ClickAsync("#aria-disabled", new PageClickOptions { Timeout = 300 }));
        await Assert.ThrowsAsync<ElementNotEditableError>(() =>
            page.FillAsync("#readonly-target", "x", new PageFillOptions { Timeout = 300 }));
        await Assert.ThrowsAsync<UnsupportedHumanizeSelectorError>(() =>
            page.ClickAsync("internal:role=button", new PageClickOptions { Timeout = 300 }));

        await page.CheckAsync("#check-target", new PageCheckOptions { Timeout = 3000 });
        Assert.True(await page.Locator("#check-target").IsCheckedAsync());
        await page.UncheckAsync("#check-target", new PageUncheckOptions { Timeout = 3000 });
        Assert.False(await page.Locator("#check-target").IsCheckedAsync());
    }

    [Theory]
    [InlineData(false, "remove")]
    [InlineData(true, "remove")]
    [InlineData(false, "replace")]
    [InlineData(true, "replace")]
    public async Task Target_mutation_after_movement_never_clicks_underneath_or_replacement(
        bool force, string mutation)
    {
        if (!BrowserAvailable) return;

        await using var browser = await CloakLauncher.LaunchAsync(FastLaunchOptions());
        var page = await browser.NewPageAsync();
        await page.GotoAsync("https://example.com", new PageGotoOptions
        {
            WaitUntil = WaitUntilState.DOMContentLoaded,
        });
        await page.EvaluateAsync(@"(mutation) => {
            document.body.innerHTML = `
                <button id='underlying' style='position:absolute;left:180px;top:180px;width:180px;height:60px'>underlying</button>
                <button id='target' style='position:absolute;left:180px;top:180px;width:180px;height:60px'>target</button>`;
            window.__underlyingClicks = 0;
            window.__replacementClicks = 0;
            document.querySelector('#underlying').addEventListener('click', () => window.__underlyingClicks++);
            const original = document.querySelector('#target');
            original.addEventListener('mousemove', () => {
                if (mutation === 'remove') {
                    original.remove();
                    return;
                }
                const replacement = original.cloneNode(true);
                replacement.addEventListener('click', () => window.__replacementClicks++);
                original.replaceWith(replacement);
            }, {once: true});
        }", mutation);

        var error = await Record.ExceptionAsync(() => page.ClickAsync("#target", new PageClickOptions
        {
            Force = force,
            Timeout = 3000,
        }));
        Assert.NotNull(error);
        if (mutation == "remove") Assert.IsType<ElementNotAttachedError>(error);
        else Assert.IsType<ElementTargetChangedError>(error);

        var counts = await page.EvaluateAsync<ClickCounts>(@"() => ({
            underlying: window.__underlyingClicks,
            replacement: window.__replacementClicks,
        })");
        Assert.Equal(0, counts.Underlying);
        Assert.Equal(0, counts.Replacement);
    }

    [Fact]
    public async Task Frame_options_and_repeated_position_locators_stay_legacy_compatible()
    {
        if (!BrowserAvailable) return;

        await using var browser = await CloakLauncher.LaunchAsync(FastLaunchOptions());
        var page = await browser.NewPageAsync();
        await page.GotoAsync("https://example.com", new PageGotoOptions
        {
            WaitUntil = WaitUntilState.DOMContentLoaded,
        });
        await page.EvaluateAsync(@"() => {
            document.body.innerHTML = `
                <button id='same'>main</button>
                <button class='option'>A</button><button class='option'>B</button>
                <button class='nested'>first</button><button class='nested'>second</button>
                <iframe id='child' name='child'></iframe>`;
            window.__mainClicks = 0;
            window.__optionClicks = [];
            window.__nestedClicks = [];
            document.querySelector('#same').addEventListener('click', () => window.__mainClicks++);
            for (const button of document.querySelectorAll('.option'))
                button.addEventListener('click', () => window.__optionClicks.push(button.textContent));
            for (const button of document.querySelectorAll('.nested'))
                button.addEventListener('click', () => window.__nestedClicks.push(button.textContent));
            const doc = document.querySelector('#child').contentDocument;
            doc.open();
            doc.write(`<button id='same'>frame</button><script>
                window.__frameClicks = 0;
                document.querySelector('#same').addEventListener('click', () => window.__frameClicks++);
            <\/script>`);
            doc.close();
        }");

        var child = page.Frames.Single(frame => frame.Name == "child");
        await child.Locator("#same").ClickAsync(new LocatorClickOptions { Timeout = 3000 });
        Assert.Equal(1, await child.EvaluateAsync<int>("() => window.__frameClicks"));
        Assert.Equal(0, await page.EvaluateAsync<int>("() => window.__mainClicks"));

        await page.Locator("button.option", new PageLocatorOptions { HasTextString = "B" })
            .ClickAsync(new LocatorClickOptions { Timeout = 3000 });
        Assert.Equal(new[] { "B" }, await page.EvaluateAsync<string[]>("() => window.__optionClicks"));

        await page.Locator("button.nested").First.First
            .ClickAsync(new LocatorClickOptions { Timeout = 3000 });
        Assert.Equal(new[] { "first" }, await page.EvaluateAsync<string[]>("() => window.__nestedClicks"));
    }

    [Fact]
    public async Task Direct_locator_uses_canonical_scroll_and_rescroll_after_reflow()
    {
        if (!BrowserAvailable) return;

        await using var browser = await CloakLauncher.LaunchAsync(FastLaunchOptions());
        var page = await browser.NewPageAsync();
        await page.GotoAsync("https://example.com", new PageGotoOptions
        {
            WaitUntil = WaitUntilState.DOMContentLoaded,
        });
        await page.EvaluateAsync(@"() => {
            document.body.innerHTML = `<button id='below' style='position:absolute;top:2200px;left:100px'>below</button>`;
            document.body.style.minHeight = '5000px';
            window.__belowClicks = 0;
            window.__reflowed = false;
            const button = document.querySelector('#below');
            button.addEventListener('click', () => window.__belowClicks++);
            window.addEventListener('scroll', () => {
                if (window.__reflowed || window.scrollY < 100) return;
                window.__reflowed = true;
                button.style.top = '3200px';
            });
        }");

        await page.Locator("#below").ClickAsync(new LocatorClickOptions { Timeout = 10000 });
        Assert.True(await page.EvaluateAsync<bool>("() => window.__reflowed"));
        Assert.Equal(1, await page.EvaluateAsync<int>("() => window.__belowClicks"));
    }

    [Fact]
    public async Task Force_skips_coverage_rejection_but_preserves_target_identity()
    {
        if (!BrowserAvailable) return;

        await using var browser = await CloakLauncher.LaunchAsync(FastLaunchOptions());
        var page = await browser.NewPageAsync();
        await page.GotoAsync("https://example.com", new PageGotoOptions
        {
            WaitUntil = WaitUntilState.DOMContentLoaded,
        });
        await page.EvaluateAsync(@"() => {
            document.body.innerHTML = `
                <button id='target' style='position:absolute;left:180px;top:180px;width:180px;height:60px'>target</button>
                <div id='cover' style='position:absolute;left:180px;top:180px;width:180px;height:60px;z-index:2'></div>`;
            window.__targetClicks = 0;
            window.__coverClicks = 0;
            document.querySelector('#target').addEventListener('click', () => window.__targetClicks++);
            document.querySelector('#cover').addEventListener('click', () => window.__coverClicks++);
        }");

        await page.ClickAsync("#target", new PageClickOptions { Force = true, Timeout = 3000 });
        var counts = await page.EvaluateAsync<ClickCounts>(@"() => ({
            target: window.__targetClicks,
            cover: window.__coverClicks,
        })");
        Assert.Equal(0, counts.Target);
        Assert.Equal(1, counts.Cover);
    }

    private sealed class ClickCounts
    {
        public int Underlying { get; set; }
        public int Replacement { get; set; }
        public int Target { get; set; }
        public int Cover { get; set; }
    }
}
