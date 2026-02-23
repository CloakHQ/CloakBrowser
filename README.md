<p align="center">
<img src="https://raw.githubusercontent.com/CloakHQ/CloakBrowser/main/images/logo.png" width="500" alt="CloakBrowser">
</p>

# CloakBrowser

[![PyPI](https://img.shields.io/pypi/v/cloakbrowser)](https://pypi.org/project/cloakbrowser/)
[![Python](https://img.shields.io/pypi/pyversions/cloakbrowser)](https://pypi.org/project/cloakbrowser/)
[![License](https://img.shields.io/github/license/CloakHQ/CloakBrowser)](LICENSE)
[![Stars](https://img.shields.io/github/stars/CloakHQ/CloakBrowser)](https://github.com/CloakHQ/CloakBrowser)
[![Last Commit](https://img.shields.io/github/last-commit/CloakHQ/CloakBrowser)](https://github.com/CloakHQ/CloakBrowser)

**Stealth Chromium that passes every bot detection test.**

Drop-in Playwright replacement. Same API, same code — just swap the import. Your browser now scores **0.9 on reCAPTCHA v3**, passes **Cloudflare Turnstile**, and clears **14 out of 14** stealth detection tests.

- 🔒 **16 source-level C++ patches** — not JS injection, not config flags
- 🎯 **0.9 reCAPTCHA v3 score** — human-level, server-verified
- ☁️ **Passes Cloudflare Turnstile**, FingerprintJS, BrowserScan — 14/14 tests
- 🔄 **Drop-in Playwright replacement** — same API, swap one import
- 📦 **`pip install cloakbrowser`** — binary auto-downloads, zero config
- 🦊 **Fills the Camoufox vacuum** — Chromium-based, actively maintained

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

- **Config-level patches break** — `playwright-stealth`, `undetected-chromedriver`, and `puppeteer-extra` inject JavaScript or tweak flags. Every Chrome update breaks them. Antibot systems detect the patches themselves.
- **CloakBrowser patches Chromium source code** — fingerprints are modified at the C++ level, compiled into the binary. Detection sites see a real browser because it *is* a real browser.
- **One line to switch** — same Playwright API, no new abstractions, no CAPTCHA-solving services.

## Test Results

All tests verified against live detection services. Last tested: Feb 2026 (Chromium 142).

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
| UA string | `HeadlessChrome` | **`Chrome/142.0.0.0`** | No headless leak |
| CDP detection | Detected | **Not detected** | `isAutomatedWithCDP: false` |
| TLS fingerprint | Mismatch | **Identical to Chrome** | ja3n/ja4/akamai match |

**14/14 tests passed.**

### Proof

<p align="center">
<img src="https://raw.githubusercontent.com/CloakHQ/CloakBrowser/main/images/recaptcha_v3_score_09.png" width="600" alt="reCAPTCHA v3 — Score 0.9">
<br><em>reCAPTCHA v3 score 0.9 — server-side verified (human-level)</em>
</p>

<p align="center">
<img src="https://raw.githubusercontent.com/CloakHQ/CloakBrowser/main/images/turnstile_non_interactive.png" width="600" alt="Cloudflare Turnstile — Success">
<br><em>Cloudflare Turnstile non-interactive challenge — auto-resolved</em>
</p>

<p align="center">
<img src="https://raw.githubusercontent.com/CloakHQ/CloakBrowser/main/images/browserscan_normal.png" width="600" alt="BrowserScan — Normal">
<br><em>BrowserScan bot detection — NORMAL (4/4 checks passed)</em>
</p>

<p align="center">
<img src="https://raw.githubusercontent.com/CloakHQ/CloakBrowser/main/images/fingerprintjs_pass.png" width="600" alt="FingerprintJS — Passed">
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
# {'version': '142.0.7444.175', 'platform': 'linux-x64', 'installed': True, ...}

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

## Roadmap

| Feature | Status |
|---------|--------|
| Linux x64 binary | ✅ Released |
| macOS arm64 (Apple Silicon) | 🔜 In progress |
| Chromium 145 build | 🔜 In progress |
| Fingerprint rotation per session | 📋 Planned |
| Built-in proxy rotation | 📋 Planned |
| Windows support | 📋 Planned |

> ⭐ **Star this repo** to get notified when Chromium 145 and macOS builds drop.

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

**Note:** If you run CloakBrowser inside a web server with uvloop (e.g., `uvicorn[standard]`), use `--loop asyncio` to avoid subprocess pipe hangs.

## Troubleshooting

**Binary download fails / timeout**
Set a custom download URL or use a local binary:
```bash
export CLOAKBROWSER_BINARY_PATH=/path/to/your/chrome
```

**"playwright install" vs CloakBrowser binary**
You do NOT need `playwright install chromium`. CloakBrowser downloads its own binary. You only need Playwright's system deps:
```bash
playwright install-deps chromium
```

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
A: Yes. A ready-to-use Dockerfile is included — see the [Docker](#docker) section above.

## License

MIT — see [LICENSE](LICENSE).

## Contributing

Issues and PRs welcome. Contact: cloakhq@pm.me
