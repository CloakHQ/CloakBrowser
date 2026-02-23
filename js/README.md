<p align="center">
<img src="https://raw.githubusercontent.com/CloakHQ/CloakBrowser/main/images/logo.png" width="500" alt="CloakBrowser">
</p>

# CloakBrowser

[![npm](https://img.shields.io/npm/v/cloakbrowser)](https://www.npmjs.com/package/cloakbrowser)
[![License](https://img.shields.io/github/license/CloakHQ/CloakBrowser)](https://github.com/CloakHQ/CloakBrowser/blob/main/LICENSE)

**Stealth Chromium that passes every bot detection test.**

Drop-in Playwright/Puppeteer replacement. Same API — just swap the import. Scores **0.9 on reCAPTCHA v3**, passes **Cloudflare Turnstile**, and clears **14/14** stealth detection tests.

- 🔒 **16 source-level C++ patches** — not JS injection, not config flags
- 🎯 **0.9 reCAPTCHA v3 score** — human-level, server-verified
- ☁️ **Passes Cloudflare Turnstile**, FingerprintJS, BrowserScan — 14/14 tests
- 🔄 **Drop-in replacement** — works with both Playwright and Puppeteer
- 📦 **`npm install cloakbrowser`** — binary auto-downloads, zero config

## Install

```bash
# With Playwright
npm install cloakbrowser playwright-core

# With Puppeteer
npm install cloakbrowser puppeteer-core
```

On first launch, the stealth Chromium binary auto-downloads (~200MB, cached at `~/.cloakbrowser/`).

## Usage

### Playwright (default)

```javascript
import { launch } from 'cloakbrowser';

const browser = await launch();
const page = await browser.newPage();
await page.goto('https://protected-site.com');
console.log(await page.title());
await browser.close();
```

### Puppeteer

```javascript
import { launch } from 'cloakbrowser/puppeteer';

const browser = await launch();
const page = await browser.newPage();
await page.goto('https://protected-site.com');
console.log(await page.title());
await browser.close();
```

### Options

```javascript
import { launch, launchContext } from 'cloakbrowser';

// With proxy
const browser = await launch({
  proxy: 'http://user:pass@proxy:8080',
});

// Headed mode (visible browser window)
const browser = await launch({ headless: false });

// Extra Chrome args
const browser = await launch({
  args: ['--window-size=1920,1080'],
});

// Browser + context in one call
const context = await launchContext({
  userAgent: 'Custom UA',
  viewport: { width: 1920, height: 1080 },
  locale: 'en-US',
  timezoneId: 'America/New_York',
});
```

### Utilities

```javascript
import { ensureBinary, clearCache, binaryInfo } from 'cloakbrowser';

// Pre-download binary (e.g., during Docker build)
await ensureBinary();

// Check installation
console.log(binaryInfo());

// Force re-download
clearCache();
```

## Test Results

| Detection Service | Stock Browser | CloakBrowser |
|---|---|---|
| **reCAPTCHA v3** | 0.1 (bot) | **0.9** (human) |
| **Cloudflare Turnstile** | FAIL | **PASS** |
| **FingerprintJS** | DETECTED | **PASS** |
| **BrowserScan** | DETECTED | **NORMAL** (4/4) |
| **bot.incolumitas.com** | 13 fails | **1 fail** |
| `navigator.webdriver` | `true` | **`false`** |

## Configuration

| Env Variable | Default | Description |
|---|---|---|
| `CLOAKBROWSER_BINARY_PATH` | — | Skip download, use a local Chromium binary |
| `CLOAKBROWSER_CACHE_DIR` | `~/.cloakbrowser` | Binary cache directory |
| `CLOAKBROWSER_DOWNLOAD_URL` | GitHub Releases | Custom download URL |

## Migrate From Playwright

```diff
- import { chromium } from 'playwright';
- const browser = await chromium.launch();
+ import { launch } from 'cloakbrowser';
+ const browser = await launch();

const page = await browser.newPage();
// ... rest of your code works unchanged
```

## Platforms

| Platform | Status |
|---|---|
| Linux x86_64 | ✅ Supported |
| macOS arm64 (Apple Silicon) | Coming soon |
| macOS x86_64 (Intel) | Coming soon |
| Windows | Planned |

## Requirements

- Node.js >= 18
- One of: `playwright-core` >= 1.40 or `puppeteer-core` >= 21

## License

MIT — see [LICENSE](https://github.com/CloakHQ/CloakBrowser/blob/main/LICENSE).

## Links

- [GitHub](https://github.com/CloakHQ/CloakBrowser)
- [PyPI (Python package)](https://pypi.org/project/cloakbrowser/)
- [Full documentation](https://github.com/CloakHQ/CloakBrowser#readme)
