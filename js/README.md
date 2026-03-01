<p align="center">
<img src="https://i.imgur.com/cqkp6fG.png" width="500" alt="CloakBrowser">
</p>

# CloakBrowser

[![npm](https://img.shields.io/npm/v/cloakbrowser)](https://www.npmjs.com/package/cloakbrowser)
[![License](https://img.shields.io/github/license/CloakHQ/CloakBrowser)](https://github.com/CloakHQ/CloakBrowser/blob/main/LICENSE)

**Stealth Chromium that passes every bot detection test.**

Drop-in Playwright/Puppeteer replacement. Same API — just swap the import. Scores **0.9 on reCAPTCHA v3**, passes **Cloudflare Turnstile**, and clears **30/30** stealth detection tests.

- 🔒 **16 source-level C++ patches** — not JS injection, not config flags
- 🎯 **0.9 reCAPTCHA v3 score** — human-level, server-verified
- ☁️ **Passes Cloudflare Turnstile**, FingerprintJS, BrowserScan — 30/30 tests
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

> **Note:** Playwright is recommended for sites with reCAPTCHA Enterprise. Puppeteer's CDP protocol leaks automation signals that reCAPTCHA Enterprise can detect. This is a known Puppeteer limitation, not specific to CloakBrowser.

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

// With timezone and locale (sets --timezone and --lang binary flags)
const browser = await launch({
  timezone: 'America/New_York',
  locale: 'en-US',
});

// Auto-detect timezone/locale from proxy IP (requires: npm install mmdb-lib)
const browser = await launch({
  proxy: 'http://proxy:8080',
  geoip: true,
});

// Browser + context in one call (timezone/locale set both binary flags AND context)
const context = await launchContext({
  userAgent: 'Custom UA',
  viewport: { width: 1920, height: 1080 },
  locale: 'en-US',
  timezoneId: 'America/New_York',
});
```

### Auto Timezone/Locale from Proxy IP

When using a proxy, antibot systems check that your browser's timezone and locale match the proxy's location. Install `mmdb-lib` to enable auto-detection from an offline GeoIP database (~70 MB, downloaded on first use):

```bash
npm install mmdb-lib
```

```javascript
// Auto-detect — timezone and locale set from proxy's IP geolocation
const browser = await launch({ proxy: 'http://proxy:8080', geoip: true });

// Works with launchContext too
const context = await launchContext({ proxy: 'http://proxy:8080', geoip: true });

// Explicit values always win over auto-detection
const browser = await launch({ proxy: 'http://proxy:8080', geoip: true, timezone: 'Europe/London' });
```

> **Note:** For rotating residential proxies, the DNS-resolved IP may differ from the exit IP. Pass explicit `timezone`/`locale` in those cases.

### Utilities

```javascript
import { ensureBinary, clearCache, binaryInfo, checkForUpdate } from 'cloakbrowser';

// Pre-download binary (e.g., during Docker build)
await ensureBinary();

// Check installation
console.log(binaryInfo());

// Force re-download
clearCache();

// Manually check for newer Chromium version
const newVersion = await checkForUpdate();
if (newVersion) console.log(`Updated to ${newVersion}`);
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
| `CLOAKBROWSER_DOWNLOAD_URL` | `cloakbrowser.dev` | Custom download URL |
| `CLOAKBROWSER_AUTO_UPDATE` | `true` | Set to `false` to disable background update checks |

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
| Linux x86_64 | ✅ Available |
| macOS arm64 (Apple Silicon) | ✅ Available |
| macOS x86_64 (Intel) | ✅ Available |
| Windows | Planned |

**On Windows?** You can still use CloakBrowser via Docker or with your own Chromium binary by setting `CLOAKBROWSER_BINARY_PATH=/path/to/chrome`.

## Requirements

- Node.js >= 18
- One of: `playwright-core` >= 1.40 or `puppeteer-core` >= 21

## Links

- 🌐 [Website](https://cloakbrowser.dev)
- 🐛 [Bug reports & feature requests](https://github.com/CloakHQ/CloakBrowser/issues)
- 📦 [PyPI (Python package)](https://pypi.org/project/cloakbrowser/)
- 📖 [Full documentation](https://github.com/CloakHQ/CloakBrowser#readme)
- 📧 Contact: cloakhq@pm.me

## License

MIT — see [LICENSE](https://github.com/CloakHQ/CloakBrowser/blob/main/LICENSE).
