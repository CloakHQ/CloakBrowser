# Migrating from Stock Playwright & Puppeteer

CloakBrowser is fully API-compatible with Playwright (Python and JS/TS) and Puppeteer (JS/TS). Migration is a drop-in replacement — you only swap the launch import, leaving all selector-based navigation and page interaction code untouched.

---

## 1. Python Migration

### Synchronous Mode

```python
# ===== BEFORE: Stock Playwright =====
from playwright.sync_api import sync_playwright
pw = sync_playwright().start()
browser = pw.chromium.launch()
page = browser.new_page()

# ===== AFTER: CloakBrowser =====
from cloakbrowser import launch
browser = launch()  # Done! All stealth and patches active
page = browser.new_page()
```

### Asynchronous Mode

```python
# ===== BEFORE: Stock Playwright Async =====
from playwright.async_api import async_playwright
pw = await async_playwright().start()
browser = await pw.chromium.launch()
page = await browser.new_page()

# ===== AFTER: CloakBrowser Async =====
from cloakbrowser import launch_async
browser = await launch_async()  # Done!
page = await browser.new_page()
```

---

## 2. Node.js (JavaScript / TypeScript) Migration

### Playwright Wrapper

```typescript
// ===== BEFORE: Stock Playwright JS =====
import { chromium } from 'playwright';
const browser = await chromium.launch();
const page = await browser.newPage();

// ===== AFTER: CloakBrowser JS =====
import { launch } from 'cloakbrowser';
const browser = await launch();  // Done! Uses the stealth binary
const page = await browser.newPage();
```

### Puppeteer Wrapper

```typescript
// ===== BEFORE: Stock Puppeteer JS =====
import puppeteer from 'puppeteer';
const browser = await puppeteer.launch();
const page = await browser.newPage();

// ===== AFTER: CloakBrowser Puppeteer =====
import { launch } from 'cloakbrowser/puppeteer';
const browser = await launch();  // Done!
const page = await browser.newPage();
```

---

## 3. What You Gain: Under-the-Hood Stealth Comparison

| Fingerprint Metric | Stock Playwright | CloakBrowser | Evasion Method |
|---|---|---|---|
| `navigator.webdriver` | `true` | `false` | C++ binary source patch |
| `navigator.plugins` | Empty list (`0`) | 5 default plugins | C++ binary source patch |
| `window.chrome` | `undefined` | Present (standard object) | C++ binary source patch |
| **User-Agent String** | Leaks `"HeadlessChrome"` | Normal `"Chrome/146..."` | C++ binary source patch |
| **Canvas & WebGL** | Identical signature (bot flag) | Normal, unique noise | C++ binary source patch |
| **TLS Signature** | standard Node/python signature | Matches real Chrome (JA3/JA4) | C++ binary source patch |
| **Mouse / Keyboard** | Teleports instantly (0ms) | Bézier aiming, typo corrections | `humanize=True` wrapper |
| **Proxy Authentication** | Trigger 407 (CDP Interceptor) | Preemptive inline auth | Custom launcher proxy flags |

---

## 4. API Compatibility Verification

All standard browser context and page interaction hooks operate exactly as expected:
- `page.goto()`, `page.click()`, `page.fill()`, `page.type()`
- `page.locator()`, `page.get_by_role()`, `page.get_by_text()`
- `page.screenshot()`, `page.pdf()`, `page.content()`
- `page.wait_for_selector()`, `page.wait_for_load_state()`
- `page.keyboard`, `page.mouse`
- `BrowserContext`, `context.storage_state()`, `context.cookies()`
- `page.on("dialog", ...)`, `page.on("download", ...)`
- `page.expect_download()`, `page.expect_popup()`, `page.expect_navigation()`
