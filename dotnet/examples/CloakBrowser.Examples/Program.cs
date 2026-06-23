using CloakBrowser;
using CloakBrowser.Human;
using Microsoft.Playwright;

// CloakBrowser .NET examples. Run a specific example by name:
//   dotnet run --project examples/CloakBrowser.Examples -- basic
//   dotnet run --project examples/CloakBrowser.Examples -- humanize
//   dotnet run --project examples/CloakBrowser.Examples -- context
//   dotnet run --project examples/CloakBrowser.Examples -- persistent
//   dotnet run --project examples/CloakBrowser.Examples -- proxy-geoip
//   dotnet run --project examples/CloakBrowser.Examples -- visual

string which = args.Length > 0 ? args[0] : "basic";

switch (which)
{
    case "basic": await Basic(); break;
    case "humanize": await Humanize(); break;
    case "context": await Context(); break;
    case "persistent": await Persistent(); break;
    case "proxy-geoip": await ProxyGeoip(); break;
    case "bottest": await BotTest(); break;
    case "behavioral": await Behavioral(); break;
    case "visual": await Visual(); break;
    case "proxytest": await ProxyTest(); break;
    case "persisttest": await PersistTest(); break;
    case "webrtctest": await WebRtcTest(); break;
    case "trusted": await TrustedTest(); break;
    case "timeout": await TimeoutTest(); break;
    default:
        Console.Error.WriteLine($"Unknown example: {which}");
        Console.Error.WriteLine("Available: basic, humanize, context, persistent, proxy-geoip, bottest, behavioral, visual");
        Environment.Exit(2);
        break;
}

// ---------------------------------------------------------------------------
// Basic launch - open a page and print the title.
// ---------------------------------------------------------------------------
static async Task Basic()
{
    await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
    {
        Headless = true,
    });
    var page = await browser.NewPageAsync();
    await page.GotoAsync("https://bot.incolumitas.com/");
    Console.WriteLine($"Title: {await page.TitleAsync()}");
}

// ---------------------------------------------------------------------------
// Humanized interaction - Bezier mouse, human typing, scroll, actionability.
// ---------------------------------------------------------------------------
static async Task Humanize()
{
    await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
    {
        Headless = false,
        Humanize = true,
        HumanPreset = HumanPreset.Careful,
        HumanConfig = new Dictionary<string, object>
        {
            ["typing_delay"] = 90.0,
            ["mouse_overshoot_chance"] = 0.2,
        },
    });

    // NewHumanPageAsync returns a HumanPage wrapper with the configured behavior.
    HumanPage human = await browser.NewHumanPageAsync();
    await human.GotoAsync("https://example.com/");

    // Humanized actions go through actionability checks + Bezier movement.
    await human.ClickAsync("a");
    // await human.FillAsync("#search", "hello world");
    // await human.PressAsync("#search", "Enter");

    Console.WriteLine($"Title: {await human.Page.TitleAsync()}");
}

// ---------------------------------------------------------------------------
// Context with viewport, user agent, locale, timezone.
// ---------------------------------------------------------------------------
static async Task Context()
{
    await using var ctx = await CloakLauncher.LaunchContextAsync(new LaunchContextOptions
    {
        Headless = true,
        Locale = "en-US",
        Timezone = "America/New_York",
        Viewport = (1280, 800),
        ColorScheme = "dark",
    });
    var page = await ctx.NewPageAsync();
    await page.GotoAsync("https://example.com/");
    Console.WriteLine($"Title: {await page.TitleAsync()}");
}

// ---------------------------------------------------------------------------
// Persistent profile - cookies/localStorage survive across runs.
// ---------------------------------------------------------------------------
static async Task Persistent()
{
    await using var ctx = await CloakLauncher.LaunchPersistentContextAsync(
        "./cloak-profile",
        new LaunchContextOptions { Headless = true });
    var page = await ctx.NewPageAsync();
    await page.GotoAsync("https://example.com/");
    Console.WriteLine($"Title: {await page.TitleAsync()} (profile saved to ./cloak-profile)");
}

// ---------------------------------------------------------------------------
// Proxy + GeoIP - timezone/locale auto-detected, WebRTC IP spoofed to exit IP.
// ---------------------------------------------------------------------------
static async Task ProxyGeoip()
{
    await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
    {
        Headless = true,
        Proxy = "http://user:pass@proxy.example.com:8080",
        GeoIp = true, // resolves timezone/locale + WebRTC exit IP from the proxy
        Args = new List<string> { "--fingerprint-webrtc-ip=auto" },
    });
    var page = await browser.NewPageAsync();
    await page.GotoAsync("https://ipinfo.io/json");
    Console.WriteLine(await page.InnerTextAsync("body"));
}

static async Task BotTest()
{
    await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
    {
        Headless = false,        // detectors often flag headless
        Humanize = true,         // transparent decorator - the KEY feature
    });

    var page = await browser.NewPageAsync();   // should return a wrapped IPage

    // verify runtime types: is the wrapper actually in place?
    Console.WriteLine($"Page type:     {page.GetType().Name}");
    Console.WriteLine($"Mouse type:    {page.Mouse.GetType().Name}");
    Console.WriteLine($"Keyboard type: {page.Keyboard.GetType().Name}");

    await page.GotoAsync("https://deviceandbrowserinfo.com/are_you_a_bot");
    await page.WaitForTimeoutAsync(2000);

    // real humanized actions
    await page.Mouse.MoveAsync(300, 300);
    await page.Mouse.WheelAsync(0, 500);
    await page.WaitForTimeoutAsync(1500);

    await page.ScreenshotAsync(new() { Path = "bot-result.png", FullPage = true });
    Console.WriteLine("Saved bot-result.png");
    await page.WaitForTimeoutAsync(4000);  // leave time to inspect it visually
}

static async Task Behavioral()
{
    await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
    {
        Headless = false,
        Humanize = true,
    });
    var page = await browser.NewPageAsync();

    await page.GotoAsync("https://deviceandbrowserinfo.com/are_you_a_bot_interactions",
        new() { WaitUntil = WaitUntilState.DOMContentLoaded });
    await page.WaitForTimeoutAsync(3000);

    var t0 = DateTime.UtcNow;

    await page.Locator("#email").ClickAsync();
    await page.WaitForTimeoutAsync(300);
    await page.Locator("#email").FillAsync("test@example.com");
    await page.WaitForTimeoutAsync(500);

    await page.Locator("#password").ClickAsync();
    await page.WaitForTimeoutAsync(300);
    await page.Locator("#password").FillAsync("SecurePass!123");
    await page.WaitForTimeoutAsync(500);

    await page.Locator("#loginForm button[type=\"submit\"]").ClickAsync();

    var elapsedMs = (DateTime.UtcNow - t0).TotalMilliseconds;
    await page.WaitForTimeoutAsync(5000);

    var body = await page.Locator("body").TextContentAsync() ?? "";

    bool superHuman   = body.Contains("\"superHumanSpeed\": true");
    bool suspicious   = body.Contains("\"suspiciousClientSideBehavior\": true");

    Console.WriteLine($"--- BEHAVIORAL RESULT ---");
    Console.WriteLine($"Form fill elapsed: {elapsedMs:F0} ms (Python requires > 3000)");
    Console.WriteLine($"superHumanSpeed:            {superHuman}   (expected False)");
    Console.WriteLine($"suspiciousClientSideBehavior: {suspicious}   (expected False)");
    Console.WriteLine(superHuman || suspicious || elapsedMs < 3000
        ? ">>> FAIL - the port behaves non-humanly"
        : ">>> PASS - humanization works just like Python");

    await page.ScreenshotAsync(new() { Path = "behavioral-result.png", FullPage = true });
    Console.WriteLine("Screenshot: behavioral-result.png");
}

static async Task Visual()
{
    const string cursorJs = @"
    () => {
        if (document.getElementById('__hc')) return;
        const el = document.createElement('div');
        el.id = '__hc';
        el.style.cssText = 'width:14px;height:14px;background:red;border:2px solid darkred;border-radius:50%;position:fixed;z-index:2147483647;pointer-events:none;display:none;transition:background 0.05s;';
        document.body.appendChild(el);
        const trail = document.createElement('div');
        trail.id = '__hcTrail';
        trail.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:2147483646;pointer-events:none;overflow:hidden;';
        document.body.appendChild(trail);
        let dotCount = 0; const maxDots = 500;
        function updatePos(x, y) {
            el.style.display = 'block';
            el.style.left = (x - 9) + 'px'; el.style.top = (y - 9) + 'px';
            if (dotCount < maxDots) {
                const dot = document.createElement('div');
                dot.style.cssText = 'width:3px;height:3px;background:rgba(255,0,0,0.3);border-radius:50%;position:fixed;pointer-events:none;left:'+(x-1)+'px;top:'+(y-1)+'px;';
                trail.appendChild(dot); dotCount++;
            }
        }
        document.addEventListener('mousemove', e => updatePos(e.clientX, e.clientY));
        document.addEventListener('drag', e => { if (e.clientX > 0) updatePos(e.clientX, e.clientY); });
        document.addEventListener('dragover', e => { if (e.clientX > 0) updatePos(e.clientX, e.clientY); });
        document.addEventListener('mousedown', () => { el.style.background = 'yellow'; });
        document.addEventListener('mouseup', () => { el.style.background = 'red'; });
        document.addEventListener('dragend', () => { el.style.background = 'red'; });
    }";

    var results = new List<(string Name, bool Passed, string Detail)>();
    void Check(string name, bool ok, string detail = "")
    {
        results.Add((name, ok, detail));
        Console.WriteLine($"  [{(ok ? "PASS" : "FAIL")}] {name}{(detail != "" ? " - " + detail : "")}");
    }

    await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
    {
        Headless = false,
        Humanize = true,
    });
    var page = await browser.NewPageAsync();

    async Task Inject()
    {
        try { await page.EvaluateAsync(cursorJs); } catch { }
        await page.WaitForTimeoutAsync(300);
    }

    static long Ms(DateTime t0) => (long)(DateTime.UtcNow - t0).TotalMilliseconds;

    Console.WriteLine(new string('=', 70));
    Console.WriteLine("  HUMAN-LIKE BEHAVIOR VISUAL TEST");
    Console.WriteLine("  Red dot = cursor, yellow = button held, trail = path");
    Console.WriteLine(new string('=', 70));

    // SCENARIO 1: Wikipedia search
    Console.WriteLine("\n=== Wikipedia - navigation and search ===");
    await page.GotoAsync("https://www.wikipedia.org");
    await page.WaitForTimeoutAsync(2000); await Inject(); await page.WaitForTimeoutAsync(1000);

    var t = DateTime.UtcNow;
    await page.Locator("#searchInput").ClickAsync();
    Check("click search input", Ms(t) > 200, $"{Ms(t)} ms");
    await page.WaitForTimeoutAsync(500);

    t = DateTime.UtcNow;
    await page.Locator("#searchInput").FillAsync("Python programming language");
    var v = await page.Locator("#searchInput").InputValueAsync();
    Check("fill search box", v == "Python programming language" && Ms(t) > 2000, $"{Ms(t)} ms, '{v}'");
    await page.WaitForTimeoutAsync(500);

    t = DateTime.UtcNow;
    await page.Locator("#searchInput").DblClickAsync();
    var sel = (await page.EvaluateAsync<string>("() => window.getSelection().toString().trim()")) ?? "";
    Check("dblclick selects word", sel.Length > 0 && Ms(t) > 200, $"{Ms(t)} ms, '{sel}'");
    await page.WaitForTimeoutAsync(500);

    t = DateTime.UtcNow;
    await page.Locator("#searchInput").FillAsync("Artificial intelligence");
    var v2 = await page.Locator("#searchInput").InputValueAsync();
    Check("fill replaces text", v2 == "Artificial intelligence" && Ms(t) > 1500, $"{Ms(t)} ms, '{v2}'");
    await page.WaitForTimeoutAsync(500);

    t = DateTime.UtcNow;
    await page.Locator("button[type=\"submit\"]").HoverAsync();
    Check("hover submit", Ms(t) > 100, $"{Ms(t)} ms");
    await page.WaitForTimeoutAsync(1000);

    // SCENARIO 2: Checkboxes
    Console.WriteLine("\n=== Checkboxes - check/uncheck ===");
    await page.GotoAsync("https://the-internet.herokuapp.com/checkboxes");
    await page.WaitForTimeoutAsync(2000); await Inject(); await page.WaitForTimeoutAsync(1000);

    var cb1 = page.Locator("input[type=\"checkbox\"]").Nth(0);
    var cb2 = page.Locator("input[type=\"checkbox\"]").Nth(1);
    if (await cb1.IsCheckedAsync()) { await cb1.UncheckAsync(); await page.WaitForTimeoutAsync(500); }
    t = DateTime.UtcNow;
    await cb1.CheckAsync();
    Check("check checkbox 1", await cb1.IsCheckedAsync() && Ms(t) > 200, $"{Ms(t)} ms");
    await page.WaitForTimeoutAsync(500);
    if (!await cb2.IsCheckedAsync()) { await cb2.CheckAsync(); await page.WaitForTimeoutAsync(500); }
    t = DateTime.UtcNow;
    await cb2.UncheckAsync();
    Check("uncheck checkbox 2", !await cb2.IsCheckedAsync() && Ms(t) > 200, $"{Ms(t)} ms");
    await page.WaitForTimeoutAsync(1000);

    // SCENARIO 3: Dropdown
    Console.WriteLine("\n=== Dropdown - select ===");
    await page.GotoAsync("https://the-internet.herokuapp.com/dropdown");
    await page.WaitForTimeoutAsync(2000); await Inject(); await page.WaitForTimeoutAsync(1000);
    t = DateTime.UtcNow;
    await page.Locator("#dropdown").SelectOptionAsync("1");
    Check("select option 1", await page.Locator("#dropdown").InputValueAsync() == "1" && Ms(t) > 100, $"{Ms(t)} ms");
    await page.WaitForTimeoutAsync(500);
    t = DateTime.UtcNow;
    await page.Locator("#dropdown").SelectOptionAsync("2");
    Check("select option 2", await page.Locator("#dropdown").InputValueAsync() == "2" && Ms(t) > 100, $"{Ms(t)} ms");
    await page.WaitForTimeoutAsync(1000);

    // SCENARIO 4: Drag and drop
    Console.WriteLine("\n=== Drag and Drop - A -> B ===");
    await page.GotoAsync("https://the-internet.herokuapp.com/drag_and_drop");
    await page.WaitForTimeoutAsync(2000); await Inject(); await page.WaitForTimeoutAsync(1000);
    var beforeA = (await page.Locator("#column-a header").TextContentAsync())?.Trim();
    t = DateTime.UtcNow;
    await page.Locator("#column-a").DragToAsync(page.Locator("#column-b"));
    await page.WaitForTimeoutAsync(1000);
    var afterA = (await page.Locator("#column-a header").TextContentAsync())?.Trim();
    Check("drag A to B", beforeA != afterA && Ms(t) > 300, $"{Ms(t)} ms, swapped={beforeA != afterA}");
    await page.WaitForTimeoutAsync(1000);

    // SCENARIO 5: Text editing
    Console.WriteLine("\n=== Text editing - type/press/clear/sequential ===");
    await page.GotoAsync("https://www.wikipedia.org");
    await page.WaitForTimeoutAsync(2000); await Inject(); await page.WaitForTimeoutAsync(1000);
    t = DateTime.UtcNow;
    await page.Locator("#searchInput").PressSequentiallyAsync("Hello World");
    var hv = await page.Locator("#searchInput").InputValueAsync();
    Check("type 'Hello World'", hv == "Hello World" && Ms(t) > 1000, $"{Ms(t)} ms, '{hv}'");
    await page.WaitForTimeoutAsync(500);
    t = DateTime.UtcNow;
    await page.Locator("#searchInput").PressAsync("End");
    await page.Locator("#searchInput").PressAsync("!");
    var pv = await page.Locator("#searchInput").InputValueAsync();
    Check("press '!' at end", (pv ?? "").Contains("!") && Ms(t) > 100, $"{Ms(t)} ms, '{pv}'");
    await page.WaitForTimeoutAsync(500);
    t = DateTime.UtcNow;
    await page.Locator("#searchInput").ClearAsync();
    var cv = await page.Locator("#searchInput").InputValueAsync();
    Check("clear field", cv == "" && Ms(t) > 100, $"{Ms(t)} ms");
    await page.WaitForTimeoutAsync(500);
    t = DateTime.UtcNow;
    await page.Locator("#searchInput").PressSequentiallyAsync("Sequential");
    var sv = await page.Locator("#searchInput").InputValueAsync();
    Check("press_sequentially", sv == "Sequential" && Ms(t) > 500, $"{Ms(t)} ms, '{sv}'");
    await page.WaitForTimeoutAsync(1000);

    // SCENARIO 6: Mouse precision + raw keyboard
    Console.WriteLine("\n=== Mouse precision + keyboard ===");
    t = DateTime.UtcNow;
    await page.Mouse.MoveAsync(600, 400);
    Check("mouse.move (600,400)", Ms(t) > 100, $"{Ms(t)} ms");
    await page.WaitForTimeoutAsync(500);
    t = DateTime.UtcNow;
    await page.Mouse.ClickAsync(200, 200);
    Check("mouse.click (200,200)", Ms(t) > 100, $"{Ms(t)} ms");
    await page.WaitForTimeoutAsync(500);
    await page.Locator("#searchInput").ClickAsync();
    await page.WaitForTimeoutAsync(300);
    t = DateTime.UtcNow;
    await page.Keyboard.TypeAsync("Direct keyboard");
    Check("keyboard.type", Ms(t) > 500, $"{Ms(t)} ms");
    await page.WaitForTimeoutAsync(1000);

    // SUMMARY
    Console.WriteLine("\n" + new string('=', 70));
    int passed = results.Count(r => r.Passed);
    foreach (var r in results)
        Console.WriteLine($"  [{(r.Passed ? "OK" : "XX")}] {r.Name}");
    Console.WriteLine($"\n  {passed}/{results.Count} passed, {results.Count - passed} failed");
    if (passed == results.Count) Console.WriteLine("  *** ALL VISUAL TESTS PASSED ***");
    Console.WriteLine(new string('=', 70));

    Console.WriteLine("\nPress Enter to close the browser...");
    Console.ReadLine();
}
static async Task ProxyTest()
{
    var proxy = Environment.GetEnvironmentVariable("CLOAK_TEST_PROXY_SOCKS5");
    if (string.IsNullOrEmpty(proxy))
    {
        Console.WriteLine("Set CLOAK_TEST_PROXY_SOCKS5=socks5://user:pass@host:port to run this example");
        return;
    }


    Console.WriteLine($"Testing proxy: {proxy}");
    await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
    {
        Headless = true,
        Proxy = proxy,
        GeoIp = true,                                  // timezone/locale + WebRTC from the exit IP
        Args = new List<string> { "--fingerprint-webrtc-ip=auto" },
    });
    var page = await browser.NewPageAsync();

    // 1. is the traffic actually going through the proxy
    await page.GotoAsync("https://ipinfo.io/json");
    var body = await page.InnerTextAsync("body");
    Console.WriteLine(body);

    // 2. which timezone/locale actually got applied in the browser
    var tz = await page.EvaluateAsync<string>(
        "() => Intl.DateTimeFormat().resolvedOptions().timeZone");
    var locale = await page.EvaluateAsync<string>("() => navigator.language");
    Console.WriteLine($"\nBrowser timezone: {tz}");
    Console.WriteLine($"Browser locale:   {locale}");
}
static async Task PersistTest()
{
    const string profile = "./cloak-persist-test";
    const string url = "https://example.com/";

    Console.WriteLine("=== Run 1: write data into the profile ===");
    await using (var ctx = await CloakLauncher.LaunchPersistentContextAsync(
        profile, new LaunchContextOptions { Headless = true }))
    {
        var page = await ctx.NewPageAsync();
        await page.GotoAsync(url);
        await page.EvaluateAsync(@"() => {
            localStorage.setItem('cloakTest', 'survived-42');
            document.cookie = 'cloak_cookie=persist-ok; path=/; max-age=86400';
        }");
        Console.WriteLine("Wrote: localStorage cloakTest=survived-42, cookie cloak_cookie=persist-ok");
    }

    Console.WriteLine("\n=== Run 2: read back from the same profile ===");
    await using (var ctx = await CloakLauncher.LaunchPersistentContextAsync(
        profile, new LaunchContextOptions { Headless = true }))
    {
        var page = await ctx.NewPageAsync();
        await page.GotoAsync(url);
        var ls = await page.EvaluateAsync<string?>("() => localStorage.getItem('cloakTest')");
        var ck = await page.EvaluateAsync<string?>(
            "() => (document.cookie.match(/cloak_cookie=([^;]+)/) || [null,null])[1]");

        Console.WriteLine($"localStorage cloakTest: {ls ?? "(null)"}   (expected 'survived-42')");
        Console.WriteLine($"cookie cloak_cookie:    {ck ?? "(null)"}   (expected 'persist-ok')");
        Console.WriteLine(ls == "survived-42" && ck == "persist-ok"
            ? ">>> PASS - the profile survives a restart"
            : ">>> FAIL - data was not persisted");
    }
}

static async Task WebRtcTest()
{
    var proxy = Environment.GetEnvironmentVariable("CLOAK_TEST_PROXY");
    if (string.IsNullOrEmpty(proxy))
    {
        Console.WriteLine("Set CLOAK_TEST_PROXY=http://user:pass@host:port to run this example");
        return;
    }

    await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
    {
        Headless = true,
        Proxy = proxy,
        GeoIp = true,
        Args = new List<string> { "--fingerprint-webrtc-ip=auto" },
    });
    var page = await browser.NewPageAsync();

    await page.GotoAsync("https://browserleaks.com/webrtc");
    await page.WaitForTimeoutAsync(6000);   // give WebRTC time to run

    var text = await page.InnerTextAsync("body");
    Console.WriteLine("--- browserleaks WebRTC (looking for IPs) ---");
    // pull out lines that look like an IP
    foreach (var line in text.Split('\n'))
        if (System.Text.RegularExpressions.Regex.IsMatch(line, @"\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}"))
            Console.WriteLine("  " + line.Trim());

    await page.ScreenshotAsync(new() { Path = "webrtc-result.png", FullPage = true });
    Console.WriteLine("\nScreenshot: webrtc-result.png");
}
static async Task TrustedTest()
{
    await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
    {
        Headless = false, Humanize = true,
    });
    var page = await browser.NewPageAsync();
    await page.GotoAsync("https://www.wikipedia.org");
    await page.WaitForTimeoutAsync(1500);

    // detector: catch untrusted keydown + querySelector from the evaluate context
    await page.EvaluateAsync(@"() => {
        window.__untrusted = [];
        window.__evalLeaks = [];
        const input = document.querySelector('#searchInput');
        input.addEventListener('keydown', e => {
            if (!e.isTrusted) window.__untrusted.push(e.key);
        }, true);
        const origQS = document.querySelector.bind(document);
        document.querySelector = function(sel){
            try { throw new Error(); } catch(e){
                if (e.stack && /:\d+:\d+/.test(e.stack) && e.stack.includes('eval')) {
                    window.__evalLeaks.push(sel);
                }
            }
            return origQS(sel);
        };
    }");

    await page.Locator("#searchInput").ClickAsync();
    await page.WaitForTimeoutAsync(300);
    await page.Keyboard.TypeAsync("Hello!@#$%^&*()");
    await page.WaitForTimeoutAsync(800);

    var untrusted = await page.EvaluateAsync<string[]>("() => window.__untrusted");
    var leaks = await page.EvaluateAsync<string[]>("() => window.__evalLeaks");

    Console.WriteLine($"Untrusted keydown events: {untrusted.Length}  -> {string.Join(",", untrusted)}");
    Console.WriteLine($"evaluate querySelector leaks: {leaks.Length}");
    Console.WriteLine(untrusted.Length == 0
        ? ">>> PASS - all shift symbols are isTrusted=true, no evaluate leaks"
        : ">>> FAIL - untrusted events found (a detector would catch them)");
}
static async Task TimeoutTest()
{
    const double timeoutMs = 2000;
    const double budgetMultiplier = 1.8; // matches Python TestTimeoutBudget307

    await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
    {
        Headless = true,
        Humanize = true,
    });
    var page = await browser.NewPageAsync();
    await page.GotoAsync("https://example.com/");

    Console.WriteLine($"Clicking a non-existent selector with timeout={timeoutMs}ms...");

    var sw = System.Diagnostics.Stopwatch.StartNew();
    try
    {
        await page.ClickAsync("#this-element-does-not-exist",
            new() { Timeout = (float)timeoutMs });
    }
    catch (Exception ex)
    {
        Console.WriteLine($"Expected exception: {ex.GetType().Name}");
    }
    sw.Stop();

    double elapsed = sw.Elapsed.TotalMilliseconds;
    double limit = timeoutMs * budgetMultiplier;

    Console.WriteLine("--- TIMEOUT BUDGET (issue #307) ---");
    Console.WriteLine($"Elapsed:      {elapsed:F0} ms");
    Console.WriteLine($"Limit (1.8x): {limit:F0} ms");
    Console.WriteLine(elapsed < limit
        ? ">>> PASS - timeout budget is shared, not multiplied"
        : ">>> FAIL - timeout multiplied (each step took the full budget)");
}
