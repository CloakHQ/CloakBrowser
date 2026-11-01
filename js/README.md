<p align="center">
<img src="https://i.imgur.com/cqkp6fG.png" width="500" alt="CloakBrowser">
</p>

# CloakBrowser

[![npm](https://img.shields.io/npm/v/cloakbrowser)](https://www.npmjs.com/package/cloakbrowser)
[![License](https://img.shields.io/github/license/CloakHQ/CloakBrowser)](https://github.com/CloakHQ/CloakBrowser/blob/main/LICENSE)

**Stealth Chromium that passes every bot detection test.**

Drop-in Playwright/Puppeteer replacement. Same API, same code — just swap the import. **3 lines of code, 30 seconds to unblock.**

- **87 source-level C++ patches** — canvas, WebGL, audio, fonts, GPU, screen, WebRTC, network timing, automation signals
- **0.9 reCAPTCHA v3 score** — human-level, server-verified
- **Passes Cloudflare Turnstile**, FingerprintJS, BrowserScan — tested against 50+ detection sites
- **`npm install cloakbrowser`** — binary auto-downloads, auto-updates, zero config
- **Latest binary, free to try** — [get a free key with your email](https://cloakbrowser.dev/free) (or just launch: the first run asks), scale to thousands of sessions on Pro
- **Works with any framework** — tested with browser-use, Crawl4AI, Scrapling, Stagehand ([example](examples/stagehand.ts)), LangChain, Selenium, and more

## Install

```bash
# With Playwright
npm install cloakbrowser playwright-core

# With Puppeteer
npm install cloakbrowser puppeteer-core
```

On first launch, the stealth Chromium binary auto-downloads (~200MB, cached at `~/.cloakbrowser/`).

**License key:** every launch needs one, and a free key takes one email. The first launch in a terminal asks: get a free key (opens the signup page and continues once you confirm your email) or paste a key you have. In CI, Docker, or any run without a terminal, set `CLOAKBROWSER_LICENSE_KEY` (get one with `npx cloakbrowser login` or at [cloakbrowser.dev/free](https://cloakbrowser.dev/free)).

## Usage

### Playwright (default)

```javascript
import { launch } from 'cloakbrowser';

const browser = await launch();
const page = await browser.newPage();
await page.goto('https://example.com');
console.log(await page.title());
await browser.close();
```

**For sites with anti-bot protection**, add a residential proxy and these flags:

```javascript
const browser = await launch({
    proxy: 'http://user:pass@residential-proxy:port',
    geoip: true,       // match timezone + locale to proxy IP
    headless: false,    // some sites detect headless even with C++ patches
    humanize: true,     // human-like mouse, keyboard, scroll
});
```

See the [main README](https://github.com/CloakHQ/CloakBrowser#troubleshooting) for site-specific troubleshooting (Kasada, Akamai, reCAPTCHA).

### Puppeteer

> **Note:** Playwright is recommended for sites with reCAPTCHA Enterprise. Puppeteer's CDP protocol leaks automation signals that reCAPTCHA Enterprise can detect. This is a known Puppeteer limitation, not specific to CloakBrowser.

```javascript
import { launch } from 'cloakbrowser/puppeteer';

const browser = await launch({
  proxy: 'http://user:pass@residential-proxy:port',
  geoip: true,
  headless: false,
  humanize: true,
});
const page = await browser.newPage();
await page.goto('https://example.com');
console.log(await page.title());
await browser.close();
```

### Options

```javascript
import { launch, launchContext, launchPersistentContext } from 'cloakbrowser';

// With proxy (HTTP or SOCKS5)
const browser = await launch({
  proxy: 'http://user:pass@proxy:8080',
});
const browser = await launch({
  proxy: 'socks5://user:pass@proxy:1080',
});
// Note: SOCKS5 and credentialed HTTP proxies are set on the browser, so
// context.request / page.request / route.fetch() do NOT use them (real IP).
// Make those calls from the page instead, which goes through the proxy:
const data = await page.evaluate(async (url) => (await fetch(url)).json(), 'https://example.com/api');

// With proxy object (bypass, separate auth fields)
const browser = await launch({
  proxy: { server: 'http://proxy:8080', bypass: '.google.com', username: 'user', password: 'pass' },
});

// Headed mode (visible browser window)
const browser = await launch({ headless: false });

// Extra Chrome args
const browser = await launch({
  args: ['--disable-gpu'],
});

// Pin an exact Chromium version (paid Pro key only)
const browser = await launch({ licenseKey: 'cb_xxxxxxxx', browserVersion: '154.0.8037.57.1' });

// Opt into the Pro Preview binary channel
const browser = await launch({
  licenseKey: 'cb_xxxxxxxx',
  releaseChannel: 'preview',
});

// Auto-detect timezone/locale from proxy IP (requires: npm install mmdb-lib)
const browser = await launch({
  proxy: 'http://proxy:8080',
  geoip: true,
});

// Browser + context in one call
const context = await launchContext({
  proxy: 'http://user:pass@residential-proxy:port',
  geoip: true,
  headless: false,
  humanize: true,
});

// Persistent profile — stay logged in, load extensions
const ctx = await launchPersistentContext({
  userDataDir: './chrome-profile',
  headless: false,
  proxy: 'http://user:pass@proxy:8080',
});
const page = ctx.pages()[0] || await ctx.newPage();
await page.goto('https://example.com');
await ctx.close();  // profile saved — reuse same path to restore state
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
```

### CLI

Pre-download the binary or check installation status from the command line:

```bash
npx cloakbrowser login        # Get a free key by email, or save a key you have
npx cloakbrowser logout       # Remove the saved key
npx cloakbrowser install      # Download binary with progress output
npx cloakbrowser info         # Show version, path, platform
npx cloakbrowser update       # Check for and download newer binary
npx cloakbrowser clear-cache  # Remove cached binaries
```

`login` with no argument shows the same menu as a first launch without a key: **1)** get a free key (opens the signup page in your browser, then waits until you confirm your email) or **2)** paste a key you have. `login <key>` saves a key directly. Keys are validated, then stored at `~/.cloakbrowser/license.key` (readable by you only) so every launch picks them up.

### Utilities

```javascript
import { ensureBinary, clearCache, binaryInfo } from 'cloakbrowser';

// Pre-download binary (e.g., during Docker build; needs CLOAKBROWSER_LICENSE_KEY set)
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
| CDP detection | Detected | **Not detected** |
| TLS fingerprint | Mismatch | **Identical to Chrome** |
| | | **Tested against 50+ detection sites** |

## Configuration

| Env Variable | Default | Description |
|---|---|---|
| `CLOAKBROWSER_LICENSE_KEY` | — | Your license key (free or paid). Overrides `~/.cloakbrowser/license.key`. Required wherever there is no terminal to ask (CI, Docker) |
| `CLOAKBROWSER_BINARY_PATH` | — | Skip download, use a local Chromium binary |
| `CLOAKBROWSER_CACHE_DIR` | `~/.cloakbrowser` | Binary cache directory |
| `CLOAKBROWSER_AUTO_UPDATE` | `true` | Set to `false` to keep the cached build and skip update checks |
| `CLOAKBROWSER_VERSION` | — | Pin to an exact Chromium version for rollback (e.g. `154.0.8037.57.1`). Paid Pro key only |
| `CLOAKBROWSER_RELEASE_CHANNEL` | `stable` | Set to `preview` to opt into the Pro Preview binary channel |

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

| Platform | Binary | Status |
|---|---|---|
| Linux x86_64 | Chromium 155 (87 patches) | ✅ |
| Linux arm64 (RPi, Graviton) | Chromium 155 (87 patches) | ✅ |
| macOS arm64 (Apple Silicon) | Chromium 155 (87 patches) | ✅ |
| macOS x86_64 (Intel) | Chromium 155 (87 patches) | ✅ |
| Windows x86_64 | Chromium 155 (87 patches) | ✅ |

Free and Pro keys get the same build; Pro raises the number of concurrent sessions.

## CloakBrowser Pro

The wrappers (Python, JS, .NET) are MIT, free forever. The latest binary is **free to try** — throw it at your hardest target today.

Anti-bot systems change every week and an older binary quietly degrades. The latest build is the one that keeps passing. **Try it free, then upgrade when you're running for real.**

- **Free, latest build (Chromium 156)** — the newest binary, the exact one that stays [green against live detection](#test-results). Free with your email, one concurrent session. Just launch (the first run asks), run `npx cloakbrowser login`, or [grab your key](https://cloakbrowser.dev/free), then point it at the site that's been blocking you.
- **Pro** — when it's part of production scraping, QA, monitoring, or automation: scale to **5, 20, 200, 2,000, or more concurrent sessions**, always first on the newest patches, with hands-on support. Linux, Windows, macOS. **[See plans and pricing →](https://cloakbrowser.dev)**

Get a key and activate it:

```bash
npx cloakbrowser login      # get a free key by email, or paste a key you have
# ...or set it directly (env var, licenseKey option, or ~/.cloakbrowser/license.key):
export CLOAKBROWSER_LICENSE_KEY=cb_xxxxxxxx
```

Try the latest free → **[cloakbrowser.dev/free](https://cloakbrowser.dev/free)**  ·  Scale up on Pro → **[cloakbrowser.dev](https://cloakbrowser.dev)**

## Requirements

- Node.js 20.19+ or 22.12+
- One of: `playwright-core` >= 1.53 or `puppeteer-core` >= 21

## Troubleshooting

**Sites challenge every visit**

`launch()` starts with an empty profile each time, so every visit looks like a new visitor. Use `launchPersistentContext()` so cookies and storage carry over and you come back as a returning visitor:

```javascript
import { launchPersistentContext } from 'cloakbrowser';

const ctx = await launchPersistentContext({
  userDataDir: './my-profile',
  headless: false,
});

// Load Chrome extensions
const ctx = await launchPersistentContext({
  userDataDir: './my-profile',
  headless: false,
  extensionPaths: ['./my-extension'],
});
```

This also gives you cookie and localStorage persistence across sessions.

**reCAPTCHA v3 scores are low (0.1–0.3)**

Avoid `page.waitForTimeout()` — it sends CDP protocol commands that reCAPTCHA detects. Use native sleep instead:

```javascript
// Bad — sends CDP commands, reCAPTCHA detects this
await page.waitForTimeout(3000);

// Good — invisible to the browser
await new Promise(r => setTimeout(r, 3000));
```

Other tips for maximizing reCAPTCHA scores:

- **Use Playwright, not Puppeteer** — Puppeteer sends more CDP protocol traffic that reCAPTCHA detects ([details](#puppeteer))
- **Use residential proxies** — datacenter IPs are flagged by IP reputation, not browser fingerprint
- **Spend 15+ seconds on the page** before triggering reCAPTCHA — short visits score lower
- **Space out requests** — back-to-back `grecaptcha.execute()` calls from the same session get penalized. Wait 30+ seconds between pages with reCAPTCHA
- **Use `page.type()` instead of `page.fill()`** for form filling — `fill()` sets values directly without keyboard events, which reCAPTCHA's behavioral analysis flags. `type()` with a delay simulates real keystrokes:

  ```javascript
  await page.type('#email', 'user@example.com', { delay: 50 });
  ```

- **Minimize `page.evaluate()` calls** before the reCAPTCHA check fires — each one sends CDP traffic

**Try a Preview binary**

Stable is the default. Opt into Preview per launch:

```javascript
const browser = await launch({
  licenseKey: 'cb_xxxxxxxx',
  releaseChannel: 'preview',
});
```

Or set `CLOAKBROWSER_RELEASE_CHANNEL=preview` for all launches and CLI commands. Preview selects the newest build available for this platform: a newer Preview when present, otherwise Stable. `npx cloakbrowser info` reports the resolved channel and exact version. An exact `browserVersion` pin overrides the channel.

**New update broke something? Roll back to the previous version**

Pin to an exact binary version (keep current wrapper, use older Chromium). Paid Pro key only. A free key cannot pin: it ignores the pin and always gets the latest build.

```bash
export CLOAKBROWSER_VERSION=154.0.8037.57.1   # env var for all launches
```

```javascript
const browser = await launch({ licenseKey: 'cb_xxxxxxxx', browserVersion: '154.0.8037.57.1' });
```

The pin is never sticky — unpinned launches always use the latest available version.

Or downgrade the wrapper (if a new wrapper release broke something). With a license key you still get the latest binary; pin it as above to roll that back too:

```bash
npm install cloakbrowser@0.6.3
```

**Can I still use the old keyless v146 build?**

Yes, through the last wrapper release that runs without a key: `npm install cloakbrowser@0.6`. It downloads the old v146 build (v145 on macOS) from [GitHub Releases](https://github.com/CloakHQ/cloakbrowser/releases), with no key. It is no longer updated and ages fast as detection evolves, so the free key on the latest build is the better choice.

## Links

- 🌐 [Website](https://cloakbrowser.dev)
- 🐛 [Bug reports & feature requests](https://github.com/CloakHQ/CloakBrowser/issues)
- 📦 [PyPI (Python package)](https://pypi.org/project/cloakbrowser/)
- 📖 [Full documentation](https://github.com/CloakHQ/CloakBrowser#readme)
- 📧 Contact: <cloakhq@pm.me>

## License

- **Wrapper code** (this repository) — MIT. See [LICENSE](https://github.com/CloakHQ/CloakBrowser/blob/main/LICENSE).
- **CloakBrowser binary** (compiled Chromium) — requires a license key: free with your email (one concurrent session), or a paid [CloakBrowser Pro](https://cloakbrowser.dev) subscription. Free for personal and commercial use, no redistribution. See [BINARY-LICENSE.md](https://github.com/CloakHQ/CloakBrowser/blob/main/BINARY-LICENSE.md).

Use against financial, banking, healthcare, or government authentication systems without authorization is expressly prohibited.
