# CloakBrowser for .NET

A complete, faithful **.NET 8 / C#** port of the
[CloakBrowser](https://github.com/CloakHQ/CloakBrowser) Python wrapper - stealth
Chromium that passes bot-detection tests, built on top of
[`Microsoft.Playwright`](https://playwright.dev/dotnet/).

CloakBrowser is a thin wrapper around a closed-source, source-level patched
Chromium binary (58 C++ fingerprint patches). This port reproduces **all** of the
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
  - [Actionability checks](#actionability-checks)
  - [Shared timeout budget (#307)](#shared-timeout-budget-307)
  - [Focus-aware press / clear](#focus-aware-press--clear)
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
| **CLI** (`install` / `info` / `update` / `clear-cache`) | ✅ | `CloakBrowser.Cli/` |

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
# add to your project
dotnet add package CloakBrowser

# the patched Chromium binary downloads automatically on first launch,
# or pre-install it:
dotnet run --project src/CloakBrowser.Cli -- install
```

The binary is cached under `~/.cloakbrowser` (override with
`CLOAKBROWSER_CACHE_DIR`).

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
│   │   │   ├── HumanKeyboard.cs         #   <- human/keyboard.py (typing + CDP stealth)
│   │   │   ├── HumanScroll.cs           #   <- human/scroll.py
│   │   │   ├── Actionability.cs         #   <- human/actionability.py
│   │   │   ├── IsolatedWorld.cs         #   <- _AsyncIsolatedWorld
│   │   │   ├── PlaywrightAdapters.cs    #   IMouse/IKeyboard/ICDPSession -> raw protocols
│   │   │   └── HumanPage.cs             #   <- patch_page flows (explicit engine)
│   │   └── Wrappers/                    # transparent humanize decorators (Humanize=true)
│   │       ├── Humanize.cs              #   wrap entry points + helpers (idempotent)
│   │       ├── HumanCursor.cs           #   shared per-page cursor / CDP stealth state
│   │       ├── LocatorHumanizer.cs      #   locator-based humanize engine
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
await page.Mouse.WheelAsync(0, 600);          // accelerate -> cruise -> decelerate scroll
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
| `IPage` / `ILocator` `ClickAsync`, `DblClickAsync`, `HoverAsync`, `TapAsync` | direct Playwright dispatch | Bezier-curve mouse move to a randomized in-element aim point, then click |
| `IPage` / `ILocator` `FillAsync`, `TypeAsync` / `PressSequentiallyAsync` | instant value set / fast type | per-character typing with variable delays, thinking pauses, occasional typos that self-correct |
| `IPage` / `ILocator` `PressAsync` | direct | human key timing; clicks to focus first only if not already focused |
| `ILocator` `CheckAsync`, `UncheckAsync`, `SetCheckedAsync`, `DragToAsync` | direct | humanized click / curved drag |
| `ILocator` `SelectOptionAsync` (all overloads) | instant native select | curved hover to the `<select>` + pause, then native select |
| `ILocator` `ClearAsync` | instant value reset | focus (humanized click if needed) + select-all + Backspace |
| `IMouse` `MoveAsync`, `ClickAsync`, `DblClickAsync`, `DownAsync`, `UpAsync` | direct | curved, eased motion with overshoot |
| `IMouse` `WheelAsync` | single event | accelerate-cruise-decelerate microsteps |
| `IKeyboard` `TypeAsync`, `PressAsync`, `InsertTextAsync` | direct | human-timed CDP key events |
| `page.Mouse`, `page.Keyboard`, `page.Locator(...)`, `page.GetBy*`, `page.Frames`, `QuerySelectorAsync`, `IBrowser.NewPageAsync/NewContextAsync`, `IBrowserContext.NewPageAsync` | raw Playwright objects | the same call returns a **wrapped** object so humanization stays transitive |
| every **other** member (navigation, waits, evaluation, screenshots, network, etc.) | - | **delegated verbatim** to Playwright (identical signatures, return types, exceptions, and `CancellationToken` support) |
| escape hatch | n/a | `((HumanizedPage)page).Original` (also `.Inner`) returns the raw, un-wrapped object; `browser.RawBrowser` on the handle |

Per-call overrides are honored - e.g.
`await page.ClickAsync("#x", new() { Force = true })` still works and is
humanized. `ElementHandle` interactions are humanized too, but prefer `ILocator`
(Playwright's recommendation) for the most reliable aiming.

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

`HumanPage` methods (all take an optional `HumanActionOptions { Timeout, Force }`):

| Method | Description |
| --- | --- |
| `GotoAsync(url, options?)` | navigate (delegates to the raw page) |
| `ClickAsync(selector)` | Bezier move + human click |
| `DblClickAsync(selector)` | move + double click |
| `HoverAsync(selector)` | curved move, no click |
| `TapAsync(selector)` | same motion as click |
| `TypeAsync(selector, text)` | focus + per-character typing |
| `FillAsync(selector, value)` | click + select-all + clear + type |
| `PressAsync(selector, key)` | focus-aware single key press |
| `PressSequentiallyAsync(selector, text)` | focus + per-character typing |
| `ClearAsync(selector)` | focus + select-all + Backspace |
| `CheckAsync` / `UncheckAsync` / `SetCheckedAsync(selector, state)` | humanized toggle via click |
| `SelectOptionAsync(selector, values)` | curved hover + native select |
| `FocusAsync(selector)` | curved move + **programmatic** focus (no click side-effects) |
| `ScrollIntoViewIfNeededAsync(selector)` | humanized accelerate->cruise->decelerate->overshoot scroll |
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

### CloakBrowser Pro

Pass a `LicenseKey` (or set `CLOAKBROWSER_LICENSE_KEY`, or write the key to
`~/.cloakbrowser/license.key`) to download the latest **Pro** binary from
cloakbrowser.dev. Without a key, the free binary downloads from GitHub Releases
exactly as before. License validation is cached locally for 24h, and the Pro
binary is authenticated with the **same pinned Ed25519 signature** as the free
binary. A valid key whose Pro download or signature check fails surfaces a clear
error rather than silently downgrading to the free binary. `Download.BinaryInfo()`
exposes a `Tier` field (`"pro"` / `"free"`) and `License.ValidateLicense` /
`License.LicenseInfo` mirror the Python `validate_license` / `LicenseInfo` exports.

```csharp
await using var browser = await CloakLauncher.LaunchAsync(new LaunchOptions
{
    LicenseKey = "ck_live_...",   // or via CLOAKBROWSER_LICENSE_KEY / ~/.cloakbrowser/license.key
});
```

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

`HumanKeyboard.HumanTypeAsync` types one character at a time with variable delays
and occasional "thinking" pauses. ASCII alphanumeric characters can trigger a
**fat-finger typo** (a nearby QWERTY key) that is then noticed and corrected with
Backspace.

Shift symbols (`@ # ! $ ...`) are the tricky case for stealth. When a **CDP
session** is available, they are dispatched through
`Input.dispatchKeyEvent` - producing `isTrusted = true` events with **no
`evaluate` stack trace** for detectors to find. Without CDP, it falls back to a
(detectable) `page.evaluate` path.

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

`HumanScroll` performs an **accelerate -> cruise -> decelerate** wheel sequence in
microsteps, with an optional overshoot-and-settle, landing the element in a
natural viewport band (`ScrollTargetZone`).

### Actionability checks

Before interacting, the humanize layer runs Playwright-style **actionability
checks** (`Actionability.cs`), with a retry/backoff loop `[100, 250, 500, 1000]`
ms:

| Check | Meaning | Error on failure |
| --- | --- | --- |
| `attached` | element exists in the DOM | `ElementNotAttachedError` |
| `visible` | element is visible | `ElementNotVisibleError` |
| `stable` | bounding box stopped moving (post-scroll) | `ElementNotStableError` |
| `enabled` | element is enabled | `ElementNotEnabledError` |
| `editable` | element is editable | `ElementNotEditableError` |
| `pointer_events` | the click point actually hits the element | `ElementNotReceivingEventsError` |

Action presets: `ChecksClick`, `ChecksHover`, `ChecksInput`, `ChecksFocus`,
`ChecksCheck`.

**Fail-open pointer check.** The `pointer_events` probe uses
`document.elementFromPoint`. If it *cannot run* (stale handle, execution context
destroyed - `EvaluateAsync` throws), the check **fails open** and returns
promptly rather than blocking until timeout - failing closed would wrongly block
legitimate clicks. But an explicit `{ hit: false }` (the element is genuinely
*covered*) still raises `ElementNotReceivingEventsError`.

### Shared timeout budget (#307)

All sequential steps of one action share a **single deadline** rather than each
restarting the full timeout. The helper
`Actionability.RemainingMs(deadline)` returns the milliseconds left (clamped at
zero, never negative). Because every step subtracts from the *same* budget, the
total wall-clock time can never multiply across steps - the bug fixed in
upstream issue **#307**.

### Focus-aware press / clear

`PressAsync` and `ClearAsync` first probe focus with
`EvaluateAsync<bool>("el => el === document.activeElement")`. If the element is
**already focused**, they **skip the humanized click** entirely (the cursor does
not move) and go straight to the keystrokes; otherwise they perform a humanized
focus-click first. This avoids pointless mouse motion on an already-focused
field.

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
  inline auth).
- **GeoIP** looks up the proxy exit IP against MaxMind GeoLite2 and applies the
  resolved timezone/locale via binary flags.
- **WebRTC** spoofing reuses that exit IP so `RTCPeerConnection` cannot leak the
  real address.

---

## CLI

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

All tests are **browser-free**: production wrappers are exercised through
`DispatchProxy`-backed Playwright fakes (`Wrappers/FakeProxy.cs`,
`Fake.Of<T>()`), and `InternalsVisibleTo` lets the tests reach internal types.
A handful of genuinely browser-dependent timing tests are marked
`[Fact(Skip = "requires browser")]` rather than faked.

| Area | File(s) | What it proves |
| --- | --- | --- |
| Version / download | `ConfigTests.cs`, `DownloadConfigTests.cs` | version compare, archive names, checksum parsing, **zip-slip** path guard |
| Launch args | `BuildArgsTests.cs`, `MiscTests.cs` | stealth args, `build_args` dedup |
| Proxy | `ProxyResolverTests.cs` | URL resolution / encoding |
| Bezier math | `BezierMathTests.cs` | curve produces many points, ends near target, no big jumps, deviates from a straight line |
| Humanize config | `HumanConfigTests.cs` | presets, snake/Pascal overrides, range coercion, **merge never mutates base**, null/empty/unknown-key handling |
| Transparent layer | `Wrappers/*.cs` | non-intercepted members delegate verbatim; intercepted members humanize; nested objects come back wrapped; exceptions & `CancellationToken`s propagate |
| Non-ASCII keyboard | `Human/NonAsciiKeyboardTests.cs` | Cyrillic/CJK go via `InsertText`; ASCII via key presses; mixed strings route per-character |
| Pointer-events fail-open | `Human/PointerEventsFailOpenTests.cs` | throwing probe returns fast (`< 500ms`); explicit "covered" raises `ElementNotReceivingEventsError` |
| Timeout budget (#307) | `Human/TimeoutBudgetTests.cs` | `RemainingMs` never negative, decreases over time, shared (not multiplied) |
| Focus check | `Wrappers/FocusCheckTests.cs` | focused element -> no humanized click (cursor doesn't move); non-focused -> click happens |

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
| `Human/HumanScroll.cs` | `cloakbrowser/human/scroll.py` |
| `Human/Actionability.cs` | `cloakbrowser/human/actionability.py` |
| `Human/HumanPage.cs` | `cloakbrowser/human/__init__.py` (`patch_page`) |
| `CloakBrowser.Cli/` | `cloakbrowser/__main__.py` |

---

## License

MIT - same as the upstream CloakBrowser project.
