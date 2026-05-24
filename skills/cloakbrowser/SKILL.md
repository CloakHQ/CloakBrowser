---
name: cloakbrowser
description: Use this skill for browser automation on websites protected by anti-bot, anti-scraping, or fingerprinting systems. Trigger this skill when the user needs to scrape protected websites, bypass Cloudflare Turnstile, reCAPTCHA, DataDome, Kasada, or Akamai, perform stealth browsing, manage multiple browser identities, solve captchas, spoof browser fingerprints, or automate interactions on sites that block standard playwright or puppeteer automation. Supports Playwright-compatible browser automation in both Python and Node.js (TypeScript/JavaScript).
allowed-tools: Bash(python:*) Bash(python3:*) Bash(py:*) Bash(npm:*) Bash(npx:*)
---

# Stealth Browser Automation with CloakBrowser

CloakBrowser is a stealth Chromium browser containing 58 C++ patches that modify fingerprints at the source level, making automated sessions indistinguishable from real human Chrome usage. It is fully API-compatible with Playwright and Puppeteer.

## First Step: Ask the User

Before writing any automation scripts, ask the user whether they want **headed** or **headless** mode:
- **Headless** (`headless=True`, default): Runs in the background (no visible window). Faster, lower memory usage. Best for headless servers and background tasks.
- **Headed** (`headless=False`): Opens a real visible browser window. Required for Chrome extensions, debugging, and often recommended to pass the absolute strictest anti-bot systems (e.g. Kasada, DataDome).

Present this as a clear choice, then proceed based on their answer.

## Quick Starts

### Python Quick Start

All Python scripts should be executed with `python` or `python3`.

```python
from cloakbrowser import launch

# Sync mode
browser = launch(headless=True)  # or headless=False
page = browser.new_page()
page.goto("https://example.com")
print(page.title())
page.screenshot(path="screenshot.png")
browser.close()
```

### TypeScript / JavaScript Quick Start

Node.js scripts work natively with standard Playwright runner or ts-node.

```typescript
import { launch } from 'cloakbrowser';

async function main() {
  const browser = await launch({ headless: true });
  const page = await browser.newPage();
  await page.goto('https://example.com');
  console.log(await page.title());
  await page.screenshot({ path: 'screenshot.png' });
  await browser.close();
}
main();
```

## Core Patterns

### Page Interactions (Playwright-compatible API)

Use standard Playwright methods. Ensure you use selector-based page methods for automated humanization:

```python
page.goto("https://example.com")
page.click("#submit-button")
page.fill("#email", "user@example.com")
page.type("#search", "query")            # types character-by-character
page.select_option("#dropdown", "value")
page.hover("#menu-item")
page.press("Enter")

# Locator API (Recommended)
page.locator("#my-element").click()
page.get_by_role("button", name="Submit").click()
```

### Async Operations (Python)

Use async when concurrency (multiple pages, parallel scraping) is needed:

```python
import asyncio
from cloakbrowser import launch_async

async def main():
    browser = await launch_async(headless=True)
    page = await browser.new_page()
    await page.goto("https://example.com")
    print(await page.title())
    await browser.close()

asyncio.run(main())
```

### Wait Strategies

Exposing hard timing signatures can trigger bot detection. Always use native sleep instead of page timeouts:

```python
import time
# GOOD: Python time.sleep does not expose automation characteristics to browser scripts
time.sleep(3) 

# AVOID: page.wait_for_timeout(3000) - can be intercepted by advanced anti-bots
```

## Core Launch Parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| `headless` | `bool` | `True` | Run in headless mode. |
| `backend` | `'playwright' \| 'patchright'` | `'playwright'` | **Critical**: Use `'patchright'` to completely suppress CDP signals (vital for reCAPTCHA v3 Enterprise). Note: Breaks proxy auth and `add_init_script`. |
| `proxy` | `str \| dict` | `None` | Proxy URL string or dict. Supports native inline credentials for HTTP & SOCKS5, bypassing CDP proxies. |
| `geoip` | `bool` | `False` | Auto-detect timezone/locale and spoof WebRTC ICE exit IP based on proxy location. |
| `timezone` | `str` | `None` | Override IANA timezone (e.g. `'America/New_York'`) via binary process flags. |
| `locale` | `str` | `None` | Override locale (e.g. `'en-US'`) via `--lang` and binary flags. |
| `humanize` | `bool` | `False` | Enable human-like mouse paths, keyboard typing timing, and scroll patterns. |
| `human_preset` | `'default' \| 'careful'` | `'default'` | Speed preset for human movements. `'careful'` is slower, with idle pauses. |
| `extension_paths` | `list[str]` | `None` | List of paths to unpacked Chrome extensions to load (requires `headless=False`). |
| `viewport` | `dict \| None` | `{"width": 1280, "height": 720}` | Set viewport size. Set to `None` to disable emulation and use native OS window size. |
| `color_scheme` | `'light' \| 'dark'` | `None` | Force preferred color scheme on the browser context. |

## References & Specialized Guides

* **Anti-Detection Hardening & Patchright** — [references/anti-detection.md](references/anti-detection.md)
* **Fingerprint Determinism & Seeds** — [references/fingerprint-config.md](references/fingerprint-config.md)
* **Human Behavior Simulation Tuning** — [references/humanize.md](references/humanize.md)
* **Persistent Context, Viewports & Extensions** — [references/persistent-context.md](references/persistent-context.md)
* **SOCKS5, HTTP Preemptive Proxies & WebRTC** — [references/proxy-network.md](references/proxy-network.md)
* **Migrating seamlessly from stock Playwright** — [references/playwright-migration.md](references/playwright-migration.md)
