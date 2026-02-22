# CloakBrowser

[![PyPI](https://img.shields.io/pypi/v/cloakbrowser)](https://pypi.org/project/cloakbrowser/)
[![Python](https://img.shields.io/pypi/pyversions/cloakbrowser)](https://pypi.org/project/cloakbrowser/)
[![License](https://img.shields.io/github/license/CloakHQ/CloakBrowser)](LICENSE)

**Stealth Chromium that passes every bot detection test.**

Drop-in Playwright replacement. Same API, same code — just swap the import. Your browser now scores **0.9 on reCAPTCHA v3**, passes **Cloudflare Turnstile**, and clears **14 out of 14** stealth detection tests.

> CloakBrowser is an open-source Python library that gives you an undetectable browser for web automation and data collection. It wraps a custom-built Chromium binary with 16 source-level fingerprint patches — modifications compiled directly into the browser's C++ code, not bolted on via JavaScript injection or config flags.
>
> Most stealth tools (playwright-stealth, undetected-chromedriver, puppeteer-extra) work at the config level: they override JavaScript properties, set browser flags, or inject scripts to mask automation signals. These approaches break every time Chrome updates its detection surface — and Cloudflare, reCAPTCHA, and other bot detection systems update constantly.
>
> CloakBrowser takes a fundamentally different approach. The fingerprint patches modify Chromium's rendering pipeline at the source level: canvas output, WebGL renderer strings, audio processing fingerprints, font enumeration, hardware concurrency, client rectangles, GPU info, timezone handling, and the WebDriver flag are all patched in C++ before compilation. The resulting binary produces fingerprints indistinguishable from a real user's Chrome installation. TLS fingerprints (ja3n, ja4, akamai hash) match genuine Chrome exactly because the browser IS Chrome — just with different fingerprint values compiled in.
>
> The result: a 0.9 score on Google's reCAPTCHA v3 (human-level, versus 0.1 for stock Playwright), clean passes on Cloudflare Turnstile managed challenges, zero bot flags on FingerprintJS, BrowserScan, and deviceandbrowserinfo.com, and undetected CDP (Chrome DevTools Protocol) usage. 14 out of 14 major detection tests passed.
>
> CloakBrowser fills the vacuum left by Camoufox (the popular Firefox-based stealth browser whose maintainer stepped down in 2025). Unlike Camoufox, CloakBrowser is Chromium-based — meaning native Playwright API support, a massive ecosystem of existing tools and scripts, and TLS fingerprints that match the browser 65%+ of the internet actually uses.
>
> Install with pip, write standard Playwright code, and let the binary handle the stealth. No new API to learn. No configuration to tune. No CAPTCHA-solving services to pay for. Just a browser that works on sites where others get blocked.

```python
from cloakbrowser import launch

browser = launch()
page = browser.new_page()
page.goto("https://protected-site.com")  # no more blocks
browser.close()
```

## Install

```bash
pip install cloakbrowser
```

On first run, the stealth Chromium binary is automatically downloaded (~200MB, cached locally).

## Why CloakBrowser?

Every bot detection system — reCAPTCHA, Cloudflare Turnstile, ShieldSquare, FingerprintJS — identifies automation browsers through **browser fingerprinting**: canvas rendering, WebGL output, audio processing, font enumeration, and dozens of other signals.

Tools like `playwright-stealth` or `undetected-chromedriver` try to fix this with **config-level patches** — JavaScript overrides, flag tweaks, UA spoofing. These work until the next Chrome update breaks them.

CloakBrowser patches **Chromium source code** — the fingerprint signals are modified at the C++ level, compiled into the binary. Detection sites see a real browser because, at the binary level, it *is* a real browser with different fingerprint values.

## Test Results

All tests verified against live detection services. Last tested: Feb 2026 (Chromium 145).

| Detection Service | Stock Playwright | CloakBrowser | Notes |
|---|---|---|---|
| **reCAPTCHA v3** | 0.1 (bot) | **0.9** (human) | Server-side verified |
| **Cloudflare Turnstile** (non-interactive) | FAIL | **PASS** | Auto-resolve |
| **Cloudflare Turnstile** (managed) | FAIL | **PASS** | Single click |
| **ShieldSquare** (yad2.co.il) | BLOCKED | **PASS** | Production site |
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

**14/14 tests passed.**

### Proof

<p align="center">
<img src="images/recaptcha_v3_score_09.png" width="600" alt="reCAPTCHA v3 — Score 0.9">
<br><em>reCAPTCHA v3 score 0.9 — server-side verified (human-level)</em>
</p>

<p align="center">
<img src="images/turnstile_non_interactive.png" width="600" alt="Cloudflare Turnstile — Success">
<br><em>Cloudflare Turnstile non-interactive challenge — auto-resolved</em>
</p>

<p align="center">
<img src="images/browserscan_normal.png" width="600" alt="BrowserScan — Normal">
<br><em>BrowserScan bot detection — NORMAL (4/4 checks passed)</em>
</p>

<p align="center">
<img src="images/fingerprintjs_pass.png" width="600" alt="FingerprintJS — Passed">
<br><em>FingerprintJS web-scraping demo — data served, not blocked</em>
</p>

## How It Works

CloakBrowser is a thin Python wrapper around a custom-built Chromium binary:

1. **You install** → `pip install cloakbrowser`
2. **First launch** → binary auto-downloads for your platform (Linux x64 / macOS arm64)
3. **Every launch** → Playwright starts with our binary + stealth args
4. **You write code** → standard Playwright API, nothing new to learn

The binary includes 16 source-level patches that modify:
- Canvas fingerprint generation
- WebGL renderer output
- Audio processing fingerprint
- Font enumeration results
- Hardware concurrency reporting
- Client rect measurements
- GPU vendor/renderer strings
- WebDriver flag
- Headless detection signals
- And more...

These are compiled into the Chromium binary — not injected via JavaScript, not set via flags.

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
# {'version': '145.0.7723.116', 'platform': 'darwin-arm64', 'installed': True, ...}

# Force re-download
clear_cache()

# Pre-download binary (e.g., during Docker build)
ensure_binary()
```

## Configuration

| Env Variable | Default | Description |
|---|---|---|
| `CLOAKBROWSER_BINARY_PATH` | — | Skip download, use a local Chromium binary |
| `CLOAKBROWSER_CACHE_DIR` | `~/.cloakbrowser` | Binary cache directory |
| `CLOAKBROWSER_DOWNLOAD_URL` | GitHub Releases | Custom download URL for binary |

## Use With Existing Playwright Code

If you have existing Playwright scripts, migration is one line:

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

## Comparison

| Feature | Playwright | playwright-stealth | undetected-chromedriver | Camoufox | CloakBrowser |
|---|---|---|---|---|---|
| reCAPTCHA v3 score | 0.1 | 0.3-0.5 | 0.3-0.7 | 0.7-0.9 | **0.9** |
| Cloudflare Turnstile | Fail | Sometimes | Sometimes | Pass | **Pass** |
| Patch level | None | JS injection | Config patches | C++ (Firefox) | **C++ (Chromium)** |
| Survives Chrome updates | N/A | Breaks often | Breaks often | Yes | **Yes** |
| Maintained | Yes | Stale | Stale | Dead (2025) | **Active** |
| Browser engine | Chromium | Chromium | Chrome | Firefox | **Chromium** |
| Playwright API | Native | Native | No (Selenium) | No | **Native** |

## Platforms

| Platform | Status |
|---|---|
| Linux x86_64 | Supported |
| macOS arm64 (Apple Silicon) | Coming soon |
| macOS x86_64 (Intel) | Coming soon |
| Windows | Planned |

## Examples

See the [`examples/`](examples/) directory:
- [`basic.py`](examples/basic.py) — Launch and load a page
- [`recaptcha_score.py`](examples/recaptcha_score.py) — Check your reCAPTCHA v3 score
- [`stealth_test.py`](examples/stealth_test.py) — Run against all detection services

## FAQ

**Q: Is this legal?**
A: CloakBrowser is a browser. Using it is legal. What you do with it is your responsibility, just like with Chrome, Firefox, or any browser. We do not endorse violating website terms of service.

**Q: How is this different from Camoufox?**
A: Camoufox patched Firefox. We patch Chromium. Chromium means native Playwright support, larger ecosystem, and TLS fingerprints that match real Chrome. Also, Camoufox is no longer maintained (since March 2025).

**Q: Will detection sites eventually catch this?**
A: Possibly. Bot detection is an arms race. Source-level patches are harder to detect than config-level patches, but not impossible. We actively monitor and update when detection evolves.

**Q: Can I use my own proxy?**
A: Yes. Pass `proxy="http://user:pass@host:port"` to `launch()`.

**Q: Can I use this with Docker?**
A: Yes. Use `ensure_binary()` in your Dockerfile to pre-download the binary during image build.

## License

MIT — see [LICENSE](LICENSE).

## Contributing

Issues and PRs welcome. Contact: cloakhq@pm.me
