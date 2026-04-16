<p align="center">
<img src="https://i.imgur.com/cqkp6fG.png" width="500" alt="CloakBrowser">
</p>

<p align="center">
<a href="https://pypi.org/project/cloakbrowser/"><img src="https://img.shields.io/pypi/v/cloakbrowser" alt="PyPI"></a>
<a href="https://www.npmjs.com/package/cloakbrowser"><img src="https://img.shields.io/npm/v/cloakbrowser" alt="npm"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/cloakhq/cloakbrowser?v=1" alt="License"></a>
<a href="https://github.com/CloakHQ/CloakBrowser"><img src="https://img.shields.io/github/last-commit/cloakhq/cloakbrowser" alt="Last Commit"></a>
<br>
<a href="https://github.com/CloakHQ/CloakBrowser"><img src="https://img.shields.io/github/stars/cloakhq/cloakbrowser" alt="Stars"></a>
<a href="https://pypi.org/project/cloakbrowser/"><img src="https://img.shields.io/pepy/dt/cloakbrowser?label=pypi&logo=pypi&logoColor=white" alt="PyPI Downloads"></a>
<a href="https://www.npmjs.com/package/cloakbrowser"><img src="https://img.shields.io/npm/dt/cloakbrowser?label=npm&logo=npm&logoColor=white" alt="npm Downloads"></a>
<a href="https://hub.docker.com/r/cloakhq/cloakbrowser"><img src="https://img.shields.io/docker/pulls/cloakhq/cloakbrowser?label=docker&logo=docker&logoColor=white" alt="Docker Pulls"></a>
</p>

<p align="center">
<a href="https://ko-fi.com/cloakhq"><img src="https://ko-fi.com/img/githubbutton_sm.svg" alt="Support on Ko-fi"></a>
</p>

<br>

<h3 align="center">Stealth Chromium that passes every bot detection test.</h3>

<table><tr><td>
Not a patched config. Not a JS injection. A real Chromium binary with fingerprints modified at the C++ source level. Antibot systems score it as a normal browser — because it <em>is</em> a normal browser.
</td></tr></table>

<br>

<p align="center">
<img src="https://i.imgur.com/IvB0It7.gif" width="600" alt="Cloudflare Turnstile — 3 Tests Passing">
<br><em>Cloudflare Turnstile — 3 live tests passing (headed mode, macOS)</em>
</p>

<br>

<p align="center">
Drop-in Playwright/Puppeteer replacement for Python and JavaScript.<br>
Same API, same code — just swap the import. <strong>3 lines of code, 30 seconds to unblock.</strong>
</p>

- **49 source-level C++ patches** — canvas, WebGL, audio, fonts, GPU, screen, WebRTC, network timing, automation signals, CDP input behavior
- **`humanize=True`** — human-like mouse curves, keyboard timing, and scroll patterns. One flag, behavioral detection passes
- **0.9 reCAPTCHA v3 score** — human-level, server-verified
- **Passes Cloudflare Turnstile**, FingerprintJS, BrowserScan — tested against 30+ detection sites
- **Auto-updating binary** — background update checks, always on the latest stealth build
- **`pip install cloakbrowser`** or **`npm install cloakbrowser`** — binary auto-downloads, zero config
- **Free and open source** — no subscriptions, no usage limits

**Try it now** — no install needed:
```bash
docker run --rm cloakhq/cloakbrowser cloaktest
```

**Python:**
```python
from cloakbrowser import launch

browser = launch()
page = browser.new_page()
page.goto("https://protected-site.com")  # no more blocks
browser.close()
```

**JavaScript (Playwright):**
```javascript
import { launch } from 'cloakbrowser';

const browser = await launch();
const page = await browser.newPage();
await page.goto('https://protected-site.com');
await browser.close();
```

Also works with Puppeteer: `import { launch } from 'cloakbrowser/puppeteer'` ([details](#puppeteer))

## Install

**Python:**
```bash
pip install cloakbrowser
```

**JavaScript / Node.js:**
```bash
# With Playwright
npm install cloakbrowser playwright-core

# With Puppeteer
npm install cloakbrowser puppeteer-core
```

On first run, the stealth Chromium binary is automatically downloaded (~200MB, cached locally).

**Optional:** Auto-detect timezone/locale from proxy IP:
```bash
pip install cloakbrowser[geoip]
```

**Migrating from Playwright?** One-line change:

```diff
- from playwright.sync_api import sync_playwright
- pw = sync_playwright().start()
- browser = pw.chromium.launch()
+ from cloakbrowser import launch
+ browser = launch()

page = browser.new_page()
page.goto("https://example.com")
# ... rest of your code works unchanged
```

> ⭐ **Star** to show support — **[Watch releases](https://github.com/CloakHQ/CloakBrowser/subscription)** to get notified when new builds drop.

## Browser Profile Manager

Self-hosted alternative to Multilogin, GoLogin, and AdsPower. Create browser profiles with unique fingerprints, proxies, and persistent sessions. Launch and interact with them in your browser via noVNC.

```bash
docker run -p 8080:8080 -v cloakprofiles:/data cloakhq/cloakbrowser-manager
```

Open [http://localhost:8080](http://localhost:8080). Create a profile. Click **Launch**. Done.

→ **[CloakBrowser Manager](https://github.com/CloakHQ/CloakBrowser-Manager)** — free, open source (MIT)

---

## Latest: v0.3.24 (Chromium 146.0.7680.177.2)

- **Native SOCKS5 proxy** — `proxy="socks5://user:pass@host:port"` works directly in all launch functions, Python + JS. QUIC/HTTP3 tunnels through SOCKS5 via UDP ASSOCIATE.
- **Chromium 146 upgrade** — rebased all patches from 145.0.7632.x to 146.0.7680.177
- **49 fingerprint patches** — Linux arm64 now matches Linux x64 on Chromium 146
- **WebRTC IP spoofing** — `--fingerprint-webrtc-ip=auto` resolves your proxy's exit IP and spoofs WebRTC ICE candidates. Auto-injected when using `geoip=True` (no extra network call)
- **Proxy signal removal** — DNS/connect/SSL timing zeroed, proxy cache headers stripped, Proxy-Connection header leak removed
- **`cloakserve` CDP multiplexer** — rewritten as a multi-connection CDP proxy with per-connection fingerprint seeds
- **Humanize CDP isolation** — keyboard events now use isolated worlds and trusted dispatch for better behavioral stealth
- **`humanize=True`** — one flag makes all mouse, keyboard, and scroll interactions behave like a real user. Bézier curves, per-character typing, realistic scroll patterns
- **Stealthy with zero flags** — binary auto-generates a random fingerprint seed at startup. No configuration required
- **Timezone & locale from proxy IP** — `launch(proxy="...", geoip=True)` auto-detects timezone and locale
- **Persistent profiles** — `launch_persistent_context()` keeps cookies and localStorage across sessions, bypasses incognito detection

See the full [CHANGELOG.md](CHANGELOG.md) for details.

## Why CloakBrowser?

- **Config-level patches break** — `playwright-stealth`, `undetected-chromedriver`, and `puppeteer-extra` inject JavaScript or tweak flags. Every Chrome update breaks them. Antibot systems detect the patches themselves.
- **CloakBrowser patches Chromium source code** — fingerprints are modified at the C++ level, compiled into the binary. Detection sites see a real browser because it *is* a real browser.
- **Source-level stealth** — C++ patches handle fingerprints (GPU, screen, UA, hardware reporting) at the binary level. No JavaScript injection, no config-level hacks. Most stealth tools only patch at the surface.
- **Same behavior everywhere** — works identically local, in Docker, and on VPS. No environment-specific patches or config needed.
- **Works with AI agents and automation frameworks** — drop-in stealth for browser-use, Crawl4AI, Scrapling, Stagehand, LangChain, Selenium, and more. See [integrations](#framework-integrations).

CloakBrowser doesn't solve CAPTCHAs — it prevents them from appearing. No CAPTCHA-solving services, no proxy rotation built in — bring your own proxies, use the Playwright API you already know.

## Test Results

All tests verified against live detection services. Last tested: Apr 2026 (Chromium 146).

| Detection Service | Stock Playwright | CloakBrowser | Notes |
|---|---|---|---|
| **reCAPTCHA v3** | 0.1 (bot) | **0.9** (human) | Server-side verified |
| **Cloudflare Turnstile** (non-interactive) | FAIL | **PASS** | Auto-resolve |
| **Cloudflare Turnstile** (managed) | FAIL | **PASS** | Single click |
| **ShieldSquare** | BLOCKED | **PASS** | Production site |
| **FingerprintJS** bot detection | DETECTED | **PASS** | demo.fingerprint.com |
| **BrowserScan** bot detection | DETECTED | **NORMAL** (4/4) | browserscan.net |
| **bot.incolumitas.com** | 13 fails | **1 fail** | WEBDRIVER spec only |
| **deviceandbrowserinfo.com** | 6 true flags | **0 true flags** | `isBot: false` |
| `navigator.webdriver` | `true` | **`false`** | Source-level patch |
| `navigator.plugins.length` | 0 | **5** | Real plugin list |
| `window.chrome` | `undefined` | **`object`** | Present like real Chrome |
| UA string | `HeadlessChrome` | **`Chrome/146.0.0.0`** | No headless leak |
| CDP detection | Detected | **Not detected** | `isAutomatedWithCDP: false` |
| TLS fingerprint | Mismatch | **Identical to Chrome** | ja3n/ja4/akamai match |
| | | **Tested against 30+ detection sites** | |

### Proof

<p align="center">
<img src="https://i.imgur.com/hvIQyMv.png" width="600" alt="reCAPTCHA v3 — Score 0.9">
<br><em>reCAPTCHA v3 score 0.9 — server-side verified (human-level)</em>
</p>

<p align="center">
<img src="https://i.imgur.com/qMIRfhq.png" width="600" alt="Cloudflare Turnstile — Success">
<br><em>Cloudflare Turnstile non-interactive challenge — auto-resolved</em>
</p>

<p align="center">
<img src="https://i.imgur.com/PRsw6rT.png" width="600" alt="BrowserScan — Normal">
<br><em>BrowserScan bot detection — NORMAL (4/4 checks passed)</em>
</p>

<p align="center">
<img src="https://i.imgur.com/9n2C7tu.png" width="600" alt="FingerprintJS — Passed">
<br><em>FingerprintJS web-scraping demo — data served, not blocked</em>
</p>

<p align="center">
<img src="https://i.imgur.com/srCcFtK.png" width="600" alt="deviceandbrowserinfo.com — You are human!">
<br><em>deviceandbrowserinfo.com behavioral bot detection — "You are human!" with humanize=True (24/24 signals passed)</em>
</p>

## Comparison

| Feature | Playwright | playwright-stealth | undetected-chromedriver | Camoufox | CloakBrowser |
|---|---|---|---|---|---|
| reCAPTCHA v3 score | 0.1 | 0.3-0.5 | 0.3-0.7 | 0.7-0.9 | **0.9** |
| Cloudflare Turnstile | Fail | Sometimes | Sometimes | Pass | **Pass** |
| Patch level | None | JS injection | Config patches | C++ (Firefox) | **C++ (Chromium)** |
| Survives Chrome updates | N/A | Breaks often | Breaks often | Yes | **Yes** |
| Maintained | Yes | Stale | Stale | Unstable | **Active** |
| Browser engine | Chromium | Chromium | Chrome | Firefox | **Chromium** |
| Playwright API | Native | Native | No (Selenium) | No | **Native** |

## How It Works

CloakBrowser is a thin wrapper (Python + JavaScript) around a custom-built Chromium binary:

1. **You install** → `pip install cloakbrowser` or `npm install cloakbrowser`
2. **First launch** → binary auto-downloads for your platform (Chromium 146)
3. **Every launch** → Playwright or Puppeteer starts with our binary + stealth args
4. **You write code** → standard Playwright/Puppeteer API, nothing new to learn

The binary includes 49 source-level patches covering canvas, WebGL, audio, fonts, GPU, screen properties, WebRTC, network timing, hardware reporting, automation signal removal, and CDP input behavior mimicking.

These are compiled into the Chromium binary — not injected via JavaScript, not set via flags.

Binary downloads are verified with SHA-256 checksums to ensure integrity.

## API

### `launch()`

```python
from cloakbrowser import launch

# Basic — headless, default stealth config
browser = launch()

# Headed mode (see the browser window)
browser = launch(headless=False)

# With proxy (HTTP or SOCKS5)
browser = launch(proxy="http://user:pass@proxy:8080")
browser = launch(proxy="socks5://user:pass@proxy:1080")

# With proxy dict (bypass, separate auth fields)
browser = launch(proxy={"server": "http://proxy:8080", "bypass": ".google.com", "username": "user", "password": "pass"})

# With extra Chrome args
browser = launch(args=["--disable-gpu"])

# With timezone and locale (sets binary flags — no detectable CDP emulation)
browser = launch(timezone="America/New_York", locale="en-US")

# Auto-detect timezone/locale from proxy IP (requires: pip install cloakbrowser[geoip])
# Also auto-injects --fingerprint-webrtc-ip to prevent WebRTC IP leaks (no extra cost)
# Note: makes HTTP calls through your proxy to resolve exit IP (ipify.org, checkip.amazonaws.com)
browser = launch(proxy="http://proxy:8080", geoip=True)

# Explicit timezone/locale always win over auto-detection
browser = launch(proxy="http://proxy:8080", geoip=True, timezone="Europe/London")

# WebRTC IP spoofing only (no geoip dep needed — resolves exit IP via HTTP call through proxy)
browser = launch(proxy="http://proxy:8080", args=["--fingerprint-webrtc-ip=auto"])

# Explicit WebRTC IP (no network call)
browser = launch(proxy="http://proxy:8080", args=["--fingerprint-webrtc-ip=1.2.3.4"])

# Human-like mouse, keyboard, and scroll behavior
browser = launch(humanize=True)

# With slower, more deliberate movements
browser = launch(humanize=True, human_preset="careful")

# Without default stealth args (bring your own fingerprint flags)
browser = launch(stealth_args=False, args=["--fingerprint=12345"])
```

Returns a standard Playwright `Browser` object. All Playwright methods work: `new_page()`, `new_context()`, `close()`, etc.

### `launch_async()`

```python
import asyncio
from cloakbrowser import launch_async

async def main():
    browser = await launch_async()
    page = await browser.new_page()
    await page.goto("https://example.com")
    print(await page.title())
    await browser.close()

asyncio.run(main())
```

### `launch_context()`

Convenience function that creates browser + context in one call with user agent, viewport, locale, and timezone:

```python
from cloakbrowser import launch_context

context = launch_context(
    user_agent="Custom UA",
    viewport={"width": 1920, "height": 1080},
    locale="en-US",
    timezone="America/New_York",
)
page = context.new_page()
page.goto("https://protected-site.com")
context.close()
```

Extra kwargs are forwarded to Playwright's `browser.new_context()` — use this for `storage_state`, `permissions`, `extra_http_headers`, etc. without needing a persistent profile folder:

```python
from cloakbrowser import launch_context

# Restore a saved session (cookies, localStorage) from a JSON file
context = launch_context(storage_state="state.json")
page = context.new_page()
page.goto("https://example.com")
# Save state back for next run
context.storage_state(path="state.json")
context.close()
```

### `launch_context_async()`

Async counterpart to `launch_context()`. Same signature and kwargs forwarding:

```python
import asyncio
from cloakbrowser import launch_context_async

async def main():
    ctx = await launch_context_async(storage_state="state.json")
    page = await ctx.new_page()
    await page.goto("https://example.com")
    await ctx.storage_state(path="state.json")
    await ctx.close()

asyncio.run(main())
```

### `launch_persistent_context()`

Same as `launch_context()`, but with a persistent user profile. Cookies, localStorage, and cache persist across sessions.

Use this when you need to:
- **Stay logged in** across runs (cookies/sessions survive restarts)
- **Bypass incognito detection** (some sites flag empty, ephemeral profiles)
- **Load Chrome extensions** (extensions only work from a real user data dir)
- **Build natural browsing history** (cached fonts, service workers, IndexedDB accumulate over time, making the profile look more realistic)

```python
from cloakbrowser import launch_persistent_context

# First run — creates the profile
ctx = launch_persistent_context("./my-profile", headless=False)
page = ctx.new_page()
page.goto("https://protected-site.com")
ctx.close()  # profile saved

# Next run — cookies, localStorage restored automatically
ctx = launch_persistent_context("./my-profile", headless=False)
```

Supports all the same options as `launch_context()`: `proxy`, `user_agent`, `viewport`, `locale`, `timezone`, `color_scheme`, `geoip`.

Async version: `launch_persistent_context_async()`.

**Storage quota and detection tradeoff:** By default, the binary normalizes storage quota to pass FingerprintJS, which blocks persistent contexts that report non-incognito quota values. This means detection services that penalize incognito mode (like BrowserScan's `notPrivate` check, -10 points) will still flag it. If your target site penalizes incognito but doesn't use FingerprintJS, set a higher quota to appear as a regular profile:

```python
ctx = launch_persistent_context("./my-profile", args=["--fingerprint-storage-quota=5000"])
```

| Quota setting | FingerprintJS | BrowserScan `notPrivate` |
|---|---|---|
| Default (auto, ~500MB) | PASS | -10 (flagged as incognito) |
| `--fingerprint-storage-quota=5000` | May trigger detection | PASS (appears non-incognito) |

### CLI

Pre-download the binary or check installation status from the command line:

```bash
python -m cloakbrowser install      # Download binary with progress output
python -m cloakbrowser info         # Show version, path, platform
python -m cloakbrowser update       # Check for and download newer binary
python -m cloakbrowser clear-cache  # Remove cached binaries
```

### Utility Functions

```python
from cloakbrowser import binary_info, clear_cache, ensure_binary

# Check binary installation status
print(binary_info())
# {'version': '146.0.7680.177.2', 'platform': 'linux-x64', 'installed': True, ...}

# Force re-download
clear_cache()

# Pre-download binary (e.g., during Docker build)
ensure_binary()
```

## JavaScript / Node.js API

CloakBrowser ships a TypeScript package with full type definitions. Choose Playwright or Puppeteer — same stealth binary underneath.

### Playwright (default)

```javascript
import { launch, launchContext, launchPersistentContext } from 'cloakbrowser';

// Basic
const browser = await launch();

// With options
const browser = await launch({
  headless: false,
  proxy: 'http://user:pass@proxy:8080',
  args: ['--fingerprint=12345'],
  timezone: 'America/New_York',
  locale: 'en-US',
  humanize: true,
});

// Convenience: browser + context in one call
const context = await launchContext({
  userAgent: 'Custom UA',
  viewport: { width: 1920, height: 1080 },
  locale: 'en-US',
  timezone: 'America/New_York',
});
const page = await context.newPage();

// Persistent profile — cookies/localStorage survive restarts, avoids incognito detection
const ctx = await launchPersistentContext({
  userDataDir: './chrome-profile',
  headless: false,
  proxy: 'http://user:pass@proxy:8080',
});
```

> **Note:** Each example above is standalone — not meant to run as one block.

All Python options work in JS: `stealthArgs: false` to disable defaults, `geoip: true` to auto-detect timezone/locale from proxy IP.

### Puppeteer

> **Note:** The Playwright wrapper is recommended for sites with reCAPTCHA Enterprise. Puppeteer's CDP protocol leaks automation signals that reCAPTCHA Enterprise can detect, causing intermittent 403 errors. This is a known Puppeteer limitation, not specific to CloakBrowser. Use Playwright for best results.

```javascript
import { launch } from 'cloakbrowser/puppeteer';

const browser = await launch({ headless: true });
const page = await browser.newPage();
await page.goto('https://example.com');
await browser.close();
```

### Utility Functions (JS)

```javascript
import { ensureBinary, clearCache, binaryInfo } from 'cloakbrowser';

// Pre-download binary (e.g., during Docker build)
await ensureBinary();

// Check installation status
console.log(binaryInfo());

// Force re-download
clearCache();
```

## Human Behavior

Pass `humanize=True` to make all mouse, keyboard, and scroll interactions indistinguishable from real users. All Playwright calls (`page.click()`, `page.fill()`, `page.type()`, `page.mouse.*`, `page.keyboard.*`, Locator API) and Puppeteer calls (`page.click()`, `page.type()`, `page.mouse.*`, `page.keyboard.*`, ElementHandle API) are automatically replaced with human-like equivalents. No code changes needed.

```python
browser = launch(humanize=True)
page = browser.new_page()
page.goto("https://example.com")
page.locator("#email").fill("user@example.com")  # per-character timing, thinking pauses
page.locator("button[type=submit]").click()       # Bézier curve, realistic aim point
```

```javascript
// Playwright
import { launch } from 'cloakbrowser';
const browser = await launch({ humanize: true });
```

```javascript
// Puppeteer
import { launch } from 'cloakbrowser/puppeteer';
const browser = await launch({ humanize: true });
```

**What changes:**

| Interaction | Default | With `humanize=True` |
|---|---|---|
| Mouse movement | Instant teleport | Bézier curve with easing and slight overshoot |
| Clicks | Instant | Realistic aim point + hold duration |
| Keyboard | Instant fill | Per-character timing, thinking pauses, occasional typos with self-correction |
| Scroll | Jump | Accelerate → cruise → decelerate micro-steps |
| `fill()` | Instant value set | Clears existing content, types character by character |

**Presets** — `default` (normal speed) or `careful` (slower, more deliberate, idle micro-movements between actions):

```python
browser = launch(humanize=True, human_preset="careful")
```

```javascript
const browser = await launch({ humanize: true, humanPreset: 'careful' });
```

**Custom config** — override any parameter:

```python
browser = launch(humanize=True, human_config={
    "mistype_chance": 0.05,              # 5% typo rate with self-correction
    "typing_delay": 100,                 # slower typing (ms per character)
    "idle_between_actions": True,        # micro-movements between clicks
    "idle_between_duration": [0.3, 0.8], # idle duration range (seconds)
})
```

```javascript
const browser = await launch({
    humanize: true,
    humanConfig: {
        mistype_chance: 0.05,
        typing_delay: 100,
        idle_between_actions: true,
        idle_between_duration: [0.3, 0.8],
    }
});
```

Access the original un-patched Playwright page at `page._original` if you need raw speed for a specific call.

> **Note (Playwright):** Always use `page.click(selector)`, `page.type(selector, text)`, `page.hover(selector)`, or `page.locator(selector).*` — these go through the full humanize pipeline. Avoid `page.query_selector()` — `ElementHandle` objects bypass all patches, so mouse movement teleports, keyboard events fire without timing, and scroll has no human curve.
>
> **Note (Puppeteer):** Both selector-based methods (`page.click()`, `page.type()`) and ElementHandle methods (`el.click()`, `el.type()`) are fully humanized. `page.$()`, `page.$$()`, and `page.waitForSelector()` return patched handles automatically.

> Contributed by [@evelaa123](https://github.com/evelaa123) — full Playwright and Puppeteer API coverage.

## Configuration

| Env Variable | Default | Description |
|---|---|---|
| `CLOAKBROWSER_BINARY_PATH` | — | Skip download, use a local Chromium binary |
| `CLOAKBROWSER_CACHE_DIR` | `~/.cloakbrowser` | Binary cache directory |
| `CLOAKBROWSER_DOWNLOAD_URL` | `cloakbrowser.dev` | Custom download URL for binary |
| `CLOAKBROWSER_AUTO_UPDATE` | `true` | Set to `false` to disable background update checks |
| `CLOAKBROWSER_SKIP_CHECKSUM` | `false` | Set to `true` to skip SHA-256 verification after download |

## Fingerprint Management

The binary is **stealthy by default** — no flags needed. It auto-generates a random fingerprint seed at startup and spoofs all detectable values (GPU, hardware specs, screen dimensions, canvas, WebGL, audio, fonts). Every launch produces a fresh, coherent identity.

**How fingerprinting works:**

| Scenario | What happens |
|----------|-------------|
| **No flags** | Random seed auto-generated at startup. GPU, screen, hardware specs, and all noise patches are spoofed automatically. Fresh identity each launch. |
| **`--fingerprint=seed`** | Deterministic identity from the seed. Same seed = same fingerprint across launches. Use this for session persistence (returning visitor). |
| **`--fingerprint=seed` + explicit flags** | Explicit flags override individual auto-generated values. The seed fills in everything else. |

The binary detects its platform at compile time — a macOS binary reports as macOS with Apple GPU, a Linux binary reports as Linux with NVIDIA GPU. The **wrapper** overrides this on Linux by passing `--fingerprint-platform=windows`, so sessions appear as Windows desktops (more common fingerprint, harder to cluster). Use `--fingerprint-platform` for cross-platform spoofing when running the binary directly.

> **Tip: Use a fixed seed when revisiting the same site.** A random seed makes every session look like a different device — which can be suspicious when hitting the same site repeatedly from the same IP. For reCAPTCHA v3 Enterprise and similar scoring systems, a fixed seed produces a consistent fingerprint across sessions, making you look like a returning visitor:
> ```python
> browser = launch(args=["--fingerprint=12345"])
> ```
> ```javascript
> const browser = await launch({ args: ['--fingerprint=12345'] });
> ```

### Default Fingerprint

Every `launch()` call sets these automatically. The **wrapper** applies platform-aware defaults — on Linux it spoofs as Windows for a more common fingerprint, on macOS it runs as a native Mac browser:

| Flag | Linux/Windows Default | macOS Default | Controls |
|------|--------------|---------------|----------|
| `--fingerprint` | Random (10000–99999) | Random (10000–99999) | Master seed for canvas, WebGL, audio, fonts, client rects |
| `--fingerprint-platform` | `windows` | `macos` | `navigator.platform`, User-Agent OS, GPU pool selection |

The binary auto-generates everything else from the seed: GPU, hardware concurrency, device memory, and screen dimensions. Each seed produces a unique, consistent fingerprint. Override with explicit flags if needed.

> **Using the binary directly?** It works out of the box with zero flags -- the binary auto-spoofs everything. Pass `--fingerprint=seed` for a persistent identity, or use explicit flags like `--fingerprint-gpu-renderer` to override any auto-generated value.

### Additional Flags

Supported by the binary but **not set by default** — pass via `args` to customize:

| Flag | Controls |
|------|----------|
| `--fingerprint-gpu-vendor` | WebGL `UNMASKED_VENDOR_WEBGL` (auto-generated from seed + platform) |
| `--fingerprint-gpu-renderer` | WebGL `UNMASKED_RENDERER_WEBGL` (auto-generated from seed + platform) |
| `--fingerprint-hardware-concurrency` | `navigator.hardwareConcurrency` (auto-generated: `8`) |
| `--fingerprint-device-memory` | `navigator.deviceMemory` in GB (auto-generated: `8`) |
| `--fingerprint-screen-width` | Screen width (auto-generated: `1920` Win/Linux, `1440` macOS) |
| `--fingerprint-screen-height` | Screen height (auto-generated: `1080` Win/Linux, `900` macOS) |
| `--fingerprint-brand` | Browser brand: `Chrome`, `Edge`, `Opera`, `Vivaldi` |
| `--fingerprint-brand-version` | Brand version (UA + Client Hints) |
| `--fingerprint-platform-version` | Client Hints platform version |
| `--fingerprint-location` | Geolocation coordinates |
| `--fingerprint-timezone` | Timezone (e.g. `America/New_York`) |
| `--fingerprint-locale` | Locale (e.g. `en-US`) |
| `--fingerprint-storage-quota` | Override storage quota in MB — affects `storage.estimate()`, `storageBuckets`, and legacy webkit APIs. Auto-normalized when `--fingerprint` is set |
| `--fingerprint-taskbar-height` | Override taskbar height (binary defaults: Win=48, Mac=95, Linux=0) |
| `--fingerprint-fonts-dir` | Path to cross-platform font directory |
| `--fingerprint-webrtc-ip` | WebRTC ICE candidate IP replacement. Use `auto` to resolve from proxy exit IP (makes an HTTP call through the proxy), or pass an explicit IP. Auto-injected when `geoip=True` |
| `--fingerprint-noise=false` | Disable noise injection (canvas, WebGL, audio, client rects) while keeping the deterministic fingerprint seed active |
| `--enable-blink-features=FakeShadowRoot` | Access closed shadow DOM elements |

> **Note:** All stealth tests were verified with the default fingerprint config above. Changing these flags may affect detection results — test your configuration before using in production.

### Examples

```python
# Pin a seed for a persistent identity
browser = launch(args=["--fingerprint=42069"])

# Full control — disable defaults, set everything yourself
browser = launch(stealth_args=False, args=[
    "--fingerprint=42069",
    "--fingerprint-platform=windows",
])

# Override GPU to look like a specific machine
browser = launch(args=[
    "--fingerprint-gpu-vendor=Intel Inc.",
    "--fingerprint-gpu-renderer=Intel Iris OpenGL Engine",
])
```

## Examples

**Python** — see [`examples/`](examples/):
- [`basic.py`](examples/basic.py) — Launch and load a page
- [`persistent_context.py`](examples/persistent_context.py) — Persistent profile with cookie/localStorage persistence
- [`recaptcha_score.py`](examples/recaptcha_score.py) — Check your reCAPTCHA v3 score
- [`stealth_test.py`](examples/stealth_test.py) — Run against 6 detection sites
- [`fingerprint_scan_test.py`](examples/fingerprint_scan_test.py) — Test against fingerprint-scan.com and CreepJS

**JavaScript** — see [`js/examples/`](js/examples/):
- [`basic-playwright.ts`](js/examples/basic-playwright.ts) — Playwright launch and load
- [`basic-puppeteer.ts`](js/examples/basic-puppeteer.ts) — Puppeteer launch and load
- [`stealth-test.ts`](js/examples/stealth-test.ts) — Run against 6 detection sites

### Framework Integrations

CloakBrowser works with any framework that uses Playwright or Chromium:

```python
# Option 1: Framework launches our binary directly (Selenium, Stagehand, UC)
from cloakbrowser.download import ensure_binary
from cloakbrowser.config import get_default_stealth_args
binary_path = ensure_binary()          # auto-downloads if needed
stealth_args = get_default_stealth_args()  # all fingerprint flags

# Option 2: CloakBrowser launches first, framework connects via CDP (browser-use, Crawl4AI, Scrapling)
from cloakbrowser import launch_async
browser = await launch_async(args=["--remote-debugging-port=9242"])
# Connect your framework to http://127.0.0.1:9242 — all stealth flags are set
# Note: humanize requires the wrapper (see below)
```

> **Humanize over CDP**: Stealth fingerprint patches work automatically over CDP, but `humanize=True` is a wrapper-level feature. If you connect to CloakBrowser via CDP from a separate script, import the patching functions to add humanization:
>
> ```js
> import { patchBrowser, resolveConfig } from 'cloakbrowser/human';
> patchBrowser(browser, resolveConfig('default'));
> ```

| Framework | Stars | Language | Example |
|-----------|-------|----------|---------|
| [browser-use](https://github.com/browser-use/browser-use) | 70K | Python | [`browser_use_example.py`](examples/integrations/browser_use_example.py) |
| [Crawl4AI](https://github.com/unclecode/crawl4ai) | 58K | Python | [`crawl4ai_example.py`](examples/integrations/crawl4ai_example.py) |
| [Crawlee](https://github.com/apify/crawlee-python) | 8.6K | Python | [`crawlee_example.py`](examples/integrations/crawlee_example.py) |
| [Scrapling](https://github.com/D4Vinci/Scrapling) | 21K | Python | [`scrapling_example.py`](examples/integrations/scrapling_example.py) |
| [Stagehand](https://github.com/browserbase/stagehand) | 21K | TypeScript | [`stagehand.ts`](js/examples/stagehand.ts) |
| [LangChain](https://github.com/langchain-ai/langchain) | 100K+ | Python | [`langchain_loader.py`](examples/integrations/langchain_loader.py) |
| [Selenium](https://github.com/SeleniumHQ/selenium) | — | Python | [`selenium_example.py`](examples/integrations/selenium_example.py) |
| [undetected-chromedriver](https://github.com/ultrafunkamsterdam/undetected-chromedriver) | 12K | Python | [`undetected_chromedriver.py`](examples/integrations/undetected_chromedriver.py) |
| [agent-browser](https://github.com/nichochar/agent-browser) | — | Shell | [`agent_browser.sh`](examples/integrations/agent_browser.sh) |

## Platforms

| Platform | Chromium | Patches | Status |
|---|---|---|---|
| Linux x86_64 | 146 | 49 | ✅ Latest |
| Linux arm64 (RPi, Graviton) | 146 | 49 | ✅ Latest |
| macOS arm64 (Apple Silicon) | 145 | 26 | ✅ |
| macOS x86_64 (Intel) | 145 | 26 | ✅ |
| Windows x86_64 | 145 | 48 | ✅ |

The wrapper auto-downloads the correct binary for your platform.

**macOS first launch:** The binary is ad-hoc signed. On first run, macOS Gatekeeper will block it. Right-click the app → **Open** → click **Open** in the dialog. This is only needed once.

## Docker

Pre-built image on Docker Hub — no install, no setup.

### Quick test

```bash
docker run --rm cloakhq/cloakbrowser cloaktest
```

### Run a script

```bash
# Inline script
docker run --rm cloakhq/cloakbrowser python -c "
from cloakbrowser import launch
browser = launch()
page = browser.new_page()
page.goto('https://example.com')
print(page.title())
browser.close()
"

# Mount your own script
docker run --rm -v ./my_script.py:/app/my_script.py cloakhq/cloakbrowser python my_script.py

# With a proxy
docker run --rm cloakhq/cloakbrowser python -c "
from cloakbrowser import launch
browser = launch(proxy='http://user:pass@proxy:8080')
page = browser.new_page()
page.goto('https://example.com')
print(page.title())
browser.close()
"
```

### CDP server mode

Start a persistent stealth browser and connect to it remotely via Chrome DevTools Protocol:

```bash
docker run -d --name cloak -p 127.0.0.1:9222:9222 cloakhq/cloakbrowser cloakserve
```

Then connect from your host machine:

```python
from playwright.sync_api import sync_playwright

pw = sync_playwright().start()
browser = pw.chromium.connect_over_cdp("http://localhost:9222")
page = browser.new_page()
page.goto("https://example.com")
print(page.title())
browser.close()
```

Pass extra flags to the browser:

```bash
# With proxy
docker run -d --name cloak -p 127.0.0.1:9222:9222 cloakhq/cloakbrowser \
  cloakserve --proxy-server=http://proxy:8080

# Headed mode (renders to Xvfb inside container)
docker run -d --name cloak -p 127.0.0.1:9222:9222 cloakhq/cloakbrowser \
  cloakserve --headless=false
```

Stop the server:

```bash
docker stop cloak && docker rm cloak
```

> **Security:** CDP gives full control over the browser (execute JS, read pages, access files).
> The examples bind to `127.0.0.1` so only your machine can connect. Never expose port 9222
> to the public internet without additional authentication.

### Docker Compose

```yaml
services:
  cloakbrowser:
    image: cloakhq/cloakbrowser
    command: cloakserve
    restart: unless-stopped
    ports:
      - "127.0.0.1:9222:9222"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9222/json/version"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

**Per-connection fingerprint seeds** — run multiple browser identities from a single container. Each unique seed spawns a separate Chrome process with its own fingerprint:

```python
# Each seed gets unique canvas noise, client rects, and other browser signals
b1 = pw.chromium.connect_over_cdp("http://localhost:9222?fingerprint=11111")
b2 = pw.chromium.connect_over_cdp("http://localhost:9222?fingerprint=22222")

# Full identity control via query params
b3 = pw.chromium.connect_over_cdp(
    "http://localhost:9222?fingerprint=33333"
    "&timezone=Asia/Tokyo&locale=ja-JP&platform=macos"
    "&hardware-concurrency=4&device-memory=8"
)

# Auto-detect timezone/locale from proxy exit IP
b4 = pw.chromium.connect_over_cdp(
    "http://localhost:9222?fingerprint=44444"
    "&proxy=http://proxy:8080&geoip=true"
)
```

Supported query params: `fingerprint`, `timezone`, `locale`, `platform`, `platform-version`, `brand`, `brand-version`, `gpu-vendor`, `gpu-renderer`, `hardware-concurrency`, `device-memory`, `screen-width`, `screen-height`, `proxy`, `geoip`. Same seed reuses the same process (first connection's params win). No seed = shared default process (backward compatible). Check active processes at `GET /` (returns JSON with PIDs, ports, and connection counts).

**Persistent profiles** — mount a volume to keep cookies and sessions across container restarts:

```bash
docker run --rm -v ./my-profile:/profile cloakhq/cloakbrowser python -c "
from cloakbrowser import launch_persistent_context
ctx = launch_persistent_context('/profile')
page = ctx.new_page()
page.goto('https://example.com')
ctx.close()
"
```

Run again with the same volume — cookies, localStorage, and cache are restored automatically.

**Resource usage:** ~190MB RAM idle, ~280MB with 3 tabs. ~30MB per additional tab.

### Extend with your own image

```dockerfile
FROM cloakhq/cloakbrowser
COPY your_script.py /app/
CMD ["python", "your_script.py"]
```

**Building your own image from pip** — use `python -m cloakbrowser install` to download the binary during build with visible progress:

```dockerfile
FROM python:3.12-slim
RUN pip install cloakbrowser && python -m cloakbrowser install
COPY your_script.py /app/
CMD ["python", "/app/your_script.py"]
```

**Building from source** — a [`Dockerfile`](Dockerfile) is also included if you prefer to build your own image:

```bash
docker build -t cloakbrowser .
```

CloakBrowser works identically local, in Docker, and on VPS. No environment-specific config needed.

**Note:** If you run CloakBrowser inside a web server with uvloop (e.g., `uvicorn[standard]`), use `--loop asyncio` to avoid subprocess pipe hangs.

## Troubleshooting

---

### Still getting blocked on aggressive sites (DataDome, Turnstile)?

Some sites detect headless mode even with our C++ patches. Run in **headed mode** with a virtual display:

```bash
# Install Xvfb (virtual framebuffer)
sudo apt install xvfb

# Start virtual display
Xvfb :99 -screen 0 1920x1080x24 &
export DISPLAY=:99
```

```python
from cloakbrowser import launch

# Headed mode + residential proxy for maximum stealth
browser = launch(headless=False, proxy="http://your-residential-proxy:port")
page = browser.new_page()
page.goto("https://heavily-protected-site.com")  # passes DataDome, etc.
browser.close()
```

This runs a real headed browser rendered on a virtual display — no physical monitor needed. Combine with the recommended config below for maximum stealth.

---

### Recommended config for anti-bot sites

Most blocks come from missing one of these three things, not from browser fingerprint detection:

```python
browser = launch(
    proxy="http://your-residential-proxy:port",  # residential IP — datacenter IPs get blocked by reputation alone
    geoip=True,      # matches timezone + locale to proxy exit IP (without this: UTC + en-US = bot signal)
    headless=False,   # headed mode — some sites detect headless even with C++ patches
    humanize=True,    # human-like mouse, keyboard, scroll behavior
)
```

```javascript
const browser = await launch({
    proxy: 'http://your-residential-proxy:port',
    geoip: true,
    headless: false,
    humanize: true,
});
```

If your proxy supports SOCKS5, use it for better compatibility — SOCKS5 tunnels raw TCP, avoiding HTTP CONNECT issues that some proxies have with HTTP/2:

```python
browser = launch(proxy="socks5://user:pass@proxy:1080", geoip=True, headless=False, humanize=True)
```

If you're still blocked after this, the issue is almost always IP reputation — try a different proxy region or test from a home ISP to confirm the browser itself is clean.

---

### Sites challenge fresh sessions but work after first visit

Some sites challenge first-time visitors with no cookies over HTTP/2. This affects all Chromium browsers, not just CloakBrowser. Use a persistent profile to warm up cookies once, then reuse across sessions:

```python
from cloakbrowser import launch_persistent_context

# First run: warm up with --disable-http2
ctx = launch_persistent_context("./profile", args=["--disable-http2"])
page = ctx.new_page()
page.goto("https://example.com")  # warms up cookies
ctx.close()

# Future runs — no --disable-http2 needed
ctx = launch_persistent_context("./profile")
page = ctx.new_page()
page.goto("https://example.com")  # passes with saved cookies
```

```javascript
import { launchPersistentContext } from 'cloakbrowser';

// First run: warm up with --disable-http2
let ctx = await launchPersistentContext({ userDataDir: './profile', args: ['--disable-http2'] });
let page = await ctx.newPage();
await page.goto('https://example.com');
await ctx.close();

// Future runs — no --disable-http2 needed
ctx = await launchPersistentContext({ userDataDir: './profile' });
```

For stateless/ephemeral use cases, `launch(args=["--disable-http2"])` forces HTTP/1.1 which bypasses the check. Only use this flag for sites that require it — most work fine with HTTP/2. If your proxy supports SOCKS5, use `proxy="socks5://user:pass@host:port"` instead — SOCKS5 bypasses HTTP CONNECT entirely.

---

### Something not working? Make sure you're on the latest version

Older versions may use outdated stealth args or download an older binary:
```bash
pip install -U cloakbrowser    # Python
npm install cloakbrowser@latest # JavaScript
docker pull cloakhq/cloakbrowser:latest  # Docker
```

---

### Binary download fails / timeout

Set a custom download URL or use a local binary:
```bash
export CLOAKBROWSER_BINARY_PATH=/path/to/your/chrome
```

---

### New update broke something? Roll back to the previous version

Install a specific wrapper version to downgrade both the wrapper and the binary it downloads:
```bash
pip install cloakbrowser==0.3.21              # Python
npm install cloakbrowser@0.3.21               # JavaScript
docker pull cloakhq/cloakbrowser:0.3.21       # Docker
```
Each wrapper version pins its own binary version, so downgrading the wrapper automatically gets you the matching binary on next launch.

---

### macOS: "App is damaged" or Gatekeeper blocks launch

The binary is ad-hoc signed. macOS quarantines downloaded files. Run once to clear it:
```bash
xattr -cr ~/.cloakbrowser/chromium-*/Chromium.app
```

---

### "playwright install" vs CloakBrowser binary

You do NOT need `playwright install chromium`. CloakBrowser downloads its own binary. You only need Playwright's system deps:
```bash
playwright install-deps chromium
```

---

### macOS: Blocked on some sites that pass on Linux

The macOS fingerprint profile has known inconsistencies that aggressive bot detection catches. If a site blocks you on macOS but works on Linux, switch to a Windows fingerprint profile by passing `stealth_args=False` and manually setting `--fingerprint-platform=windows` with matching GPU flags (see [Fingerprint Management](#fingerprint-management) for the full flag list).

---

### Site detects incognito / private browsing mode

By default, `launch()` opens an incognito context. Some sites penalize this. Use `launch_persistent_context()` to get a real profile with cookie persistence:

```python
from cloakbrowser import launch_persistent_context

ctx = launch_persistent_context("./my-profile", headless=False)
```

If the site still flags incognito, raise the storage quota to appear as a regular browsing session. See the [storage quota tradeoff](#launch_persistent_context) for details on how this affects different detection services.

---

### reCAPTCHA v3 scores are low (0.1–0.3)

Avoid `page.wait_for_timeout()` — it sends CDP protocol commands that reCAPTCHA detects. Use native sleep instead:

```python
# Bad — sends CDP commands, reCAPTCHA detects this
page.wait_for_timeout(3000)

# Good — invisible to the browser
import time
time.sleep(3)
```

```javascript
// Bad — sends CDP commands
await page.waitForTimeout(3000);

// Good — invisible to the browser
await new Promise(r => setTimeout(r, 3000));
```

Other tips for maximizing reCAPTCHA scores:
- **Try the Patchright backend** — suppresses additional CDP automation signals at the Playwright protocol layer. Install with `pip install cloakbrowser[patchright]`, then use `launch(backend="patchright")` or set `CLOAKBROWSER_BACKEND=patchright` globally. Note: Patchright breaks proxy auth and `add_init_script` — only use it if you're still seeing low scores after trying the steps above
- **Use Playwright, not Puppeteer** — Puppeteer sends more CDP protocol traffic that reCAPTCHA detects ([details](#puppeteer))
- **Use residential proxies** — datacenter IPs are flagged by IP reputation, not browser fingerprint
- **Spend 15+ seconds on the page** before triggering reCAPTCHA — short visits score lower
- **Space out requests** — back-to-back `grecaptcha.execute()` calls from the same session get penalized. Wait 30+ seconds between pages with reCAPTCHA
- **Use a fixed fingerprint seed** for consistent device identity across sessions (see [Fingerprint Management](#fingerprint-management))
- **Use `page.type()` instead of `page.fill()`** for form filling — `fill()` sets values directly without keyboard events, which reCAPTCHA's behavioral analysis flags. `type()` with a delay simulates real keystrokes:
  ```python
  page.type("#email", "user@example.com", delay=50)
  ```
- **Minimize `page.evaluate()` calls** before the reCAPTCHA check fires — each one sends CDP traffic

## FAQ

**Q: Is this legal?**
A: CloakBrowser is a browser built on open-source Chromium. We do not condone illegal use. Automating systems without authorization, credential stuffing, and account creation abuse are expressly prohibited. See [BINARY-LICENSE.md](https://github.com/CloakHQ/CloakBrowser/blob/main/BINARY-LICENSE.md) for full terms.

**Q: How is this different from Camoufox?**
A: Camoufox patches Firefox. We patch Chromium. Chromium means native Playwright support, larger ecosystem, and TLS fingerprints that match real Chrome. Camoufox returned in early 2026 but is in unstable beta — CloakBrowser is production-ready.

**Q: Will detection sites eventually catch this?**
A: Possibly. Bot detection is an arms race. Source-level patches are harder to detect than config-level patches, but not impossible. We actively monitor and update when detection evolves.

**Q: Can I use my own proxy?**
A: Yes. Pass `proxy="http://user:pass@host:port"` or `proxy="socks5://user:pass@host:port"` to `launch()`. Both HTTP and SOCKS5 proxies are supported natively.

## Roadmap

| Feature | Status |
|---------|--------|
| Linux x64 — Chromium 146 (49 patches) | ✅ Released |
| macOS arm64/x64 — Chromium 145 (26 patches) | ✅ Released |
| Windows x64 — Chromium 145 (33 patches) | ✅ Released |
| JavaScript/Puppeteer + Playwright support | ✅ Released |
| Fingerprint rotation per session | ✅ Released |
| Built-in proxy rotation | 📋 Planned |

## Links

- 📋 **Changelog** — [CHANGELOG.md](CHANGELOG.md)
- 🌐 **Website** — [cloakbrowser.dev](https://cloakbrowser.dev)
- 🐛 **Bug reports & feature requests** — [GitHub Issues](https://github.com/CloakHQ/CloakBrowser/issues)
- 📦 **PyPI** — [pypi.org/project/cloakbrowser](https://pypi.org/project/cloakbrowser/)
- 📦 **npm** — [npmjs.com/package/cloakbrowser](https://www.npmjs.com/package/cloakbrowser)
- ☕ **Support** — [ko-fi.com/cloakhq](https://ko-fi.com/cloakhq)
- 📧 **Contact** — cloakhq@pm.me

## Security

All releases are signed for supply chain verification.

```bash
# Verify GPG signature (binary release tag)
gpg --keyserver keyserver.ubuntu.com --recv-keys C60C0DDC9D0DE2DD
git verify-tag chromium-v146.0.7680.177.2

# Verify GitHub binary attestation (Sigstore)
gh attestation verify cloakbrowser-linux-x64.tar.gz --repo CloakHQ/cloakbrowser

# Verify Docker image signature (Cosign/Sigstore)
cosign verify \
  --certificate-identity-regexp "https://github.com/CloakHQ/CloakBrowser/" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  cloakhq/cloakbrowser:latest
```

## License

- **Wrapper code** (this repository) — MIT. See [LICENSE](https://github.com/CloakHQ/CloakBrowser/blob/main/LICENSE).
- **CloakBrowser binary** (compiled Chromium) — free to use, no redistribution. See [BINARY-LICENSE.md](https://github.com/CloakHQ/CloakBrowser/blob/main/BINARY-LICENSE.md).

## Contributing

Issues and PRs welcome. If something isn't working, [open an issue](https://github.com/CloakHQ/CloakBrowser/issues) — we respond fast.

## Contributors

- [@evelaa123](https://github.com/evelaa123) — humanize behavior, persistent contexts, Windows fix
- [@yahooguntu](https://github.com/yahooguntu) — persistent contexts
- [@kitiho](https://github.com/kitiho) — null viewport fix
