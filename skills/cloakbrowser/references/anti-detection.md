# Anti-Detection Hardening & Patchright Backend

CloakBrowser passes most bot detection systems out of the box. For the toughest targets (DataDome, Kasada, Akamai, reCAPTCHA v3 Enterprise), additional hardening and backend selection are required.

## Backend Selection: Playwright vs. Patchright

CloakBrowser supports a custom `backend` argument that dictates how automation interactions are handled:

| Backend | Suppresses CDP Signals | Handles Proxy Auth | Supports `add_init_script` | Primary Use Case |
|---|---|---|---|---|
| `'playwright'` (default) | No | Yes | Yes | Standard sites, basic anti-bots, normal scraping. |
| `'patchright'` | **Yes** (fully stealth) | No | No | Strictly protected sites, **reCAPTCHA v3 Enterprise**. |

### Why backend="patchright" is critical for reCAPTCHA v3 Enterprise:
reCAPTCHA v3 Enterprise monitors the Chrome DevTools Protocol (CDP) connection. Stock Playwright communicates over CDP, leaking the `isAutomatedWithCDP` flag. 
Setting `backend="patchright"` launches a customized Playwright build that actively hides and intercepts CDP traffic, yielding a **0.9 (human)** score on enterprise fingerprinters.

```python
from cloakbrowser import launch

# Maximum stealth for reCAPTCHA Enterprise
browser = launch(
    backend="patchright",
    humanize=True,
    human_preset="careful",
)
```
*Note*: When using `'patchright'`, you cannot use standard HTTP proxy authentication popups or Playwright's `page.add_init_script()`.

---

## Recommended Configuration by Difficulty

### Level 1: Basic Web Scraping (no aggressive anti-bots)
```python
browser = launch(headless=True)
```

### Level 2: reCAPTCHA v3 (Target Score: 0.9)
```python
browser = launch(
    backend="patchright",  # Highly recommended for Enterprise
    humanize=True,
    human_preset="careful",
)
```
*Follow the behavioral best practices in [humanize.md](humanize.md): use typing delay, sleep, and avoid massive amounts of evaluate calls.*

### Level 3: Cloudflare Turnstile (Headed Mode + Residential IP)
```python
browser = launch(
    headless=False,  # Headed mode recommended to bypass managed Turnstile challenges
    proxy="socks5://user:pass@residential-proxy:1080",
    geoip=True,      # Match timezone and locale to proxy IP location
    humanize=True,
)
```

### Level 4: DataDome / Kasada / Akamai (Absolute Maximum Hardening)
```python
browser = launch(
    headless=False,
    proxy="socks5://user:pass@residential-proxy:1080",
    geoip=True,
    humanize=True,
    human_preset="careful",
    args=[
        "--fingerprint-storage-quota=5000",  # Bypasses incognito/private quota detection
    ]
)
```
*Ensure Windows/macOS fonts are installed if running on headless Linux servers.*

---

## Linux Font Configuration

Kasada and Akamai render hidden canvases to hash emoji and font outputs. Headless Linux servers (e.g. Docker, VPS) have minimal fonts, producing unique hashes that flag the browser as a bot.

1. **Install common font packages**:
```bash
sudo apt update
sudo apt install -y fonts-noto-color-emoji fonts-freefont-ttf fonts-unifont \
    fonts-ipafont-gothic fonts-wqy-zenhei fonts-tlwg-loma-otf
```

2. **For CreepJS-level stealth (inject real Windows fonts)**:
Copy TTF fonts from a Windows machine (`C:\Windows\Fonts`) into your Linux server, then point CloakBrowser to them:
```bash
mkdir -p ~/.local/share/fonts/windows
cp /path/to/windows/fonts/*.ttf ~/.local/share/fonts/windows/
fc-cache -f  # Mandatory to rebuild font cache
```
```python
browser = launch(
    args=["--fingerprint-fonts-dir=/home/user/.local/share/fonts/windows"]
)
```

---

## Testing Your Hardening Configuration

Use these boilerplate scripts to check your detection status:

### 1. Test Automation Flags (bot.sannysoft.com)
```python
from cloakbrowser import launch
import time

browser = launch(headless=False)
page = browser.new_page()
page.goto("https://bot.sannysoft.com")
time.sleep(5)
page.screenshot(path="sannysoft-test.png")
browser.close()
# Look for solid green "Pass" across all variables.
```

### 2. Test Incognito Status & Canvas (FingerprintJS)
```python
from cloakbrowser import launch
import time

# Low storage quota will flag as "incognito"
browser = launch(
    headless=False,
    args=["--fingerprint-storage-quota=5000"]
)
page = browser.new_page()
page.goto("https://fingerprintjs.github.io/fingerprintjs/")
time.sleep(6)
page.screenshot(path="fingerprintjs-test.png")
browser.close()
```

---

## Common Mistakes to Avoid

1. **Calling `page.wait_for_timeout()`**: This is highly detectable because it uses automated timers. Use standard Python `time.sleep()` instead.
2. **Datacenter Proxies against Akamai/DataDome**: Datacenter IP ranges are blacklisted. High-difficulty targets require premium residential proxies.
3. **Bypassing Font Setup on Headless Servers**: Bot fingerprinters instantly detect Linux-specific font shortages.
4. **Too Many `page.evaluate()` Calls**: Frequently invoking JS execution from Playwright generates timing patterns that anti-bots track. Batch your evaluated scripts into single calls.
