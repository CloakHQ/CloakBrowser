<p align="center">
<img src="https://i.imgur.com/cqkp6fG.png" width="500" alt="CloakBrowser">
</p>

<p align="center">
<a href="https://pypi.org/project/cloakbrowser/"><img src="https://img.shields.io/pypi/v/cloakbrowser" alt="PyPI"></a>
<a href="https://www.npmjs.com/package/cloakbrowser"><img src="https://img.shields.io/npm/v/cloakbrowser" alt="npm"></a>
<a href="LICENSE"><img src="https://img.shields.io/github/license/CloakHQ/CloakBrowser" alt="License"></a>
<a href="https://github.com/CloakHQ/CloakBrowser"><img src="https://img.shields.io/github/last-commit/CloakHQ/CloakBrowser" alt="Last Commit"></a>
<br>
<a href="https://github.com/CloakHQ/CloakBrowser"><img src="https://img.shields.io/github/stars/CloakHQ/CloakBrowser" alt="Stars"></a>
<a href="https://pepy.tech/projects/cloakbrowser"><img src="https://img.shields.io/pepy/dt/cloakbrowser?label=pypi&logo=pypi&logoColor=white" alt="PyPI Downloads"></a>
<a href="https://www.npmjs.com/package/cloakbrowser"><img src="https://img.shields.io/npm/dt/cloakbrowser?label=npm&logo=npm&logoColor=white" alt="npm Downloads"></a>
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

- 🔒 **25 source-level C++ patches** — not JS injection, not config flags
- 🛡️ **CDP stealth built-in** — uses [Patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) to reduce Playwright's automation footprint
- 🎯 **0.9 reCAPTCHA v3 score** — human-level, server-verified
- ☁️ **Passes Cloudflare Turnstile**, FingerprintJS, BrowserScan — 30/30 tests
- 🔄 **Drop-in replacement** — works with Playwright (Python & JS) and Puppeteer (JS)
- 📦 **`pip install cloakbrowser`** or **`npm install cloakbrowser`** — binary auto-downloads, zero config
- 💸 **Enterprise results, zero cost** — anti-detect browsers charge $49–299/month for the same results. CloakBrowser is free

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

## What's New in v0.3.0

- **Chromium 145** — latest stable, 25 fingerprint patches (up from 16). All platforms
- **9 new patches** — screen dimensions, device memory, audio, WebGL, and more
- **SHA-256 checksum verification** — binary downloads are verified for integrity
- **CDP hardening** — audited and patched known automation detection vectors
- **Full stealth audit** — every patch reviewed for detection vectors, multiple fixes shipped
- **Timezone & locale from proxy IP** — `launch(proxy="...", geoip=True)` auto-detects timezone and locale

See the full [CHANGELOG.md](CHANGELOG.md) for details.

## Why CloakBrowser?

- **Config-level patches break** — `playwright-stealth`, `undetected-chromedriver`, and `puppeteer-extra` inject JavaScript or tweak flags. Every Chrome update breaks them. Antibot systems detect the patches themselves.
- **CloakBrowser patches Chromium source code** — fingerprints are modified at the C++ level, compiled into the binary. Detection sites see a real browser because it *is* a real browser.
- **Two layers of stealth** — C++ patches handle fingerprints (GPU, screen, UA, hardware reporting), while the Patchright driver defers Playwright's binding registration and randomizes internal world names. Most stealth tools only do one or the other.
- **Same behavior everywhere** — works identically local, in Docker, and on VPS. No environment-specific patches or config needed.
- **Works with AI browser agents** — drop-in stealth binary for [browser-use](https://github.com/browser-use/browser-use), [agent-browser](https://github.com/nichochar/agent-browser), Claude computer use, and OpenAI Operator
- **One line to switch** — same Playwright API, no new abstractions, no CAPTCHA-solving services.

CloakBrowser doesn't solve CAPTCHAs — it prevents them from appearing. Antibot systems score it as a normal browser because it *is* a normal browser, just with your fingerprints instead of theirs. No CAPTCHA services, no proxy rotation built in — bring your own proxies, use the Playwright API you already know.

## Test Results

All tests verified against live detection services. Last tested: Mar 2026 (Chromium 145).

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
| UA string | `HeadlessChrome` | **`Chrome/145.0.0.0`** | No headless leak |
| CDP detection | Detected | **Not detected** | `isAutomatedWithCDP: false` |
| TLS fingerprint | Mismatch | **Identical to Chrome** | ja3n/ja4/akamai match |
| | | **30/30 passed** | |

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

## How It Works

CloakBrowser is a thin wrapper (Python + JavaScript) around a custom-built Chromium binary:

1. **You install** → `pip install cloakbrowser` or `npm install cloakbrowser`
2. **First launch** → binary auto-downloads for your platform (Chromium 145)
3. **Every launch** → Playwright or Puppeteer starts with our binary + stealth args
4. **You write code** → standard Playwright/Puppeteer API, nothing new to learn

The binary includes 25 source-level patches covering canvas, WebGL, audio, fonts, GPU, screen properties, hardware reporting, and automation signal removal.

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

# With proxy
browser = launch(proxy="http://user:pass@proxy:8080")

# With extra Chrome args
browser = launch(args=["--disable-gpu", "--window-size=1920,1080"])

# With timezone and locale (sets both binary flags and Playwright context)
browser = launch(timezone="America/New_York", locale="en-US")

# Auto-detect timezone/locale from proxy IP (requires: pip install cloakbrowser[geoip])
browser = launch(proxy="http://proxy:8080", geoip=True)

# Explicit timezone/locale always win over auto-detection
browser = launch(proxy="http://proxy:8080", geoip=True, timezone="Europe/London")

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

Convenience function that creates browser + context with common options:

```python
from cloakbrowser import launch_context

context = launch_context(
    user_agent="Custom UA",
    viewport={"width": 1920, "height": 1080},
    locale="en-US",
    timezone_id="America/New_York",
)
page = context.new_page()
```

### Utility Functions

```python
from cloakbrowser import binary_info, clear_cache, ensure_binary

# Check binary installation status
print(binary_info())
# {'version': '145.0.7632.109', 'platform': 'linux-x64', 'installed': True, ...}

# Force re-download
clear_cache()

# Pre-download binary (e.g., during Docker build)
ensure_binary()
```

## JavaScript / Node.js API

CloakBrowser ships a TypeScript package with full type definitions. Choose Playwright or Puppeteer — same stealth binary underneath.

### Playwright (default)

```javascript
import { launch, launchContext } from 'cloakbrowser';

// Basic
const browser = await launch();

// With options
const browser = await launch({
  headless: false,
  proxy: 'http://user:pass@proxy:8080',
  args: ['--window-size=1920,1080'],
  timezone: 'America/New_York',
  locale: 'en-US',
});

// Convenience: browser + context in one call
const context = await launchContext({
  userAgent: 'Custom UA',
  viewport: { width: 1920, height: 1080 },
  locale: 'en-US',
  timezoneId: 'America/New_York',
});
const page = await context.newPage();
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

The binary detects its platform at compile time — a macOS binary reports Apple GPU and macOS screen (1440x900), a Linux binary reports NVIDIA GPU and 1080p screen. Override with `--fingerprint-platform` for cross-platform spoofing (e.g. Linux binary appearing as Windows).

> **Tip: Use a fixed seed when revisiting the same site.** A random seed makes every session look like a different device — which can be suspicious when hitting the same site repeatedly from the same IP. For reCAPTCHA v3 Enterprise and similar scoring systems, a fixed seed produces a consistent fingerprint across sessions, making you look like a returning visitor:
> ```python
> browser = launch(args=["--fingerprint=12345"])
> ```
> ```javascript
> const browser = await launch({ args: ['--fingerprint=12345'] });
> ```

### Default Fingerprint

Every `launch()` call sets these automatically. Defaults are **platform-aware** — macOS runs as a native Mac browser, Linux and Windows use the Windows fingerprint profile:

| Flag | Linux/Windows Default | macOS Default | Controls |
|------|--------------|---------------|----------|
| `--fingerprint` | Random (10000–99999) | Random (10000–99999) | Master seed for canvas, WebGL, audio, fonts, client rects |
| `--fingerprint-platform` | `windows` | `macos` | `navigator.platform`, User-Agent OS, GPU pool selection |
| `--fingerprint-hardware-concurrency` | `8` | *(not set — uses real value)* | `navigator.hardwareConcurrency` |
| `--fingerprint-gpu-vendor` | `NVIDIA Corporation` | `Google Inc. (Apple)` | WebGL `UNMASKED_VENDOR_WEBGL` |
| `--fingerprint-gpu-renderer` | `NVIDIA GeForce RTX 3070` | `ANGLE (Apple, ANGLE Metal Renderer: Apple M3, Unspecified Version)` | WebGL `UNMASKED_RENDERER_WEBGL` |
| `--fingerprint-device-memory` | `8` | *(not set)* | `navigator.deviceMemory` |
| `--fingerprint-screen-width` | `1920` | *(not set)* | Screen width reporting |
| `--fingerprint-screen-height` | `1080` | *(not set)* | Screen height reporting |
| `--window-size` | `1920,1080` | *(not set)* | Browser window dimensions |

> **Using the binary directly?** It works out of the box with zero flags — the binary auto-spoofs everything. Pass `--fingerprint=seed` for a persistent identity, or use explicit flags like `--fingerprint-gpu-renderer` to override any auto-generated value.

> **Production tip:** For better stealth at scale, pass your own GPU, screen, and hardware values instead of relying on defaults. Custom parameters make your sessions harder to cluster by anti-bot systems that look for uniform fingerprint profiles.

### Additional Flags

Supported by the binary but **not set by default** — pass via `args` to customize:

| Flag | Controls |
|------|----------|
| `--fingerprint-brand` | Browser brand: `Chrome`, `Edge`, `Opera`, `Vivaldi` |
| `--fingerprint-brand-version` | Brand version (UA + Client Hints) |
| `--fingerprint-platform-version` | Client Hints platform version |
| `--fingerprint-location` | Geolocation coordinates |
| `--fingerprint-timezone` | Timezone (e.g. `America/New_York`) |
| `--fingerprint-taskbar-height` | Override taskbar height (binary defaults: Win=48, Mac=95, Linux=0) |
| `--fingerprint-fonts-dir` | Path to cross-platform font directory |
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
    "--fingerprint-hardware-concurrency=8",
    "--fingerprint-gpu-vendor=NVIDIA Corporation",
    "--fingerprint-gpu-renderer=NVIDIA GeForce RTX 3070",
])

# Override GPU to look like a different machine
browser = launch(args=[
    "--fingerprint-gpu-vendor=Intel Inc.",
    "--fingerprint-gpu-renderer=Intel Iris OpenGL Engine",
])
```

## Comparison

| Feature | Playwright | playwright-stealth | undetected-chromedriver | Camoufox | CloakBrowser |
|---|---|---|---|---|---|
| reCAPTCHA v3 score | 0.1 | 0.3-0.5 | 0.3-0.7 | 0.7-0.9 | **0.9** |
| Cloudflare Turnstile | Fail | Sometimes | Sometimes | Pass | **Pass** |
| Patch level | None | JS injection | Config patches | C++ (Firefox) | **C++ (Chromium)** |
| Survives Chrome updates | N/A | Breaks often | Breaks often | Yes | **Yes** |
| Maintained | Yes | Stale | Stale | Unstable (2026 beta) | **Active** |
| Browser engine | Chromium | Chromium | Chrome | Firefox | **Chromium** |
| Playwright API | Native | Native | No (Selenium) | No | **Native** |

## Platforms

| Platform | Chromium | Patches | Status |
|---|---|---|---|
| Linux x86_64 | 145 | 25 | ✅ Latest |
| macOS arm64 (Apple Silicon) | 145 | 25 | ✅ Latest |
| macOS x86_64 (Intel) | 145 | 25 | ✅ Latest |
| Windows x86_64 | 145 | 25 | ✅ Latest |

The wrapper auto-downloads the correct binary for your platform.

**macOS first launch:** The binary is ad-hoc signed. On first run, macOS Gatekeeper will block it. Right-click the app → **Open** → click **Open** in the dialog. This is only needed once.

## Examples

**Python** — see [`examples/`](examples/):
- [`basic.py`](examples/basic.py) — Launch and load a page
- [`recaptcha_score.py`](examples/recaptcha_score.py) — Check your reCAPTCHA v3 score
- [`stealth_test.py`](examples/stealth_test.py) — Run against all detection services
- [`fingerprint_scan_test.py`](examples/fingerprint_scan_test.py) — Test against fingerprint-scan.com and CreepJS

**JavaScript** — see [`js/examples/`](js/examples/):
- [`basic-playwright.ts`](js/examples/basic-playwright.ts) — Playwright launch and load
- [`basic-puppeteer.ts`](js/examples/basic-puppeteer.ts) — Puppeteer launch and load
- [`stealth-test.ts`](js/examples/stealth-test.ts) — Full 6-site detection test suite

## Roadmap

| Feature | Status |
|---------|--------|
| Linux x64 — Chromium 145 (25 patches) | ✅ Released |
| macOS arm64/x64 — Chromium 145 (25 patches) | ✅ Released |
| Windows x64 — Chromium 145 (25 patches) | ✅ Released |
| JavaScript/Puppeteer + Playwright support | ✅ Released |
| Fingerprint rotation per session | ✅ Released |
| Built-in proxy rotation | 📋 Planned |

## Docker

A ready-to-use [`Dockerfile`](Dockerfile) is included. It installs system deps, the package, and pre-downloads the stealth binary during build:

```bash
docker build -t cloakbrowser .
docker run --rm cloakbrowser python examples/basic.py
```

The key steps in the Dockerfile:
1. **System deps** — Chromium requires ~15 shared libraries (`libnss3`, `libgbm1`, etc.)
2. **`pip install .`** — installs CloakBrowser + Playwright
3. **`ensure_binary()`** — downloads the stealth Chromium binary at build time (~200MB), so containers start instantly

To extend with your own script, just add a `COPY` + `CMD`:

```dockerfile
FROM cloakbrowser
COPY your_script.py /app/
CMD ["python", "your_script.py"]
```

**With a proxy** (the most common production setup):

```bash
docker run --rm cloakbrowser python -c "
from cloakbrowser import launch
browser = launch(proxy='http://user:pass@proxy:8080')
page = browser.new_page()
page.goto('https://example.com')
print(page.title())
browser.close()
"
```

CloakBrowser works identically local, in Docker, and on VPS. No environment-specific config needed.

**Note:** If you run CloakBrowser inside a web server with uvloop (e.g., `uvicorn[standard]`), use `--loop asyncio` to avoid subprocess pipe hangs.

## Headed Mode (for aggressive bot detection)

Some sites using advanced bot detection (e.g., DataDome, Cloudflare Turnstile) can detect headless mode even with our C++ patches. For these sites, run in **headed mode** with a virtual display:

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

This runs a real headed browser rendered on a virtual display — no physical monitor needed. Combined with a residential proxy, this passes even the most aggressive detection services.

> **Tip:** Datacenter IPs are often flagged by IP reputation databases regardless of browser fingerprint. For sites with strict bot detection, a residential proxy makes the difference.

## Troubleshooting

**Reddit or similar sites show CAPTCHA / "Prove your humanity"**

Some sites (notably Reddit homepage) use HTTP/2 fingerprinting that detects Playwright's connection layer. Pass `--disable-http2` to fall back to HTTP/1.1:

```python
browser = launch(args=["--disable-http2"])
```

```javascript
const browser = await launch({ args: ['--disable-http2'] });
```

Only use this flag for sites that require it — most sites work fine with HTTP/2.

**Something not working? Make sure you're on the latest wrapper**
Older versions may use outdated stealth args or download an older binary:
```bash
pip install -U cloakbrowser    # Python
npm install cloakbrowser@latest # JavaScript
```

**Binary download fails / timeout**
Set a custom download URL or use a local binary:
```bash
export CLOAKBROWSER_BINARY_PATH=/path/to/your/chrome
```

**macOS: "App is damaged" or Gatekeeper blocks launch**
The binary is ad-hoc signed. macOS quarantines downloaded files. Run once to clear it:
```bash
xattr -cr ~/.cloakbrowser/chromium-*/Chromium.app
```

**"playwright install" vs CloakBrowser binary**
You do NOT need `playwright install chromium`. CloakBrowser downloads its own binary. You only need Playwright's system deps:
```bash
patchright install-deps chromium
```

**reCAPTCHA v3 scores are low (0.1–0.3)**

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
A: CloakBrowser is a browser. Using it is legal. What you do with it is your responsibility, just like with Chrome, Firefox, or any browser. We do not endorse violating website terms of service.

**Q: How is this different from Camoufox?**
A: Camoufox patches Firefox. We patch Chromium. Chromium means native Playwright support, larger ecosystem, and TLS fingerprints that match real Chrome. Camoufox returned in early 2026 but is in unstable beta — CloakBrowser is production-ready.

**Q: Will detection sites eventually catch this?**
A: Possibly. Bot detection is an arms race. Source-level patches are harder to detect than config-level patches, but not impossible. We actively monitor and update when detection evolves.

**Q: Can I use my own proxy?**
A: Yes. Pass `proxy="http://user:pass@host:port"` to `launch()`.

## Links

- 📋 **Changelog** — [CHANGELOG.md](CHANGELOG.md)
- 🌐 **Website** — [cloakbrowser.dev](https://cloakbrowser.dev)
- 🐛 **Bug reports & feature requests** — [GitHub Issues](https://github.com/CloakHQ/CloakBrowser/issues)
- 📦 **PyPI** — [pypi.org/project/cloakbrowser](https://pypi.org/project/cloakbrowser/)
- 📦 **npm** — [npmjs.com/package/cloakbrowser](https://www.npmjs.com/package/cloakbrowser)
- 📧 **Contact** — cloakhq@pm.me

## License

- **Wrapper code** (this repository) — MIT. See [LICENSE](https://github.com/CloakHQ/CloakBrowser/blob/main/LICENSE).
- **CloakBrowser binary** (compiled Chromium) — free to use, no redistribution. See [BINARY-LICENSE.md](https://github.com/CloakHQ/CloakBrowser/blob/main/BINARY-LICENSE.md).

## Contributing

Issues and PRs welcome. If something isn't working, [open an issue](https://github.com/CloakHQ/CloakBrowser/issues) — we respond fast.
