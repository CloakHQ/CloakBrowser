# CloakBrowser for .NET

A complete, faithful **.NET 8 / C#** port of the
[CloakBrowser](https://github.com/CloakHQ/CloakBrowser) Python wrapper - stealth
Chromium that passes bot-detection tests, built on top of
[`Microsoft.Playwright`](https://playwright.dev/dotnet/).

CloakBrowser is a thin wrapper around a closed-source, source-level patched
Chromium binary (71 C++ fingerprint patches). This port reproduces **all** of the
wrapper functionality with identical behavior - same launch flags, same proxy /
GeoIP / WebRTC logic, and a humanize layer whose curves, timings, and stealth
paths match the Python and JavaScript clients exactly.

---

## Table of contents

- [Why a decorator layer?](#why-a-decorator-layer)
- [Feature matrix](#feature-matrix)
- [Requirements](#requirements)
- [Installation](#installation)
- [Project layout](#project-layout)
- [Quick start](#quick-start)
- [Humanized interactions (transparent)](#humanized-interactions-transparent)
  - [What changes vs. plain Playwright](#what-changes-vs-plain-playwright)
  - [Explicit `HumanPage` engine (advanced)](#explicit-humanpage-engine-advanced)
- [Launch API reference](#launch-api-reference)
- [Options reference](#options-reference)
- [`HumanConfig` reference](#humanconfig-reference)
- [How the humanize layer works](#how-the-humanize-layer-works)
  - [Mouse motion (Bezier)](#mouse-motion-bezier)
  - [Human typing & the CDP stealth path](#human-typing--the-cdp-stealth-path)
  - [Non-ASCII input](#non-ascii-input)
  - [Scrolling](#scrolling)
  - [Actionability, errors and timeouts](#actionability-errors-and-timeouts)
  - [Fields: focus, caret, value inputs](#fields-focus-caret-value-inputs)
- [Proxy, GeoIP & WebRTC](#proxy-geoip--webrtc)
- [CLI](#cli)
- [Environment variables](#environment-variables)
- [Building & testing](#building--testing)
- [Test suite map](#test-suite-map)
- [Mapping to the Python source](#mapping-to-the-python-source)
- [License](#license)

---

## Why a decorator layer?

.NET's Playwright exposes **sealed interfaces** (`IPage`, `ILocator`, `IMouse`, ...)
that **cannot** be monkey-patched the way the Python/JS clients replace methods at
runtime. CloakBrowser bridges this gap with a **transparent decorator layer**:

1. You pass `Humanize = true` at launch.
2. `NewPageAsync()` / `NewContextAsync()` return a **wrapped** object.
3. Every standard Playwright call (`page.ClickAsync`, `page.FillAsync`,
   `page.Mouse.MoveAsync`, ...) is automatically humanized - **no API changes** in
   your code.
4. The wrappers are generated at **compile time** by a Roslyn source generator
   (`[GenerateInterfaceDelegation]`), so they are fully statically typed with **no
   reflection on the hot path**. Non-intercepted members are delegated verbatim.

```
your code ──> HumanizedPage ──┬─ intercepted member ─> humanize engine ─> raw IPage
   (IPage)   (generated)      └─ everything else ─────────────────────> raw IPage (verbatim)
```

---

## Feature matrix

| Capability | Status | Source |
| --- | :---: | --- |
| Automatic binary **download / cache / auto-update** (SHA-256 verified) | ✅ | `Download.cs`, `Config.cs` |
| **Stealth launch args** (random fingerprint seed, platform spoofing) | ✅ | `CloakLauncher.cs` |
| **Proxy** - HTTP/HTTPS + SOCKS5, inline URL-encoded credentials | ✅ | `ProxyResolver.cs` |
| **GeoIP** timezone/locale from proxy exit IP (MaxMind GeoLite2) | ✅ | `GeoIp.cs` |
| **WebRTC** IP spoofing (`--fingerprint-webrtc-ip=auto`) | ✅ | `CloakLauncher.cs` |
| **Widevine** CDM hint seeding (Linux) | ✅ | `Widevine.cs` |
| **Persistent contexts** (profile reuse) | ✅ | `CloakLauncher.cs` |
| **Humanize** - Bezier mouse, human typing, scrolling, actionability | ✅ | `Human/`, `Wrappers/` |
| Transparent humanize via **source generator** | ✅ | `CloakBrowser.Generators/` |
| **CLI** (`login` / `logout` / `install` / `info` / `update` / `clear-cache`) | ✅ | `CloakBrowser.Cli/` |

---

## Requirements

| Dependency | Version | Why |
| --- | --- | --- |
| .NET SDK | **8.0** | target framework `net8.0` |
| `Microsoft.Playwright` | **1.49.0** | underlying browser automation |
| `MaxMind.GeoIP2` | **5.2.0** | GeoIP timezone/locale resolution |

---

## Installation

```bash
dotnet add package CloakBrowser
```

The patched Chromium binary downloads automatically on first launch, cached under
`~/.cloakbrowser` (override with `CLOAKBROWSER_CACHE_DIR`).

---

## Project layout

```
dotnet/
├── CloakBrowser.sln
├── src/
│   ├── CloakBrowser/                    # the library
│   │   ├── Config.cs                    # <- cloakbrowser/config.py
│   │   ├── Download.cs                  # <- cloakbrowser/download.py (+ zip-slip guard)
│   │   ├── GeoIp.cs                     # <- cloakbrowser/geoip.py
│   │   ├── Widevine.cs                  # <- cloakbrowser/widevine.py
│   │   ├── CloakLauncher.cs             # <- cloakbrowser/browser.py (launch funcs, build_args)
│   │   ├── ProxyResolver.cs             # <- cloakbrowser/browser.py (proxy URL helpers)
│   │   ├── ProxySettings.cs             # <- ProxySettings TypedDict
│   │   ├── LaunchOptions.cs             # launch option records
│   │   ├── Handles.cs                   # CloakBrowserHandle / CloakContextHandle
│   │   ├── CloakLog.cs                  # logging facade
│   │   ├── Human/                       # <- cloakbrowser/human/*
│   │   │   ├── HumanConfig.cs           #   <- human/config.py  (HumanConfig + merge)
│   │   │   ├── HumanRandom.cs           #   <- human/config.py  (rand/sleep helpers)
│   │   │   ├── HumanMouse.cs            #   <- human/mouse.py    (Bezier engine)
│   │   │   ├── HumanKeyboard.cs         #   <- human/keyboard.py (key tables, typo neighbours)
│   │   │   ├── HumanEngine.cs           #   <- human/engine.py  (resolve, wait, scroll, move, hit-test)
│   │   │   ├── HumanEngine.Actions.cs   #   <- human/engine.py  (click/fill/type/check/select/drag/...)
│   │   │   ├── HumanWorld.cs            #   <- human/world.py   (per-frame execution contexts)
│   │   │   ├── WorldHelpers.cs          #   <- human/world.py   (shared helper library)
│   │   │   ├── InjectedSource.cs        #   <- human/injected.py (selector engine loader)
│   │   │   ├── Fields.cs                #   <- human/fields.py  (fill classification, date parts)
│   │   │   ├── Actionability.cs         #   error classes + standalone checks (public, on the engine)
│   │   │   ├── HumanScroll.cs           #   standalone wheel scroll helper (public, kept for compatibility)
│   │   │   ├── IsolatedWorld.cs         #   single-world CDP evaluator (public, kept for compatibility)
│   │   │   └── HumanPage.cs             #   explicit API over the engine
│   │   └── Wrappers/                    # transparent humanize decorators (Humanize=true)
│   │       ├── Humanize.cs              #   wrap entry points + helpers (idempotent)
│   │       ├── HumanCursor.cs           #   per-page engine host (cursor, worlds)
│   │       ├── HumanizedFrameLocator.cs #   IFrameLocator   decorator
│   │       ├── HumanizedBrowser.cs      #   IBrowser        decorator
│   │       ├── HumanizedBrowserContext.cs # IBrowserContext decorator
│   │       ├── HumanizedPage.cs         #   IPage           decorator
│   │       ├── HumanizedFrame.cs        #   IFrame          decorator
│   │       ├── HumanizedLocator.cs      #   ILocator        decorator
│   │       ├── HumanizedElementHandle.cs # IElementHandle   decorator
│   │       ├── HumanizedMouse.cs        #   IMouse          decorator
│   │       └── HumanizedKeyboard.cs     #   IKeyboard       decorator
│   ├── CloakBrowser.Generators/         # Roslyn source generator
│   │   └── InterfaceDelegationGenerator.cs # emits delegating members
│   └── CloakBrowser.Cli/                # <- cloakbrowser/__main__.py
├── examples/CloakBrowser.Examples/      # runnable examples (see below)
└── tests/CloakBrowser.Tests/            # xUnit tests
```

---

## Quick start

```csharp
using CloakBrowser;

await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
{
    Headless = true,
});

var page = await browser.NewPageAsync();
await page.GotoAsync("https://bot.incolumitas.com/");
Console.WriteLine(await page.TitleAsync());
```

---

## Humanized interactions (transparent)

Pass `Humanize = true` and **write ordinary Playwright code** - mouse moves,
clicks, typing, and scrolling are humanized automatically. Nothing else in your
code changes:

```csharp
using CloakBrowser;
using CloakBrowser.Human;

await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
{
    Headless    = false,
    Humanize    = true,                       // <- the only change
    HumanPreset = HumanPreset.Careful,        // optional: Default | Careful
    HumanConfig = new Dictionary<string, object> { ["typing_delay"] = 90.0 }, // optional overrides
});

var page = await browser.NewPageAsync();      // returns a transparently-wrapped IPage
await page.GotoAsync("https://example.com/login");

await page.FillAsync("#username", "alice");   // per-character human typing
await page.FillAsync("#password", "s3cr3t!"); // (variable delays, thinking pauses, typos+fixes)
await page.ClickAsync("button[type=submit]"); // Bezier mouse curve to a realistic aim point
await page.ClickAsync("#footer-link");         // wheel-scrolls it into view first, like a person
```

The wrapping is **complete and transitive** - anything you reach through the page
is wrapped too:

```csharp
await page.Mouse.MoveAsync(400, 300);                 // humanized
await page.Keyboard.TypeAsync("hello");               // humanized
var btn = page.Locator("#submit");                    // wrapped ILocator
await btn.ClickAsync();                               // humanized
foreach (var frame in page.Frames) { /* wrapped IFrame */ }
```

### What changes vs. plain Playwright

| Member | `Humanize = false` (default) | `Humanize = true` |
| --- | --- | --- |
| `ClickAsync`, `DblClickAsync`, `HoverAsync`, `TapAsync` on `IPage` / `IFrame` / `ILocator` / `IElementHandle` | direct Playwright dispatch | wheel-scroll into view, Bezier move to an in-element aim point, hit-test, press; `Button`, `ClickCount`, `Modifiers`, `Position`, `Delay`, `Trial`, `Force` honoured |
| `FillAsync`, `TypeAsync` / `PressSequentiallyAsync`, `ClearAsync` | instant value set / fast type | click into the field, select-all (persona-aware), per-character typing with variable delays, pauses and self-corrected typos; text continues at the end |
| `FillAsync` on date/time/range, `SelectOptionAsync` | programmatic value | operated like a person with trusted events (segments typed, slider clicked + arrow keys, dropdown opened + arrows + Enter); `type=color` throws |
| `PressAsync` | direct | clicks to focus first if needed, human key timing, `Delay` honoured |
| `CheckAsync`, `UncheckAsync`, `SetCheckedAsync`, `DragToAsync` / `DragAndDropAsync`, `FocusAsync`, `ScrollIntoViewIfNeededAsync` | direct | humanized click / curved drag / wheel scroll |
| `IMouse` `MoveAsync`, `ClickAsync`, `DblClickAsync` | direct | curved, eased motion (`Steps` = exact raw steps), real `detail=1,2` sequence |
| `IMouse` `DownAsync`, `UpAsync`, `WheelAsync`; `IKeyboard` `DownAsync`, `UpAsync`, `PressAsync`, `InsertTextAsync` | direct | passed through 1:1 (they already are single human inputs) |
| `IKeyboard` `TypeAsync` | fast type | human typing into the focused element |
| `page.Mouse`, `page.Keyboard`, `Locator(...)`, `GetBy*`, `FrameLocator(...)`, `ContentFrame`, `Frames`, `QuerySelector(All)Async`, `WaitForSelectorAsync`, `ElementHandle(s)Async`, `IBrowser.NewPageAsync/NewContextAsync` | raw Playwright objects | the same call returns a **wrapped** object so humanization stays transitive |
| every **other** member (navigation, waits, evaluation, screenshots, network, etc.) | - | **delegated verbatim** to Playwright (identical signatures, return types, exceptions, and `CancellationToken` support) |
| escape hatch | n/a | `Humanize.Unwrap(page)` / `((HumanizedPage)page).Original` returns the raw object; `browser.RawBrowser` on the handle |

Every locator shape works: CSS, `text=`, `xpath=`, `GetByRole`, `GetBy*`, `>>`
chains, `Filter(...)`, `:visible`, `Nth`, `FrameLocator(...)`. Locators are
**strict** like Playwright: an ambiguous `Locator(".dup").ClickAsync()` throws
`strict mode violation` (use `.First` / `.Nth()`). Element handles are humanized
too; prefer `ILocator` (Playwright's recommendation): a handle is matched by its exact
bounding box, and an action raises when two elements share that box.

### Calling the original Playwright methods (escape hatch)

When you want a specific call to skip humanization (for raw speed, or to bypass a
behavior you don't want for one action) every wrapper exposes the underlying,
un-humanized Playwright object via **`Original`** (with **`Inner`** as an alias).
This is the .NET equivalent of the `page._original` escape hatch in the Python/JS
clients - the object you get back is the genuine Playwright interface, so the
whole API is available on it:

```csharp
await using var browser = await CloakLauncher.LaunchAsync(new() { Humanize = true });
var page = await browser.NewPageAsync();

// Humanized (default): Bezier mouse curve, realistic aim point, etc.
await page.ClickAsync("#submit");

// Raw Playwright, no humanization - instant, via the escape hatch:
await ((HumanizedPage)page).Original.ClickAsync("#submit");
await ((HumanizedPage)page).Original.FillAsync("#token", value);

// Works on every wrapped object:
await ((HumanizedMouse)page.Mouse).Original.MoveAsync(10, 10);
var rawLocator = ((HumanizedLocator)page.Locator("#row")).Original;
```

The handle also exposes the un-wrapped browser/context directly:
`browser.RawBrowser` (and `RawContext` on a context handle).

> Note: when `Humanize = false`, `NewPageAsync()` already returns the raw
> Playwright `IPage`, so no escape hatch is needed.

### Explicit `HumanPage` engine (advanced)

If you want the explicit, non-transparent engine object instead of the
transparent layer, `NewHumanPageAsync` returns a `HumanPage`. Its raw Playwright
page is always available via `human.Page`.

```csharp
HumanPage human = await browser.NewHumanPageAsync();
await human.GotoAsync("https://example.com/login");
await human.FillAsync("#username", "alice");
await human.ClickAsync("button[type=submit]");
```

`HumanPage` runs on the same engine as the transparent layer (selectors resolve
in the main frame, non-strict like `page.ClickAsync`). All methods take an optional
`HumanActionOptions { Timeout, Force, Delay, HumanConfig }` (`Timeout = 0` = no limit):

| Method | Description |
| --- | --- |
| `GotoAsync(url, options?)` | navigate (delegates to the raw page) |
| `ClickAsync(selector)` | Bezier move + human click |
| `DblClickAsync(selector)` | move + double click |
| `HoverAsync(selector)` | curved move, no click |
| `TapAsync(selector)` | same motion as click |
| `TypeAsync(selector, text)` | focus + per-character typing at the end of the text |
| `FillAsync(selector, value)` | click + select-all + clear + type (value inputs like a person) |
| `PressAsync(selector, key)` | focus-aware single key press |
| `PressSequentiallyAsync(selector, text)` | same as `TypeAsync` |
| `ClearAsync(selector)` | focus + select-all + Backspace |
| `CheckAsync` / `UncheckAsync` / `SetCheckedAsync(selector, state)` | humanized toggle via click |
| `SelectOptionAsync(selector, values)` | dropdown: click + arrow keys + Enter; list box: option clicks |
| `FocusAsync(selector)` | curved move + focus without a click (like Playwright's `FocusAsync`) |
| `ScrollIntoViewIfNeededAsync(selector)` | wheel scroll; returns true when the element moved |
| `DragAndDropAsync(src, dst)` | curved press-drag-release |
| `MouseMoveAsync(x, y)` / `MouseClickAsync(x, y)` | low-level curved motion |
| `KeyboardTypeAsync(text)` | low-level human typing at the focused element |

---

## Launch API reference

All entry points live on the static `CloakLauncher` class and return an
`await using`-friendly handle.

| Method | Returns | Notes |
| --- | --- | --- |
| `LaunchAsync(LaunchOptions)` | `CloakBrowserHandle` | launches a browser; `NewPageAsync`, `NewContextAsync`, `NewHumanPageAsync`, `RawBrowser` |
| `LaunchContextAsync(LaunchContextOptions)` | `CloakContextHandle` | browser-owned context with emulation |
| `LaunchPersistentContextAsync(userDataDir, LaunchContextOptions)` | `CloakContextHandle` | reuse a profile directory (cookies/localStorage persist) |

```csharp
// emulated context
await using var ctx = await CloakLauncher.LaunchContextAsync(new LaunchContextOptions
{
    Locale      = "en-US",
    Timezone    = "America/New_York",
    Viewport    = (1280, 800),
    ColorScheme = "dark",
});
var page = await ctx.NewPageAsync();
```

> Locale and timezone are applied via **binary flags** (`--lang`,
> `--fingerprint-locale`, `--fingerprint-timezone`) - *not* detectable CDP
> emulation - matching the Python wrapper.

```csharp
// persistent profile - cookies / localStorage survive across runs, so the
// browser looks like a returning user instead of a fresh incognito session
await using var ctx = await CloakLauncher.LaunchPersistentContextAsync("./profile",
    new LaunchContextOptions { Headless = false });
var page = await ctx.NewPageAsync();
```

---

## Options reference

`LaunchOptions` / `LaunchContextOptions` (commonly used fields):

| Option | Type | Default | Purpose |
| --- | --- | --- | --- |
| `Headless` | `bool` | `true` | run headless (detectors often flag this) |
| `Humanize` | `bool` | `false` | enable the transparent humanize layer |
| `HumanPreset` | `HumanPreset` | `Default` | `Default` or `Careful` (slower, more cautious) |
| `HumanConfig` | `Dictionary<string,object>` | `null` | per-field overrides (snake_case **or** PascalCase keys) |
| `Proxy` | `string` / `ProxySettings` | `null` | HTTP/HTTPS or SOCKS5 proxy |
| `GeoIp` | `bool` | `false` | resolve timezone/locale from the proxy exit IP |
| `Args` | `List<string>` | `[]` | extra Chromium flags (e.g. `--fingerprint-webrtc-ip=auto`) |
| `Locale` | `string` | `null` | BCP 47 locale -> `--lang`, `--fingerprint-locale` |
| `Timezone` | `string` | `null` | IANA timezone -> `--fingerprint-timezone` |
| `Viewport` | `(int,int)` | - | window size |
| `NoViewport` | `bool` | `false` | disable viewport emulation (track the real window) |
| `ColorScheme` | `string` | - | `light` / `dark` |
| `LicenseKey` | `string` | `null` | CloakBrowser Pro key (or `CLOAKBROWSER_LICENSE_KEY` env / `~/.cloakbrowser/license.key`) |
| `BrowserVersion` | `string` | `null` | Pin an exact Chromium version (e.g. `"154.0.8037.57.1"`). Also reads from `CLOAKBROWSER_VERSION` env var. Works with Free and Pro. |
| `ReleaseChannel` | `string` | `null` (`stable`) | Set to `"preview"` to opt into the Pro Preview binary channel. Also reads from `CLOAKBROWSER_RELEASE_CHANNEL`. |

### CloakBrowser Pro

The wrappers are MIT, free forever. The latest binary is **free to try**:

- **Free, latest build (Chromium 154)** — the newest binary. Free with a GitHub sign-in, one concurrent session. Run `cloakbrowser login` or [grab your key](https://cloakbrowser.dev/free).
- **Pro** — scale to **5, 20, 200, 2,000, or more concurrent sessions**, always first on the newest patches, with hands-on support. Linux, Windows, macOS. **[See plans and pricing →](https://cloakbrowser.dev)**
- **v146** — the older build stays free on [GitHub Releases](https://github.com/CloakHQ/cloakbrowser/releases). A quick first look, but it ages fast as detection evolves.

Try the latest free → **[cloakbrowser.dev/free](https://cloakbrowser.dev/free)**  ·  Scale up on Pro → **[cloakbrowser.dev](https://cloakbrowser.dev)**

Get a key: run `cloakbrowser login` (GitHub sign-in for a free key, or paste a paid key), or set it directly via the `LicenseKey` option, the `CLOAKBROWSER_LICENSE_KEY` env var, or `~/.cloakbrowser/license.key`:

```csharp
await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
{
    LicenseKey = "cb_xxxxxxxx",   // or via CLOAKBROWSER_LICENSE_KEY / ~/.cloakbrowser/license.key
});
```

A valid key downloads the latest Pro binary from cloakbrowser.dev; without one, the
free binary downloads from GitHub Releases. Validation is cached locally for 24h, and
the Pro binary is authenticated with the **same pinned Ed25519 signature** as the free
binary — a key whose Pro download or signature check fails surfaces a clear error
rather than silently downgrading. `Download.BinaryInfo()` exposes a `Tier` field
(`"pro"` / `"free"`); `License.ValidateLicense` / `License.LicenseInfo` mirror the
Python `validate_license` / `LicenseInfo` exports.

### Preview release channel

Stable is the default. Opt into Preview per launch:

```csharp
await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
{
    LicenseKey = "cb_xxxxxxxx",
    ReleaseChannel = "preview",
});
```

Or set `CLOAKBROWSER_RELEASE_CHANNEL=preview` for all launches and CLI commands. Preview selects the newest build available for this platform: a newer Preview when present, otherwise Stable. The `info` command reports the resolved channel and exact version. An exact `BrowserVersion` pin overrides the channel.

### Rolling back to a previous binary version

Pin an exact Chromium version without downgrading the wrapper — works for Free and Pro:

```csharp
// Free — pin a public release
await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
{
    BrowserVersion = "146.0.7680.177.5",
});

// Pro — pin a specific Pro version
await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
{
    LicenseKey = "cb_xxxxxxxx",
    BrowserVersion = "154.0.8037.57.1",
});
```

The pin is **never sticky** — unpinned launches always use the latest available version.
You can also set it globally via the `CLOAKBROWSER_VERSION` env var (see [Environment variables](#environment-variables)).

---

## `HumanConfig` reference

Every behavior is tunable. Names match the Python `HumanConfig` dataclass; the
override dictionary accepts both `snake_case` (Python parity) and `PascalCase`
keys. Ranges are `(min, max)` and may be passed as a `(double,double)` tuple or a
2-element array.

| Group | Field (PascalCase) | Default | Meaning |
| --- | --- | --- | --- |
| Keyboard | `TypingDelay` | `70` | base inter-key delay (ms) |
| | `TypingDelaySpread` | `40` | ± jitter around `TypingDelay` |
| | `TypingPauseChance` | `0.1` | chance of a longer "thinking" pause |
| | `TypingPauseRange` | `(400, 1000)` | thinking-pause duration (ms) |
| | `ShiftDownDelay` / `ShiftUpDelay` | `(30,70)` / `(20,50)` | shift key timing |
| | `KeyHold` | `(15, 35)` | key-down hold time (ms) |
| Mistype | `MistypeChance` | `0.02` | chance of a fat-finger typo (ASCII alnum only) |
| | `MistypeDelayNotice` | `(100, 300)` | pause before noticing the typo |
| | `MistypeDelayCorrect` | `(50, 150)` | pause after correcting |
| | `FieldSwitchDelay` | `(800, 1500)` | delay when moving between fields |
| Mouse - move | `MouseStepsDivisor` | `8` | distance ÷ divisor = step count |
| | `MouseMinSteps` / `MouseMaxSteps` | `25` / `80` | clamp on step count |
| | `MouseWobbleMax` | `1.5` | perpendicular wobble amplitude (px) |
| | `MouseOvershootChance` | `0.15` | chance of overshoot + correction |
| | `MouseOvershootPx` | `(3, 6)` | overshoot distance |
| | `MouseBurstSize` / `MouseBurstPause` | `(3,5)` / `(8,18)` | move-burst grouping + pause |
| Mouse - click | `ClickAimDelayInput` / `...Button` | `(60,140)` / `(80,200)` | aim delay before pressing |
| | `ClickHoldInput` / `...Button` | `(40,100)` / `(60,150)` | mouse-down hold time |
| | `ClickInputXRange` | `(0.05, 0.30)` | left-biased X target inside inputs |
| Mouse - idle | `IdleDriftPx` | `3` | idle drift amplitude |
| | `IdlePauseRange` | `(300, 1000)` | idle pause between drifts |
| Scroll | `ScrollDeltaBase` | `(80, 130)` | wheel delta per microstep |
| | `ScrollOvershootChance` | `0.1` | chance to overshoot then settle |
| | `ScrollSettleDelay` | `(300, 600)` | pause after reaching the target |
| | `ScrollTargetZone` | `(0.20, 0.80)` | viewport band the element lands in |
| Cursor | `InitialCursorX` / `...Y` | `(400,700)` / `(45,60)` | starting cursor position (address-bar area) |
| Idle between actions | `IdleBetweenActions` | `false` | opt-in micro-movements between actions (adds latency) |

Resolve / merge helpers:

```csharp
// preset + overrides
var cfg = HumanConfigFactory.Resolve(
    HumanPreset.Careful,
    new Dictionary<string, object> { ["typing_delay"] = 120.0, ["key_hold"] = (40.0, 90.0) });

// merge onto an existing config (never mutates the base; returns a new instance)
var faster = cfg.With(new Dictionary<string, object> { ["TypingDelay"] = 30.0 });
```

`With(...)` is **forgiving**: unknown keys are ignored silently, `null`/empty
overrides return a clone, and non-overridden fields are preserved.

---

## How the humanize layer works

### Mouse motion (Bezier)

`HumanMouse.HumanMoveAsync` traces a **cubic Bezier curve** between the current
cursor position and a randomized aim point inside the target's bounding box:

1. Step count scales with distance (`dist / MouseStepsDivisor`, clamped to
   `[MouseMinSteps, MouseMaxSteps]`).
2. Two control points are biased **perpendicular** to the straight path, so the
   curve is never a straight line.
3. Each step adds **sinusoidal wobble** (max amplitude `MouseWobbleMax`).
4. Motion is **eased** (cubic ease-in-out) and grouped into bursts with short
   pauses (`MouseBurstSize` / `MouseBurstPause`).
5. With probability `MouseOvershootChance`, the cursor overshoots the target and
   corrects back - exactly like a real hand.

Click points are computed by `HumanMouse.ClickTarget`: inputs get a left-biased X
and wide Y band; buttons get a centered cluster.

### Human typing & the CDP stealth path

Typing goes one character at a time with variable delays and occasional
"thinking" pauses. ASCII letters/digits can trigger a **fat-finger typo** (a nearby
QWERTY key, a digit for digits) that is noticed and corrected with Backspace;
uppercase letters and typos are typed with Shift. Typos are skipped in
number/email/password/tel/url fields, and a typo the page rejected (input masks)
is not "corrected" by deleting a real character.

Shift symbols (`@ # ! $ ...`) are dispatched through CDP `Input.dispatchKeyEvent`,
producing `isTrusted = true` events with no script on the page.

### Non-ASCII input

Cyrillic, CJK, emoji and other non-ASCII characters cannot be produced with
physical key codes, so they are inserted via **`InsertText`**, one character at a
time, while ASCII characters keep going through `Down`/`Up` key presses. For a
mixed string like `"Hi Мир"`:

| Char | Path |
| --- | --- |
| `H`, `i`, space | `DownAsync` / `UpAsync` (with Shift for `H`) |
| `М`, `и`, `р` | `InsertTextAsync` (per character) |

### Scrolling

Targets are brought on screen with **mouse-wheel bursts** (accelerate -> cruise ->
decelerate, optional overshoot), scrolling the page, scrollable containers and
iframes (also below an iframe's own fold), and settling the element in a natural
band (`ScrollTargetZone`). The cursor first moves into the area being scrolled.

### Actionability, errors and timeouts

Like Playwright, an action waits until its element is attached, visible,
enabled, editable (for input) and stable, then checks that the aim point really
hits it, through every ancestor `<iframe>`. Retries back off 0/20/100/100/500 ms.
There are **no silent fallbacks** to Playwright's own actions:
failures throw `PlaywrightException`, and timeouts throw `System.TimeoutException`
with a call log, e.g. `<div id="over"> intercepts pointer events` or
`element is outside of the viewport`.

All steps of one action share **one deadline** (#307). The timeout is the
option's `Timeout`, else the page/context default (`SetDefaultTimeout`), else
30 s; `Timeout = 0` means no limit. A target removed or replaced while the cursor
travels is never pressed (locators re-resolve).

The checks are also callable on their own, with the pre-engine signatures:
`Actionability.EnsureActionableAsync(page, selector, Actionability.ChecksClick)`,
`EnsureStableAsync`, `CheckPointerEventsAsync(page, selector, x, y)` and the
`…HandleAsync` variants. They run on the same engine (any Playwright selector) and
throw the typed `ElementNotVisibleError`,
`ElementNotEnabledError`, `ElementNotEditableError`, `ElementNotAttachedError`,
`ElementNotStableError` and `ElementNotReceivingEventsError`. `HumanScroll`
(`HumanScrollIntoViewAsync`, `SmoothWheelAsync`) and `IsolatedWorld` stay public as
standalone helpers; humanized actions do not use them.

### Fields: focus, caret, value inputs

There is **no programmatic focus**: a field is focused by scrolling to it and
clicking; one that can never be brought on screen fails with
`element is outside of the viewport`. `TypeAsync` / `PressSequentiallyAsync`
continue at the end of existing text. Select-all and `ControlOrMeta` follow the
browser persona (`--fingerprint-platform=macos` uses Meta), not the host OS.
Date/time inputs are typed segment by segment in the locale's order, sliders are
clicked near the value and nudged with arrow keys, `<select>` is driven with
clicks and arrow keys. `<input type=color>` opens a native dialog that cannot be
driven, so `FillAsync` on it throws; use `Humanize.Unwrap(page).FillAsync` if a
programmatic value is acceptable.

---

## Proxy, GeoIP & WebRTC

```csharp
await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
{
    Proxy = "http://user:pass@proxy.example.com:8080",   // or a ProxySettings
    GeoIp = true,                                         // tz/locale from exit IP
    Args  = new List<string> { "--fingerprint-webrtc-ip=auto" },
});
```

- **SOCKS5** and **credentialed HTTP** proxies are routed through Chrome's
  `--proxy-server` with inline, URL-encoded credentials (matching the Python
  logic, including the `linux-x64` / `windows-x64` + binary-version gate for HTTP
  inline auth). Because these are set on the browser, Playwright's own request
  client (`context.APIRequest`, `page.APIRequest`, `route.FetchAsync()`) does not
  use them and sends from your real IP. Make those calls from the page instead
  (`page.EvaluateAsync("url => fetch(url).then(r => r.text())", url)`).
- **GeoIP** looks up the proxy exit IP against MaxMind GeoLite2 and applies the
  resolved timezone/locale via binary flags.
- **WebRTC** spoofing reuses that exit IP so `RTCPeerConnection` cannot leak the
  real address.

---

## CLI

Installed via NuGet you don't need a CLI — the binary auto-downloads on first launch
and updates in the background, and `Download.BinaryInfo()` reports the installed
version, path, and tier (`Download.EnsureBinary()` pre-fetches it on demand).

When running from a clone of the repo, a small CLI does the same:

```bash
dotnet run --project src/CloakBrowser.Cli -- install      # download the binary
dotnet run --project src/CloakBrowser.Cli -- info         # version / path / platform
dotnet run --project src/CloakBrowser.Cli -- update       # check + download newer
dotnet run --project src/CloakBrowser.Cli -- clear-cache  # remove cached binaries
```

---

## Environment variables

Same set as the Python wrapper:

| Variable | Purpose |
| --- | --- |
| `CLOAKBROWSER_BINARY_PATH` | Use a local binary, skip download |
| `CLOAKBROWSER_CACHE_DIR` | Override the cache directory |
| `CLOAKBROWSER_DOWNLOAD_URL` | Override the download URL |
| `CLOAKBROWSER_AUTO_UPDATE` | Enable/disable background auto-update |
| `CLOAKBROWSER_SKIP_CHECKSUM` | Skip SHA-256 verification |
| `CLOAKBROWSER_VERSION` | Pin to an exact Chromium version for rollback (e.g. `154.0.8037.57.1`). Works with Free and Pro binaries |
| `CLOAKBROWSER_RELEASE_CHANNEL` | Set to `preview` to opt into the Pro Preview binary channel (default: `stable`) |
| `CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS` | GeoIP HTTP timeout |
| `CLOAKBROWSER_WIDEVINE_CDM` / `CLOAKBROWSER_WIDEVINE` | Widevine seeding control |

---

## Building & testing

```bash
cd dotnet
dotnet build CloakBrowser.sln     # 0 warnings, 0 errors
dotnet test  CloakBrowser.sln     # all green
```

The runnable examples accept a scenario name:

```bash
dotnet run --project examples/CloakBrowser.Examples -- basic
dotnet run --project examples/CloakBrowser.Examples -- humanize
dotnet run --project examples/CloakBrowser.Examples -- visual   # on-screen cursor trail
dotnet run --project examples/CloakBrowser.Examples -- behavioral
dotnet run --project examples/CloakBrowser.Examples -- proxy-geoip
```

### Test suite map

Unit tests run without a browser (`DispatchProxy`-backed Playwright fakes,
`Wrappers/FakeProxy.cs`). Real-browser tests run when `CLOAKBROWSER_BINARY_PATH`
points at a CloakBrowser binary, against a local test page served by
`HumanEngine/SiteServer.cs` (the same page as the Python and JS tests). Real-browser
classes share one serial xunit collection (`RealBrowser`).

| Area | File(s) | What it proves |
| --- | --- | --- |
| Version / download | `ConfigTests.cs`, `DownloadConfigTests.cs` | version compare, archive names, checksum parsing, **zip-slip** path guard |
| Launch args | `BuildArgsTests.cs`, `MiscTests.cs` | stealth args, `build_args` dedup |
| Proxy | `ProxyResolverTests.cs` | URL resolution / encoding |
| Bezier math | `BezierMathTests.cs` | curve shape and end point |
| Humanize config | `HumanConfigTests.cs` | presets, snake/Pascal overrides, merge never mutates base |
| Transparent layer | `Wrappers/*.cs` | delegation, re-wrapping of every handle/frame/locator-returning member, exceptions & `CancellationToken`s propagate |
| Engine (real browser) | `HumanEngine/HumanEngineBrowserTests.cs`, `HumanEngine/WorldSmokeTests.cs` | options, strict mode, timeouts, locators, fields, frames, handles, mouse, persona select-all |
| Standalone checks (real browser) | `HumanEngine/ActionabilityApiTests.cs`, `ScrollFallbackTests.cs` | public `Actionability` checks throw the typed errors; `HumanScroll` / `IsolatedWorld` keep working |
| Selector parity (real browser) | `Human/SelectorParityBrowserTests.cs`, `tests/test_resolver_sources_match.py` | actions land on the element Playwright resolves; Python/JS/.NET helper copies stay byte-identical |
| Timeout budget (#307) | `Human/TimeoutBudgetTests.cs` | one shared deadline, `0` = no limit |

---

## Mapping to the Python source

| .NET file | Python source |
| --- | --- |
| `Config.cs` | `cloakbrowser/config.py` |
| `Download.cs` | `cloakbrowser/download.py` |
| `GeoIp.cs` | `cloakbrowser/geoip.py` |
| `Widevine.cs` | `cloakbrowser/widevine.py` |
| `CloakLauncher.cs` / `ProxyResolver.cs` | `cloakbrowser/browser.py` |
| `Human/HumanConfig.cs` | `cloakbrowser/human/config.py` |
| `Human/HumanMouse.cs` | `cloakbrowser/human/mouse.py` |
| `Human/HumanKeyboard.cs` | `cloakbrowser/human/keyboard.py` |
| `Human/HumanEngine*.cs` | `cloakbrowser/human/engine.py` |
| `Human/HumanWorld.cs`, `Human/WorldHelpers.cs` | `cloakbrowser/human/world.py` |
| `Human/InjectedSource.cs` | `cloakbrowser/human/injected.py` |
| `Human/Fields.cs` | `cloakbrowser/human/fields.py` |
| `Wrappers/*.cs` | `cloakbrowser/human/patch.py` |
| `CloakBrowser.Cli/` | `cloakbrowser/__main__.py` |

---

## License

MIT - same as the upstream CloakBrowser project.
