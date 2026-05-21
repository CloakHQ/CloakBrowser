<!--
  ไฟล์นี้คือคำแปลภาษาไทยของ README.md ต้นฉบับ
  This file is a Thai translation of the original README.md.
-->

> 🌐 **ภาษา / Language:** [English](README.md) · **ไทย (Thai)**
>
> 📄 เอกสารนี้เป็น **คำแปลภาษาไทย** ของ [README.md](README.md) ต้นฉบับ เพื่อความสะดวกของผู้อ่านที่ใช้ภาษาไทย
> เครดิตและลิขสิทธิ์ทั้งหมดเป็นของโปรเจกต์ต้นฉบับ **[CloakHQ/CloakBrowser](https://github.com/CloakHQ/CloakBrowser)**
> หากเนื้อหาส่วนใดขัดแย้งกัน ให้ยึดตาม [ฉบับภาษาอังกฤษ](README.md) เป็นหลักเสมอ
> _(Thai translation of the original README. All credit and copyright belong to the upstream project [CloakHQ/CloakBrowser](https://github.com/CloakHQ/CloakBrowser). If anything conflicts, the [English version](README.md) is authoritative.)_

---

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

<h3 align="center">Chromium แบบ stealth ที่ผ่านทุกการทดสอบการตรวจจับบอท</h3>

<table><tr><td>
ไม่ใช่แค่ config ที่ถูกแพตช์ ไม่ใช่การ inject JS แต่เป็น Chromium binary จริงที่มีการแก้ไข fingerprint ในระดับซอร์สโค้ด C++ ระบบ antibot ให้คะแนนมันว่าเป็นเบราว์เซอร์ปกติ เพราะมัน<em>เป็น</em>เบราว์เซอร์ปกติจริง ๆ
</td></tr></table>

<br>

<p align="center">
<img src="https://i.imgur.com/IvB0It7.gif" width="600" alt="Cloudflare Turnstile — 3 Tests Passing">
<br><em>Cloudflare Turnstile — การทดสอบสด 3 รายการที่ผ่าน (headed mode, macOS)</em>
</p>

<br>

<p align="center">
ตัวแทนแบบ drop-in สำหรับ Playwright/Puppeteer ทั้ง Python และ JavaScript<br>
API เดียวกัน โค้ดเดียวกัน เพียงแค่สลับ import <strong>โค้ด 3 บรรทัด ปลดบล็อกใน 30 วินาที</strong>
</p>

- **แพตช์ C++ ระดับซอร์สโค้ด 49 รายการ** — canvas, WebGL, audio, fonts, GPU, screen, WebRTC, network timing, สัญญาณ automation, พฤติกรรม CDP input
- **`humanize=True`** — เส้นโค้งเมาส์ จังหวะคีย์บอร์ด และรูปแบบการเลื่อนที่เหมือนมนุษย์ เพียงแฟล็กเดียว ก็ผ่านการตรวจจับเชิงพฤติกรรม
- **คะแนน reCAPTCHA v3 ที่ 0.9** — ระดับมนุษย์ ตรวจสอบจากฝั่งเซิร์ฟเวอร์
- **ผ่าน Cloudflare Turnstile**, FingerprintJS, BrowserScan — ทดสอบกับเว็บตรวจจับมากกว่า 30 แห่ง
- **binary อัปเดตอัตโนมัติ** — ตรวจสอบการอัปเดตในเบื้องหลัง อยู่บน stealth build ล่าสุดเสมอ
- **`pip install cloakbrowser`** หรือ **`npm install cloakbrowser`** — binary ดาวน์โหลดอัตโนมัติ ไม่ต้องตั้งค่าใด ๆ
- **ฟรีและโอเพนซอร์ส** — ไม่มีค่าสมาชิก ไม่จำกัดการใช้งาน

**ลองใช้เลยตอนนี้** — ไม่ต้องติดตั้ง:
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

ใช้งานกับ Puppeteer ได้เช่นกัน: `import { launch } from 'cloakbrowser/puppeteer'` ([รายละเอียด](#puppeteer))

## การติดตั้ง

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

เมื่อรันครั้งแรก stealth Chromium binary จะถูกดาวน์โหลดโดยอัตโนมัติ (~200MB, แคชไว้ในเครื่อง)

**ทางเลือกเสริม:** ตรวจจับ timezone/locale อัตโนมัติจาก IP ของพร็อกซี:
```bash
pip install cloakbrowser[geoip]
```

**กำลังย้ายจาก Playwright อยู่หรือเปล่า?** เปลี่ยนแค่บรรทัดเดียว:

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

> ⭐ **กดดาว** เพื่อแสดงการสนับสนุน — **[ติดตามการรีลีส](https://github.com/CloakHQ/CloakBrowser/subscription)** เพื่อรับการแจ้งเตือนเมื่อมี build ใหม่ออกมา

## ตัวจัดการโปรไฟล์เบราว์เซอร์ (Browser Profile Manager)

ทางเลือกแบบ self-hosted แทน Multilogin, GoLogin และ AdsPower สร้างโปรไฟล์เบราว์เซอร์ที่มี fingerprint, พร็อกซี และ persistent session ที่ไม่ซ้ำกัน เปิดและโต้ตอบกับมันในเบราว์เซอร์ของคุณผ่าน noVNC

```bash
docker run -p 8080:8080 -v cloakprofiles:/data cloakhq/cloakbrowser-manager
```

เปิด [http://localhost:8080](http://localhost:8080) สร้างโปรไฟล์ คลิก **Launch** เสร็จแล้ว

→ **[CloakBrowser Manager](https://github.com/CloakHQ/CloakBrowser-Manager)** — ฟรี โอเพนซอร์ส (MIT)

---

## ล่าสุด: v0.3.29 (Chromium 146.0.7680.177.4)

- **`launch_context_async()`** — คู่เวอร์ชัน async ของ `launch_context()` ส่งต่อ kwargs ไปยัง `browser.new_context()` สำหรับ `storage_state`, `permissions`, `extra_http_headers` โดยไม่ต้องใช้โฟลเดอร์ persistent profile
- **JS `contextOptions` escape hatch** — ส่งต่อออปชันใด ๆ ก็ได้ (รวมถึง `storageState`) ไปยัง `newContext()` ของ Playwright จาก `launchContext()` / `launchPersistentContext()`
- **พร็อกซี SOCKS5 แบบเนทีฟ** — `proxy="socks5://user:pass@host:port"` ใช้งานได้โดยตรงในทุกฟังก์ชัน launch ทั้ง Python + JS อุโมงค์ QUIC/HTTP3 ผ่าน SOCKS5 ด้วย UDP ASSOCIATE
- **อัปเกรด Chromium 146** — rebase แพตช์ทั้งหมดจาก 145.0.7632.x ไปเป็น 146.0.7680.177
- **แพตช์ fingerprint 57 รายการ** — เพิ่มการครอบคลุม detection-vector (WebAuthn, AAC audio, ตำแหน่งหน้าต่าง) และการแก้ไขความสอดคล้องของ WebGL/canvas
- **การปลอม IP ของ WebRTC** — `--fingerprint-webrtc-ip=auto` แปลง exit IP ของพร็อกซีของคุณและปลอม WebRTC ICE candidate ถูก inject อัตโนมัติเมื่อใช้ `geoip=True` (ไม่มีการเรียก network เพิ่ม)
- **การลบสัญญาณของพร็อกซี** — timing ของ DNS/connect/SSL ถูกตั้งเป็นศูนย์ ลบ proxy cache header ออก และกำจัดการรั่วของ Proxy-Connection header
- **`cloakserve` ตัวมัลติเพล็กซ์ CDP** — เขียนใหม่เป็นพร็อกซี CDP แบบหลายการเชื่อมต่อ พร้อม fingerprint seed แยกต่อการเชื่อมต่อ
- **การแยก CDP ของ Humanize** — เหตุการณ์คีย์บอร์ดตอนนี้ใช้ isolated world และ trusted dispatch เพื่อ stealth เชิงพฤติกรรมที่ดีขึ้น
- **`humanize=True`** — เพียงแฟล็กเดียวก็ทำให้การโต้ตอบทั้งหมดของเมาส์ คีย์บอร์ด และการเลื่อน ทำงานเหมือนผู้ใช้จริง เส้นโค้ง Bézier การพิมพ์ทีละตัวอักษร และรูปแบบการเลื่อนที่สมจริง
- **Stealth โดยไม่ต้องมีแฟล็กใด ๆ** — binary สร้าง fingerprint seed แบบสุ่มอัตโนมัติตอนเริ่มทำงาน ไม่ต้องตั้งค่าใด ๆ
- **Timezone และ locale จาก IP ของพร็อกซี** — `launch(proxy="...", geoip=True)` ตรวจจับ timezone และ locale โดยอัตโนมัติ
- **persistent profile** — `launch_persistent_context()` เก็บ cookie และ localStorage ข้ามเซสชัน หลีกเลี่ยงการตรวจจับโหมดไม่ระบุตัวตน

ดูรายละเอียดทั้งหมดได้ใน [CHANGELOG.md](CHANGELOG.md)

## ทำไมต้อง CloakBrowser?

- **แพตช์ระดับ config ใช้ไม่ได้** — `playwright-stealth`, `undetected-chromedriver` และ `puppeteer-extra` ฉีด JavaScript หรือปรับแต่ง flag ทุกครั้งที่ Chrome อัปเดต สิ่งเหล่านี้ก็พังไป ระบบ antibot ตรวจจับตัวแพตช์ได้เอง
- **CloakBrowser แพตช์ซอร์สโค้ดของ Chromium** — fingerprint ถูกแก้ไขในระดับ C++ แล้วคอมไพล์เข้าไปใน binary เว็บไซต์ตรวจจับมองเห็นเบราว์เซอร์จริง เพราะมัน *เป็น* เบราว์เซอร์จริง
- **stealth ระดับซอร์สโค้ด** — แพตช์ C++ จัดการ fingerprint (GPU, หน้าจอ, UA, การรายงานฮาร์ดแวร์) ในระดับ binary ไม่มีการฉีด JavaScript ไม่มี hack ระดับ config เครื่องมือ stealth ส่วนใหญ่แพตช์เฉพาะที่ผิวเท่านั้น
- **พฤติกรรมเหมือนกันทุกที่** — ทำงานเหมือนกันทั้งในเครื่อง, ใน Docker และบน VPS ไม่ต้องใช้แพตช์หรือ config เฉพาะสภาพแวดล้อม
- **ทำงานร่วมกับ AI agent และเฟรมเวิร์กอัตโนมัติ** — stealth แบบ drop-in สำหรับ browser-use, Crawl4AI, Scrapling, Stagehand, LangChain, Selenium และอื่นๆ ดูที่ [การผสานรวม](#framework-integrations)

CloakBrowser ไม่ได้แก้ CAPTCHA — แต่ป้องกันไม่ให้ CAPTCHA ปรากฏขึ้นเลย ไม่มีบริการแก้ CAPTCHA ไม่มีการหมุนพร็อกซีในตัว — นำพร็อกซีของคุณมาเอง แล้วใช้ Playwright API ที่คุณรู้จักอยู่แล้ว

## ผลการทดสอบ

ทุกการทดสอบยืนยันกับบริการตรวจจับจริง ทดสอบล่าสุด: เม.ย. 2026 (Chromium 146)

| บริการตรวจจับ | Playwright ต้นฉบับ | CloakBrowser | หมายเหตุ |
|---|---|---|---|
| **reCAPTCHA v3** | 0.1 (bot) | **0.9** (human) | ยืนยันฝั่งเซิร์ฟเวอร์ |
| **Cloudflare Turnstile** (non-interactive) | FAIL | **PASS** | แก้ไขอัตโนมัติ |
| **Cloudflare Turnstile** (managed) | FAIL | **PASS** | คลิกเดียว |
| **ShieldSquare** | BLOCKED | **PASS** | เว็บไซต์ production |
| การตรวจจับบอท **FingerprintJS** | DETECTED | **PASS** | demo.fingerprint.com |
| การตรวจจับบอท **BrowserScan** | DETECTED | **NORMAL** (4/4) | browserscan.net |
| **bot.incolumitas.com** | 13 fails | **1 fail** | WEBDRIVER spec เท่านั้น |
| **deviceandbrowserinfo.com** | 6 true flags | **0 true flags** | `isBot: false` |
| `navigator.webdriver` | `true` | **`false`** | แพตช์ระดับซอร์สโค้ด |
| `navigator.plugins.length` | 0 | **5** | รายการปลั๊กอินจริง |
| `window.chrome` | `undefined` | **`object`** | มีอยู่เหมือน Chrome จริง |
| UA string | `HeadlessChrome` | **`Chrome/146.0.0.0`** | ไม่มีการรั่วของ headless |
| การตรวจจับ CDP | Detected | **Not detected** | `isAutomatedWithCDP: false` |
| TLS fingerprint | Mismatch | **เหมือนกับ Chrome ทุกประการ** | ja3n/ja4/akamai ตรงกัน |
| | | **ทดสอบกับเว็บไซต์ตรวจจับมากกว่า 30 แห่ง** | |

### หลักฐาน

<p align="center">
<img src="https://i.imgur.com/hvIQyMv.png" width="600" alt="reCAPTCHA v3 — Score 0.9">
<br><em>คะแนน reCAPTCHA v3 0.9 — ยืนยันฝั่งเซิร์ฟเวอร์ (ระดับมนุษย์)</em>
</p>

<p align="center">
<img src="https://i.imgur.com/qMIRfhq.png" width="600" alt="Cloudflare Turnstile — Success">
<br><em>โจทย์ Cloudflare Turnstile แบบ non-interactive — แก้ไขอัตโนมัติ</em>
</p>

<p align="center">
<img src="https://i.imgur.com/PRsw6rT.png" width="600" alt="BrowserScan — Normal">
<br><em>การตรวจจับบอทของ BrowserScan — NORMAL (ผ่าน 4/4 รายการ)</em>
</p>

<p align="center">
<img src="https://i.imgur.com/9n2C7tu.png" width="600" alt="FingerprintJS — Passed">
<br><em>เดโม web-scraping ของ FingerprintJS — ส่งข้อมูลให้ ไม่ถูกบล็อก</em>
</p>

<p align="center">
<img src="https://i.imgur.com/srCcFtK.png" width="600" alt="deviceandbrowserinfo.com — You are human!">
<br><em>การตรวจจับบอทเชิงพฤติกรรมของ deviceandbrowserinfo.com — "You are human!" ด้วย humanize=True (ผ่าน 24/24 สัญญาณ)</em>
</p>

## การเปรียบเทียบ

| คุณสมบัติ | Playwright | playwright-stealth | undetected-chromedriver | Camoufox | CloakBrowser |
|---|---|---|---|---|---|
| คะแนน reCAPTCHA v3 | 0.1 | 0.3-0.5 | 0.3-0.7 | 0.7-0.9 | **0.9** |
| Cloudflare Turnstile | Fail | บางครั้ง | บางครั้ง | Pass | **Pass** |
| ระดับแพตช์ | ไม่มี | ฉีด JS | แพตช์ระดับ config | C++ (Firefox) | **C++ (Chromium)** |
| รอดจากการอัปเดต Chrome | N/A | พังบ่อย | พังบ่อย | ได้ | **ได้** |
| การดูแลรักษา | มี | หยุดนิ่ง | หยุดนิ่ง | ไม่เสถียร | **แอ็กทีฟ** |
| เอนจินเบราว์เซอร์ | Chromium | Chromium | Chrome | Firefox | **Chromium** |
| Playwright API | Native | Native | ไม่ (Selenium) | ไม่ | **Native** |

## วิธีการทำงาน

CloakBrowser เป็น wrapper บางๆ (Python + JavaScript) ที่ครอบ binary ของ Chromium ที่สร้างขึ้นเอง:

1. **คุณติดตั้ง** → `pip install cloakbrowser` หรือ `npm install cloakbrowser`
2. **เปิดใช้งานครั้งแรก** → binary ดาวน์โหลดอัตโนมัติสำหรับแพลตฟอร์มของคุณ (Chromium 146)
3. **ทุกครั้งที่เปิดใช้งาน** → Playwright หรือ Puppeteer เริ่มทำงานด้วย binary ของเรา + stealth args
4. **คุณเขียนโค้ด** → Playwright/Puppeteer API มาตรฐาน ไม่มีอะไรใหม่ต้องเรียนรู้

binary นี้มีแพตช์ระดับซอร์สโค้ด 49 รายการ ครอบคลุม canvas, WebGL, audio, fonts, GPU, คุณสมบัติของหน้าจอ, WebRTC, network timing, การรายงานฮาร์ดแวร์, การลบสัญญาณอัตโนมัติ และการเลียนแบบพฤติกรรม input ของ CDP

สิ่งเหล่านี้ถูกคอมไพล์เข้าไปใน binary ของ Chromium — ไม่ได้ฉีดผ่าน JavaScript และไม่ได้ตั้งค่าผ่าน flag

การดาวน์โหลด binary จะถูกตรวจสอบด้วย SHA-256 checksum เพื่อรับประกันความสมบูรณ์

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

คืนค่าเป็นอ็อบเจกต์ Playwright `Browser` มาตรฐาน เมธอดของ Playwright ทั้งหมดใช้งานได้: `new_page()`, `new_context()`, `close()` และอื่น ๆ

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

ฟังก์ชันอำนวยความสะดวกที่สร้างทั้ง browser และ context ในการเรียกครั้งเดียว พร้อมด้วย user agent, viewport, locale และ timezone:

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

kwargs ส่วนเกินจะถูกส่งต่อไปยัง `browser.new_context()` ของ Playwright — ใช้สิ่งนี้สำหรับ `storage_state`, `permissions`, `extra_http_headers` ฯลฯ โดยไม่ต้องมีโฟลเดอร์ persistent profile:

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

คู่ขนานแบบ async ของ `launch_context()` มี signature และการส่งต่อ kwargs เหมือนกัน:

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

<a id="launch_persistent_context"></a>

### `launch_persistent_context()`

เหมือนกับ `launch_context()` แต่ใช้ persistent user profile คุกกี้, localStorage และแคชจะคงอยู่ข้ามเซสชัน

ใช้สิ่งนี้เมื่อคุณต้องการ:
- **คงสถานะล็อกอินไว้** ข้ามการรัน (คุกกี้/เซสชันอยู่รอดเมื่อรีสตาร์ท)
- **หลบเลี่ยงการตรวจจับ incognito** (บางเว็บไซต์จับ profile ที่ว่างเปล่าและชั่วคราว)
- **โหลด Chrome extensions** (extensions ทำงานได้จาก user data dir จริงเท่านั้น)
- **สร้างประวัติการท่องเว็บที่เป็นธรรมชาติ** (ฟอนต์ที่แคชไว้, service workers, IndexedDB สะสมขึ้นเมื่อเวลาผ่านไป ทำให้ profile ดูสมจริงมากขึ้น)

```python
from cloakbrowser import launch_persistent_context

# First run — creates the profile
ctx = launch_persistent_context("./my-profile", headless=False)
page = ctx.new_page()
page.goto("https://protected-site.com")
ctx.close()  # profile saved

# Next run — cookies, localStorage restored automatically
ctx = launch_persistent_context("./my-profile", headless=False)

# Load Chrome extensions
ctx = launch_persistent_context(
    "./my-profile",
    headless=False,
    extension_paths=["./my-extension"],
)
```

รองรับตัวเลือกทั้งหมดเช่นเดียวกับ `launch_context()`: `proxy`, `user_agent`, `viewport`, `locale`, `timezone`, `color_scheme`, `geoip`, `extension_paths`

เวอร์ชัน async: `launch_persistent_context_async()`

**การแลกเปลี่ยนระหว่างโควตาสตอเรจกับการตรวจจับ:** โดยค่าเริ่มต้น binary จะปรับโควตาสตอเรจให้เป็นมาตรฐานเพื่อให้ผ่าน FingerprintJS ซึ่งบล็อก persistent context ที่รายงานค่าโควตาแบบ non-incognito นั่นหมายความว่าบริการตรวจจับที่ลงโทษโหมด incognito (เช่นการตรวจสอบ `notPrivate` ของ BrowserScan ที่ -10 คะแนน) จะยังคงจับมันได้ หากเว็บไซต์เป้าหมายของคุณลงโทษ incognito แต่ไม่ได้ใช้ FingerprintJS ให้ตั้งโควตาให้สูงขึ้นเพื่อให้ดูเป็น profile ปกติ:

```python
ctx = launch_persistent_context("./my-profile", args=["--fingerprint-storage-quota=5000"])
```

| การตั้งค่าโควตา | FingerprintJS | BrowserScan `notPrivate` |
|---|---|---|
| Default (auto, ~500MB) | PASS | -10 (flagged as incognito) |
| `--fingerprint-storage-quota=5000` | อาจกระตุ้นการตรวจจับ | PASS (appears non-incognito) |

### CLI

ดาวน์โหลด binary ล่วงหน้าหรือตรวจสอบสถานะการติดตั้งจากบรรทัดคำสั่ง:

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
# {'version': '146.0.7680.177.3', 'platform': 'linux-x64', 'installed': True, ...}

# Force re-download
clear_cache()

# Pre-download binary (e.g., during Docker build)
ensure_binary()
```

## JavaScript / Node.js API

CloakBrowser มาพร้อมแพ็กเกจ TypeScript ที่มี type definitions ครบถ้วน เลือกใช้ Playwright หรือ Puppeteer ก็ได้ เพราะใช้ stealth binary ตัวเดียวกันอยู่เบื้องหลัง

### Playwright (ค่าเริ่มต้น)

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

> **หมายเหตุ:** แต่ละตัวอย่างด้านบนเป็นโค้ดที่ทำงานแยกกันเองได้ ไม่ได้ตั้งใจให้รันรวมกันเป็นบล็อกเดียว

ออปชันของ Python ทั้งหมดใช้งานได้ใน JS เช่นกัน: `stealthArgs: false` เพื่อปิดค่าเริ่มต้น, `geoip: true` เพื่อตรวจจับ timezone/locale อัตโนมัติจาก IP ของพร็อกซี

<a id="puppeteer"></a>

### Puppeteer

> **หมายเหตุ:** แนะนำให้ใช้ wrapper ของ Playwright สำหรับเว็บไซต์ที่ใช้ reCAPTCHA Enterprise โปรโตคอล CDP ของ Puppeteer รั่วสัญญาณการทำงานอัตโนมัติที่ reCAPTCHA Enterprise สามารถตรวจจับได้ ทำให้เกิดข้อผิดพลาด 403 เป็นระยะ ๆ นี่เป็นข้อจำกัดที่ทราบกันดีของ Puppeteer ไม่ใช่ปัญหาเฉพาะของ CloakBrowser ใช้ Playwright เพื่อผลลัพธ์ที่ดีที่สุด

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

ส่ง `humanize=True` เพื่อทำให้การโต้ตอบทั้งหมดของเมาส์ คีย์บอร์ด และการเลื่อนหน้าจอแยกไม่ออกจากผู้ใช้จริง การเรียกใช้ของ Playwright ทั้งหมด (`page.click()`, `page.fill()`, `page.type()`, `page.mouse.*`, `page.keyboard.*`, Locator API) และการเรียกใช้ของ Puppeteer (`page.click()`, `page.type()`, `page.mouse.*`, `page.keyboard.*`, ElementHandle API) จะถูกแทนที่ด้วยรูปแบบที่เลียนแบบมนุษย์โดยอัตโนมัติ ไม่ต้องแก้ไขโค้ดใด ๆ

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

**สิ่งที่เปลี่ยนไป:**

| การโต้ตอบ | ค่าเริ่มต้น | เมื่อใช้ `humanize=True` |
|---|---|---|
| การเคลื่อนเมาส์ | เทเลพอร์ตทันที | เส้นโค้ง Bézier พร้อม easing และการเลยเป้าเล็กน้อย |
| การคลิก | ทันที | จุดเล็งที่สมจริง + ระยะเวลากดค้าง |
| คีย์บอร์ด | กรอกค่าทันที | จับเวลาทีละตัวอักษร หยุดคิดเป็นจังหวะ พิมพ์ผิดเป็นครั้งคราวพร้อมแก้ไขเอง |
| การเลื่อนหน้าจอ | กระโดดทันที | เร่ง → คงที่ → ชะลอเป็นไมโครสเต็ป |
| `fill()` | ตั้งค่าทันที | ล้างเนื้อหาเดิม แล้วพิมพ์ทีละตัวอักษร |

**พรีเซ็ต** — `default` (ความเร็วปกติ) หรือ `careful` (ช้าลง รอบคอบมากขึ้น มีไมโครมูฟเมนต์ขณะว่างระหว่างการกระทำ):

```python
browser = launch(humanize=True, human_preset="careful")
```

```javascript
const browser = await launch({ humanize: true, humanPreset: 'careful' });
```

**คอนฟิกแบบกำหนดเอง** — แทนที่พารามิเตอร์ใดก็ได้:

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

เข้าถึง Playwright page ดั้งเดิมที่ยังไม่ถูกแพตช์ได้ที่ `page._original` หากคุณต้องการความเร็วแบบดิบสำหรับการเรียกใช้บางอย่างโดยเฉพาะ

> **หมายเหตุ (Playwright):** ใช้ `page.click(selector)`, `page.type(selector, text)`, `page.hover(selector)` หรือ `page.locator(selector).*` เสมอ เพราะคำสั่งเหล่านี้ผ่าน humanize pipeline เต็มรูปแบบ หลีกเลี่ยง `page.query_selector()` เพราะออบเจกต์ `ElementHandle` จะข้ามแพตช์ทั้งหมด ทำให้การเคลื่อนเมาส์เป็นการเทเลพอร์ต เหตุการณ์คีย์บอร์ดเกิดขึ้นโดยไม่มีการจับเวลา และการเลื่อนหน้าจอไม่มีเส้นโค้งแบบมนุษย์
>
> **หมายเหตุ (Puppeteer):** ทั้งเมธอดที่อิงตาม selector (`page.click()`, `page.type()`) และเมธอดของ ElementHandle (`el.click()`, `el.type()`) ได้รับการทำให้เลียนแบบมนุษย์อย่างสมบูรณ์ `page.$()`, `page.$$()` และ `page.waitForSelector()` จะคืนค่า handle ที่ถูกแพตช์ให้โดยอัตโนมัติ

> สนับสนุนโดย [@evelaa123](https://github.com/evelaa123) — ครอบคลุม API ของ Playwright และ Puppeteer อย่างครบถ้วน

## การกำหนดค่า (Configuration)

| Env Variable | Default | คำอธิบาย |
|---|---|---|
| `CLOAKBROWSER_BINARY_PATH` | — | ข้ามการดาวน์โหลด แล้วใช้ binary ของ Chromium ในเครื่องแทน |
| `CLOAKBROWSER_CACHE_DIR` | `~/.cloakbrowser` | ไดเรกทอรีแคชสำหรับ binary |
| `CLOAKBROWSER_DOWNLOAD_URL` | `cloakbrowser.dev` | URL ดาวน์โหลด binary แบบกำหนดเอง |
| `CLOAKBROWSER_AUTO_UPDATE` | `true` | ตั้งเป็น `false` เพื่อปิดการตรวจสอบอัปเดตเบื้องหลัง |
| `CLOAKBROWSER_SKIP_CHECKSUM` | `false` | ตั้งเป็น `true` เพื่อข้ามการตรวจสอบ SHA-256 หลังดาวน์โหลด |
| `CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS` | `5` | จำนวนวินาทีสูงสุดสำหรับการแก้ค่า GeoIP ก่อนจะดำเนินต่อโดยไม่ใช้มัน |

<a id="fingerprint-management"></a>

## การจัดการ Fingerprint

binary นี้ **มี stealth เป็นค่าเริ่มต้น** — ไม่ต้องใช้ flag ใด ๆ มันจะสร้าง fingerprint seed แบบสุ่มอัตโนมัติตอนเริ่มทำงาน และปลอม (spoof) ค่าที่ตรวจจับได้ทั้งหมด (GPU, สเปกฮาร์ดแวร์, ขนาดหน้าจอ, canvas, WebGL, เสียง, ฟอนต์) ทุกครั้งที่เปิดใช้งานจะได้อัตลักษณ์ใหม่ที่สอดคล้องกัน

**fingerprint ทำงานอย่างไร:**

| Scenario | สิ่งที่เกิดขึ้น |
|----------|-------------|
| **No flags** | สร้าง seed แบบสุ่มอัตโนมัติตอนเริ่มทำงาน GPU, หน้าจอ, สเปกฮาร์ดแวร์ และแพตช์ noise ทั้งหมดจะถูก spoof โดยอัตโนมัติ ได้อัตลักษณ์ใหม่ทุกครั้งที่เปิดใช้งาน |
| **`--fingerprint=seed`** | อัตลักษณ์แบบกำหนดได้แน่นอน (deterministic) จาก seed seed เดียวกัน = fingerprint เดียวกันในทุกครั้งที่เปิดใช้งาน ใช้สำหรับการคงสถานะของเซสชัน (ผู้เยี่ยมชมที่กลับมาอีกครั้ง) |
| **`--fingerprint=seed` + flag ที่ระบุชัดเจน** | flag ที่ระบุชัดเจนจะ override ค่าที่สร้างอัตโนมัติแต่ละค่า ส่วน seed จะเติมค่าที่เหลือทั้งหมด |

binary จะตรวจจับแพลตฟอร์มของตัวเองตอนคอมไพล์ — binary ของ macOS จะรายงานว่าเป็น macOS พร้อม Apple GPU ส่วน binary ของ Linux จะรายงานว่าเป็น Linux พร้อม NVIDIA GPU **wrapper** จะ override สิ่งนี้บน Linux โดยส่ง `--fingerprint-platform=windows` ทำให้เซสชันปรากฏเป็นเดสก์ท็อป Windows (เป็น fingerprint ที่พบได้บ่อยกว่า และจัดกลุ่ม (cluster) ได้ยากกว่า) ใช้ `--fingerprint-platform` สำหรับการ spoof ข้ามแพลตฟอร์มเมื่อรัน binary โดยตรง

> **เคล็ดลับ: ใช้ seed คงที่เมื่อกลับมาเยี่ยมชมไซต์เดิม** seed แบบสุ่มจะทำให้ทุกเซสชันดูเหมือนเป็นอุปกรณ์ที่ต่างกัน — ซึ่งอาจน่าสงสัยเมื่อเข้าถึงไซต์เดิมซ้ำ ๆ จาก IP เดียวกัน สำหรับ reCAPTCHA v3 Enterprise และระบบให้คะแนนที่คล้ายกัน seed คงที่จะสร้าง fingerprint ที่สอดคล้องกันในทุกเซสชัน ทำให้คุณดูเหมือนผู้เยี่ยมชมที่กลับมาอีกครั้ง:
> ```python
> browser = launch(args=["--fingerprint=12345"])
> ```
> ```javascript
> const browser = await launch({ args: ['--fingerprint=12345'] });
> ```

### Fingerprint เริ่มต้น

ทุกการเรียก `launch()` จะตั้งค่าเหล่านี้โดยอัตโนมัติ **wrapper** จะใช้ค่าเริ่มต้นที่รับรู้แพลตฟอร์ม — บน Linux จะ spoof เป็น Windows เพื่อให้ได้ fingerprint ที่พบได้บ่อยกว่า ส่วนบน macOS จะรันเป็นเบราว์เซอร์ Mac แบบเนทีฟ:

| Flag | Linux/Windows Default | macOS Default | ควบคุม |
|------|--------------|---------------|----------|
| `--fingerprint` | Random (10000–99999) | Random (10000–99999) | seed หลักสำหรับ canvas, WebGL, เสียง, ฟอนต์, client rects |
| `--fingerprint-platform` | `windows` | `macos` | `navigator.platform`, OS ของ User-Agent, การเลือก GPU pool |

binary จะสร้างทุกอย่างที่เหลือจาก seed โดยอัตโนมัติ: GPU, hardware concurrency, device memory และขนาดหน้าจอ แต่ละ seed จะสร้าง fingerprint ที่ไม่ซ้ำกันและสอดคล้องกัน หากจำเป็นสามารถ override ได้ด้วย flag ที่ระบุชัดเจน

> **ใช้ binary โดยตรงหรือ?** มันทำงานได้ทันทีโดยไม่ต้องใช้ flag ใด ๆ -- binary จะ spoof ทุกอย่างโดยอัตโนมัติ ส่ง `--fingerprint=seed` เพื่อให้ได้อัตลักษณ์ที่คงอยู่ หรือใช้ flag ที่ระบุชัดเจน เช่น `--fingerprint-gpu-renderer` เพื่อ override ค่าที่สร้างอัตโนมัติใด ๆ

### Flag เพิ่มเติม

รองรับโดย binary แต่ **ไม่ได้ตั้งเป็นค่าเริ่มต้น** — ส่งผ่าน `args` เพื่อปรับแต่ง:

| Flag | ควบคุม |
|------|----------|
| `--fingerprint-gpu-vendor` | WebGL `UNMASKED_VENDOR_WEBGL` (สร้างอัตโนมัติจาก seed + แพลตฟอร์ม) |
| `--fingerprint-gpu-renderer` | WebGL `UNMASKED_RENDERER_WEBGL` (สร้างอัตโนมัติจาก seed + แพลตฟอร์ม) |
| `--fingerprint-hardware-concurrency` | `navigator.hardwareConcurrency` (สร้างอัตโนมัติ: `8`) |
| `--fingerprint-device-memory` | `navigator.deviceMemory` หน่วยเป็น GB (สร้างอัตโนมัติ: `8`) |
| `--fingerprint-screen-width` | ความกว้างหน้าจอ (สร้างอัตโนมัติ: `1920` Win/Linux, `1440` macOS) |
| `--fingerprint-screen-height` | ความสูงหน้าจอ (สร้างอัตโนมัติ: `1080` Win/Linux, `900` macOS) |
| `--fingerprint-brand` | แบรนด์เบราว์เซอร์: `Chrome`, `Edge`, `Opera`, `Vivaldi` |
| `--fingerprint-brand-version` | เวอร์ชันแบรนด์ (UA + Client Hints) |
| `--fingerprint-platform-version` | เวอร์ชันแพลตฟอร์มของ Client Hints |
| `--fingerprint-location` | พิกัด Geolocation |
| `--fingerprint-timezone` | เขตเวลา (เช่น `America/New_York`) |
| `--fingerprint-locale` | Locale (เช่น `en-US`) |
| `--fingerprint-storage-quota` | override storage quota หน่วยเป็น MB — มีผลต่อ `storage.estimate()`, `storageBuckets` และ webkit API รุ่นเก่า จะถูกปรับให้เป็นมาตรฐานอัตโนมัติเมื่อตั้งค่า `--fingerprint` |
| `--fingerprint-taskbar-height` | override ความสูงของแถบงาน (ค่าเริ่มต้นของ binary: Win=48, Mac=95, Linux=0) |
| `--fingerprint-fonts-dir` | พาธไปยังไดเรกทอรีที่มีฟอนต์ของแพลตฟอร์มเป้าหมาย (ดู [การตั้งค่าฟอนต์บน Linux](#font-setup-on-linux)) |
| `--fingerprint-webrtc-ip` | การแทนที่ IP ของ WebRTC ICE candidate ใช้ `auto` เพื่อแก้ค่าจาก IP ขาออกของพร็อกซี (จะทำการเรียก HTTP ผ่านพร็อกซี) หรือส่ง IP ที่ระบุชัดเจน จะถูก inject อัตโนมัติเมื่อ `geoip=True` |
| `--fingerprint-noise=false` | ปิดการ inject noise (canvas, WebGL, เสียง, client rects) ขณะที่ยังคงเปิดใช้งาน fingerprint seed แบบ deterministic อยู่ |
| `--enable-blink-features=FakeShadowRoot` | เข้าถึงเอลิเมนต์ closed shadow DOM |

> **หมายเหตุ:** การทดสอบ stealth ทั้งหมดได้รับการตรวจสอบด้วยการกำหนดค่า fingerprint เริ่มต้นข้างต้น การเปลี่ยน flag เหล่านี้อาจส่งผลต่อผลลัพธ์การตรวจจับ — ทดสอบการกำหนดค่าของคุณก่อนนำไปใช้ในโปรดักชัน

<a id="font-setup-on-linux"></a>

### การตั้งค่าฟอนต์บน Linux

**จำเป็นสำหรับไซต์ที่มีการตรวจจับบอทเชิงรุก (Kasada, Akamai)** ระบบเหล่านี้จะเรนเดอร์ emoji บน canvas ที่ซ่อนอยู่ แล้ว hash ผลลัพธ์พิกเซลออกมา สภาพแวดล้อม Linux แบบมินิมอล (Docker, cloud VM) มักไม่มี emoji และฟอนต์ส่วนขยาย ทำให้ได้ hash ที่ไม่ตรงกับเบราว์เซอร์จริงใด ๆ ติดตั้งแพ็กเกจฟอนต์มาตรฐานเพื่อแก้ปัญหานี้:

```bash
sudo apt install -y fonts-noto-color-emoji fonts-freefont-ttf fonts-unifont \
    fonts-ipafont-gothic fonts-wqy-zenhei fonts-tlwg-loma-otf
```

อิมเมจ Docker (`cloakhq/cloakbrowser`) มาพร้อมกับสิ่งเหล่านี้ที่ติดตั้งไว้ล่วงหน้าแล้ว หากคุณรัน binary โดยตรงบนเซิร์ฟเวอร์ Linux หรือในอิมเมจ Docker แบบกำหนดเอง ให้ติดตั้งด้วยตนเอง

**ทางเลือก: ฟอนต์ Windows สำหรับการแจกแจงฟอนต์ของ CreepJS** แพ็กเกจข้างต้นแก้ปัญหาการตรวจสอบ canvas ของระบบ anti-bot ได้ แต่จะไม่ช่วยปรับปรุงคะแนนฟอนต์ CreepJS ของคุณ สำหรับสิ่งนั้น คุณต้องใช้ฟอนต์ Windows จริง (Segoe UI, Calibri, Bahnschrift ฯลฯ) จากไดเรกทอรี `C:\Windows\Fonts\` ของเครื่อง Windows — `ttf-mscorefonts-installer` มีเพียงฟอนต์ยุค XP เก่า ๆ เท่านั้น และไม่เพียงพอ

```bash
mkdir -p ~/.local/share/fonts/windows
cp /path/to/windows/fonts/*.ttf ~/.local/share/fonts/windows/
cp /path/to/windows/fonts/*.TTF ~/.local/share/fonts/windows/
fc-cache -f  # mandatory for manually copied fonts
```

```python
browser = launch(
    args=["--fingerprint-fonts-dir=/home/user/.local/share/fonts/windows"],
)
```

### ตัวอย่าง

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

## ตัวอย่าง

**Python** — ดูที่ [`examples/`](examples/):
- [`basic.py`](examples/basic.py) — เปิดเบราว์เซอร์และโหลดหน้าเว็บ
- [`persistent_context.py`](examples/persistent_context.py) — persistent profile พร้อมการเก็บรักษา cookie/localStorage
- [`recaptcha_score.py`](examples/recaptcha_score.py) — ตรวจสอบคะแนน reCAPTCHA v3 ของคุณ
- [`stealth_test.py`](examples/stealth_test.py) — ทดสอบกับเว็บตรวจจับ 6 แห่ง
- [`fingerprint_scan_test.py`](examples/fingerprint_scan_test.py) — ทดสอบกับ fingerprint-scan.com และ CreepJS

**JavaScript** — ดูที่ [`js/examples/`](js/examples/):
- [`basic-playwright.ts`](js/examples/basic-playwright.ts) — เปิดและโหลดด้วย Playwright
- [`basic-puppeteer.ts`](js/examples/basic-puppeteer.ts) — เปิดและโหลดด้วย Puppeteer
- [`stealth-test.ts`](js/examples/stealth-test.ts) — ทดสอบกับเว็บตรวจจับ 6 แห่ง

<a id="framework-integrations"></a>

### การผสานรวมกับเฟรมเวิร์ก

CloakBrowser ทำงานร่วมกับเฟรมเวิร์กใดก็ตามที่ใช้ Playwright หรือ Chromium:

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

> **Humanize ผ่าน CDP**: แพตช์ stealth fingerprint ทำงานโดยอัตโนมัติผ่าน CDP แต่ `humanize=True` เป็นฟีเจอร์ระดับ wrapper หากคุณเชื่อมต่อกับ CloakBrowser ผ่าน CDP จากสคริปต์แยกต่างหาก ให้ import ฟังก์ชันแพตช์เพื่อเพิ่มการทำให้เหมือนมนุษย์:
>
> ```js
> import { patchBrowser, resolveConfig } from 'cloakbrowser/human';
> patchBrowser(browser, resolveConfig('default'));
> ```

| เฟรมเวิร์ก | Stars | ภาษา | ตัวอย่าง |
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

### การผสานรวมกับการ Deploy

| แพลตฟอร์ม | ตัวอย่าง |
|----------|---------|
| [AWS Lambda](https://aws.amazon.com/lambda/) | [`aws_lambda/`](examples/integrations/aws_lambda/) — การ scrape แบบครั้งเดียวใน Lambda (container image) |

## แพลตฟอร์ม

| แพลตฟอร์ม | Chromium | แพตช์ | สถานะ |
|---|---|---|---|
| Linux x86_64 | 146 | 57 | ✅ ล่าสุด |
| Linux arm64 (RPi, Graviton) | 146 | 57 | ✅ ล่าสุด |
| macOS arm64 (Apple Silicon) | 145 | 26 | ✅ |
| macOS x86_64 (Intel) | 145 | 26 | ✅ |
| Windows x86_64 | 146 | 57 | ✅ ล่าสุด |

wrapper จะดาวน์โหลด binary ที่ถูกต้องสำหรับแพลตฟอร์มของคุณโดยอัตโนมัติ

**การเปิดใช้งานครั้งแรกบน macOS:** binary นี้ลงนามแบบ ad-hoc เมื่อรันครั้งแรก macOS Gatekeeper จะบล็อกมัน ให้คลิกขวาที่แอป → **Open** → คลิก **Open** ในกล่องโต้ตอบ ขั้นตอนนี้จำเป็นเพียงครั้งเดียวเท่านั้น

## Docker

อิมเมจที่สร้างไว้ล่วงหน้าบน Docker Hub — ไม่ต้องติดตั้ง ไม่ต้องตั้งค่า

### ทดสอบอย่างรวดเร็ว

```bash
docker run --rm cloakhq/cloakbrowser cloaktest
```

### รันสคริปต์

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

### โหมดเซิร์ฟเวอร์ CDP

เริ่มเบราว์เซอร์ stealth แบบถาวรและเชื่อมต่อกับมันจากระยะไกลผ่าน Chrome DevTools Protocol:

```bash
docker run -d --name cloak -p 127.0.0.1:9222:9222 cloakhq/cloakbrowser cloakserve
```

จากนั้นเชื่อมต่อจากเครื่อง host ของคุณ:

```python
from playwright.sync_api import sync_playwright

pw = sync_playwright().start()
browser = pw.chromium.connect_over_cdp("http://localhost:9222")
page = browser.new_page()
page.goto("https://example.com")
print(page.title())
browser.close()
```

ส่ง flag เพิ่มเติมไปยังเบราว์เซอร์:

```bash
# With proxy
docker run -d --name cloak -p 127.0.0.1:9222:9222 cloakhq/cloakbrowser \
  cloakserve --proxy-server=http://proxy:8080

# Headed mode (renders to Xvfb inside container)
docker run -d --name cloak -p 127.0.0.1:9222:9222 cloakhq/cloakbrowser \
  cloakserve --headless=false
```

หยุดเซิร์ฟเวอร์:

```bash
docker stop cloak && docker rm cloak
```

> **ความปลอดภัย:** CDP ให้การควบคุมเบราว์เซอร์อย่างเต็มที่ (รัน JS, อ่านหน้าเว็บ, เข้าถึงไฟล์)
> ตัวอย่างเหล่านี้ผูกกับ `127.0.0.1` ดังนั้นมีเพียงเครื่องของคุณเท่านั้นที่เชื่อมต่อได้ อย่าเปิดพอร์ต 9222
> สู่อินเทอร์เน็ตสาธารณะโดยไม่มีการยืนยันตัวตนเพิ่มเติม

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

**fingerprint seed แบบต่อการเชื่อมต่อ** — รันหลายตัวตนเบราว์เซอร์จากคอนเทนเนอร์เดียว แต่ละ seed ที่ไม่ซ้ำกันจะสร้างกระบวนการ Chrome แยกต่างหากพร้อม fingerprint ของตัวเอง:

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

query param ที่รองรับ: `fingerprint`, `timezone`, `locale`, `platform`, `platform-version`, `brand`, `brand-version`, `gpu-vendor`, `gpu-renderer`, `hardware-concurrency`, `device-memory`, `screen-width`, `screen-height`, `proxy`, `geoip` seed เดียวกันจะใช้กระบวนการเดิมซ้ำ (param ของการเชื่อมต่อแรกจะมีผล) ไม่มี seed = ใช้กระบวนการ default ที่ใช้ร่วมกัน (เข้ากันได้กับเวอร์ชันก่อนหน้า) ตรวจสอบกระบวนการที่ทำงานอยู่ได้ที่ `GET /` (คืนค่า JSON พร้อม PID, พอร์ต และจำนวนการเชื่อมต่อ)

**persistent profile** — mount volume เพื่อเก็บ cookie และ session ไว้ข้ามการรีสตาร์ทคอนเทนเนอร์:

```bash
docker run --rm -v ./my-profile:/profile cloakhq/cloakbrowser python -c "
from cloakbrowser import launch_persistent_context
ctx = launch_persistent_context('/profile')
page = ctx.new_page()
page.goto('https://example.com')
ctx.close()
"
```

รันอีกครั้งด้วย volume เดิม — cookie, localStorage และ cache จะถูกกู้คืนโดยอัตโนมัติ

**การใช้ทรัพยากร:** ~190MB RAM ขณะไม่ทำงาน, ~280MB เมื่อมี 3 แท็บ ~30MB ต่อแท็บที่เพิ่มขึ้น

### ขยายด้วยอิมเมจของคุณเอง

```dockerfile
FROM cloakhq/cloakbrowser
COPY your_script.py /app/
CMD ["python", "your_script.py"]
```

**การสร้างอิมเมจของคุณเองจาก pip** — ใช้ `python -m cloakbrowser install` เพื่อดาวน์โหลด binary ระหว่างการ build พร้อมแสดงความคืบหน้าให้เห็น:

```dockerfile
FROM python:3.12-slim
RUN pip install cloakbrowser && python -m cloakbrowser install
COPY your_script.py /app/
CMD ["python", "/app/your_script.py"]
```

**การ build จากซอร์สโค้ด** — มี [`Dockerfile`](Dockerfile) มาให้ด้วยหากคุณต้องการ build อิมเมจของคุณเอง:

```bash
docker build -t cloakbrowser .
```

CloakBrowser ทำงานได้เหมือนกันทั้งบนเครื่องโลคัล, ใน Docker และบน VPS โดยไม่ต้องตั้งค่าเฉพาะสภาพแวดล้อม

**หมายเหตุ:** หากคุณรัน CloakBrowser ภายในเว็บเซิร์ฟเวอร์ที่ใช้ uvloop (เช่น `uvicorn[standard]`) ให้ใช้ `--loop asyncio` เพื่อหลีกเลี่ยงปัญหา subprocess pipe ค้าง

## การแก้ไขปัญหา

---

### ยังถูกบล็อกบนเว็บไซต์ที่ป้องกันเข้มงวด (DataDome, Turnstile) อยู่ใช่ไหม?

บางเว็บไซต์ตรวจจับ headless mode ได้แม้จะใช้แพตช์ C++ ของเราแล้ว ให้รันใน **headed mode** พร้อมกับจอแสดงผลเสมือน:

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

วิธีนี้จะรันเบราว์เซอร์แบบ headed จริง ๆ ที่เรนเดอร์บนจอแสดงผลเสมือน โดยไม่ต้องใช้จอภาพจริง ใช้ร่วมกับ config ที่แนะนำด้านล่างเพื่อความเป็น stealth สูงสุด

---

### config ที่แนะนำสำหรับเว็บไซต์ที่มีระบบกันบอท

การถูกบล็อกส่วนใหญ่เกิดจากการขาดสามสิ่งนี้อย่างใดอย่างหนึ่ง ไม่ใช่จากการตรวจจับ fingerprint ของเบราว์เซอร์:

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

ถ้าพร็อกซีของคุณรองรับ SOCKS5 ให้ใช้มันเพื่อความเข้ากันได้ที่ดีกว่า — SOCKS5 ทันเนล TCP แบบดิบ จึงเลี่ยงปัญหา HTTP CONNECT ที่พร็อกซีบางตัวมีกับ HTTP/2:

```python
browser = launch(proxy="socks5://user:pass@proxy:1080", geoip=True, headless=False, humanize=True)
```

หากยังถูกบล็อกอยู่หลังจากนี้ ให้ตรวจสอบการตั้งค่าฟอนต์ด้านล่าง

---

### ถูกบล็อกบนเว็บไซต์ Kasada / Akamai ทั้งที่ config ถูกต้อง?

บนสภาพแวดล้อม Linux แบบ minimal การขาดแพ็กเกจฟอนต์ทำให้การเรนเดอร์อิโมจิบน canvas ผลิตค่าแฮชที่ระบบกันบอทไม่รู้จัก นี่คือสาเหตุที่พบบ่อยที่สุดของการถูกบล็อกบนเว็บไซต์ที่ป้องกันเข้มงวด หลังจากตั้งค่าพร็อกซี geoip และ headed mode ถูกต้องเรียบร้อยแล้ว

ติดตั้งแพ็กเกจฟอนต์ที่ระบุไว้ใน [การตั้งค่าฟอนต์บน Linux](#font-setup-on-linux) ด้านบน

---

### เว็บไซต์ challenge เซสชันใหม่ แต่ทำงานได้หลังเข้าครั้งแรก

บางเว็บไซต์ challenge ผู้เข้าชมครั้งแรกที่ไม่มีคุกกี้ผ่าน HTTP/2 ปัญหานี้เกิดกับเบราว์เซอร์ Chromium ทั้งหมด ไม่ใช่แค่ CloakBrowser ให้ใช้ persistent profile เพื่อ warm up คุกกี้หนึ่งครั้ง แล้วนำกลับมาใช้ซ้ำข้ามเซสชัน:

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

สำหรับกรณีการใช้งานแบบ stateless/ephemeral การใช้ `launch(args=["--disable-http2"])` จะบังคับให้ใช้ HTTP/1.1 ซึ่งเลี่ยงการ check นี้ ให้ใช้ flag นี้เฉพาะกับเว็บไซต์ที่จำเป็นต้องใช้เท่านั้น — ส่วนใหญ่ทำงานได้ดีกับ HTTP/2 ถ้าพร็อกซีของคุณรองรับ SOCKS5 ให้ใช้ `proxy="socks5://user:pass@host:port"` แทน — SOCKS5 เลี่ยง HTTP CONNECT ไปทั้งหมด

---

### มีบางอย่างไม่ทำงาน? ตรวจสอบให้แน่ใจว่าคุณใช้เวอร์ชันล่าสุด

เวอร์ชันเก่าอาจใช้ args ของ stealth ที่ล้าสมัย หรือดาวน์โหลด binary เวอร์ชันเก่ากว่า:
```bash
pip install -U cloakbrowser    # Python
npm install cloakbrowser@latest # JavaScript
docker pull cloakhq/cloakbrowser:latest  # Docker
```

---

### การดาวน์โหลด binary ล้มเหลว / timeout

ตั้งค่า URL ดาวน์โหลดแบบกำหนดเอง หรือใช้ binary ในเครื่อง:
```bash
export CLOAKBROWSER_BINARY_PATH=/path/to/your/chrome
```

---

### อัปเดตใหม่ทำให้บางอย่างพัง? ย้อนกลับไปเวอร์ชันก่อนหน้า

ติดตั้ง wrapper เวอร์ชันเฉพาะเพื่อ downgrade ทั้ง wrapper และ binary ที่มันดาวน์โหลด:
```bash
pip install cloakbrowser==0.3.21              # Python
npm install cloakbrowser@0.3.21               # JavaScript
docker pull cloakhq/cloakbrowser:0.3.21       # Docker
```
wrapper แต่ละเวอร์ชันจะ pin เวอร์ชัน binary ของตัวเอง ดังนั้นการ downgrade wrapper จะทำให้ได้ binary ที่ตรงกันโดยอัตโนมัติในการ launch ครั้งถัดไป

---

### macOS: "App is damaged" หรือ Gatekeeper บล็อกการ launch

binary นี้เซ็นแบบ ad-hoc macOS จะ quarantine ไฟล์ที่ดาวน์โหลดมา รันคำสั่งนี้หนึ่งครั้งเพื่อล้างมันออก:
```bash
xattr -cr ~/.cloakbrowser/chromium-*/Chromium.app
```

---

### "playwright install" กับ binary ของ CloakBrowser

คุณไม่จำเป็นต้องใช้ `playwright install chromium` CloakBrowser ดาวน์โหลด binary ของตัวเอง คุณต้องการเพียง system deps ของ Playwright เท่านั้น:
```bash
playwright install-deps chromium
```

---

### macOS: ถูกบล็อกบนบางเว็บไซต์ที่ผ่านได้บน Linux

โปรไฟล์ fingerprint ของ macOS มีความไม่สอดคล้องที่ทราบกันอยู่ ซึ่งการตรวจจับบอทที่เข้มงวดจับได้ ถ้าเว็บไซต์บล็อกคุณบน macOS แต่ทำงานได้บน Linux ให้สลับไปใช้โปรไฟล์ fingerprint ของ Windows โดยส่ง `stealth_args=False` และตั้งค่า `--fingerprint-platform=windows` ด้วยตนเอง พร้อมกับ GPU flags ที่ตรงกัน (ดูรายการ flag ทั้งหมดได้ที่ [การจัดการ Fingerprint](#fingerprint-management))

---

### เว็บไซต์ตรวจจับโหมด incognito / private browsing

โดยค่าเริ่มต้น `launch()` จะเปิด context แบบ incognito บางเว็บไซต์ลงโทษกรณีนี้ ให้ใช้ `launch_persistent_context()` เพื่อให้ได้โปรไฟล์จริงที่มีการคงคุกกี้ไว้:

```python
from cloakbrowser import launch_persistent_context

ctx = launch_persistent_context("./my-profile", headless=False)
```

ถ้าเว็บไซต์ยังตั้งค่าสถานะ incognito อยู่ ให้เพิ่ม storage quota เพื่อให้ดูเหมือนเซสชันการเรียกดูทั่วไป ดูรายละเอียดเกี่ยวกับผลกระทบต่อบริการตรวจจับต่าง ๆ ได้ที่ [การแลกเปลี่ยนเรื่อง storage quota](#launch_persistent_context)

---

### คะแนน reCAPTCHA v3 ต่ำ (0.1–0.3)

หลีกเลี่ยง `page.wait_for_timeout()` — มันส่งคำสั่งโปรโตคอล CDP ที่ reCAPTCHA ตรวจจับได้ ให้ใช้ native sleep แทน:

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

เคล็ดลับอื่น ๆ สำหรับการเพิ่มคะแนน reCAPTCHA ให้สูงสุด:
- **ลองใช้ backend Patchright** — ระงับสัญญาณ automation ของ CDP เพิ่มเติมที่เลเยอร์โปรโตคอลของ Playwright ติดตั้งด้วย `pip install cloakbrowser[patchright]` แล้วใช้ `launch(backend="patchright")` หรือตั้งค่า `CLOAKBROWSER_BACKEND=patchright` แบบ global หมายเหตุ: Patchright ทำให้การยืนยันตัวตนของพร็อกซีและ `add_init_script` ใช้งานไม่ได้ — ใช้มันก็ต่อเมื่อคุณยังเห็นคะแนนต่ำอยู่หลังจากลองทำตามขั้นตอนข้างต้นแล้วเท่านั้น
- **ใช้ Playwright ไม่ใช่ Puppeteer** — Puppeteer ส่งทราฟฟิกโปรโตคอล CDP มากกว่าซึ่ง reCAPTCHA ตรวจจับได้ ([รายละเอียด](#puppeteer))
- **ใช้ residential proxy** — datacenter IP จะถูกตั้งค่าสถานะจากชื่อเสียงของ IP ไม่ใช่จาก fingerprint ของเบราว์เซอร์
- **ใช้เวลาบนหน้าเว็บ 15 วินาทีขึ้นไป** ก่อนทริกเกอร์ reCAPTCHA — การเข้าชมสั้น ๆ ได้คะแนนต่ำกว่า
- **เว้นระยะคำขอ** — การเรียก `grecaptcha.execute()` ติด ๆ กันจากเซสชันเดียวกันจะถูกลงโทษ ให้รอ 30 วินาทีขึ้นไประหว่างหน้าที่มี reCAPTCHA
- **ใช้ fingerprint seed แบบคงที่** เพื่อให้มีอัตลักษณ์ของอุปกรณ์ที่สม่ำเสมอข้ามเซสชัน (ดู [การจัดการ Fingerprint](#fingerprint-management))
- **ใช้ `page.type()` แทน `page.fill()`** สำหรับการกรอกฟอร์ม — `fill()` ตั้งค่าโดยตรงโดยไม่มีเหตุการณ์ของแป้นพิมพ์ ซึ่งการวิเคราะห์พฤติกรรมของ reCAPTCHA ตั้งค่าสถานะไว้ ส่วน `type()` ที่มี delay จะจำลองการกดแป้นพิมพ์จริง:
  ```python
  page.type("#email", "user@example.com", delay=50)
  ```
- **ลดการเรียก `page.evaluate()`** ก่อนที่การ check ของ reCAPTCHA จะทำงาน — แต่ละครั้งจะส่งทราฟฟิก CDP

## FAQ

**Q: สิ่งนี้ถูกกฎหมายหรือไม่?**
A: CloakBrowser คือเบราว์เซอร์ที่สร้างบน Chromium แบบโอเพนซอร์ส เราไม่สนับสนุนการใช้งานที่ผิดกฎหมาย การทำงานอัตโนมัติกับระบบโดยไม่ได้รับอนุญาต, การยัดข้อมูลรับรอง (credential stuffing) และการใช้งานสร้างบัญชีในทางที่ผิด ถูกห้ามอย่างชัดเจน ดูข้อกำหนดฉบับเต็มได้ที่ [BINARY-LICENSE.md](https://github.com/CloakHQ/CloakBrowser/blob/main/BINARY-LICENSE.md)

**Q: สิ่งนี้แตกต่างจาก Camoufox อย่างไร?**
A: Camoufox แพตช์ Firefox ส่วนเราแพตช์ Chromium การใช้ Chromium หมายถึงการรองรับ Playwright แบบเนทีฟ, ระบบนิเวศที่ใหญ่กว่า และ TLS fingerprint ที่ตรงกับ Chrome จริง Camoufox กลับมาในช่วงต้นปี 2026 แต่ยังอยู่ในเบต้าที่ไม่เสถียร — ส่วน CloakBrowser พร้อมใช้งานในระดับโปรดักชัน

**Q: ในที่สุดเว็บตรวจจับจะจับสิ่งนี้ได้ไหม?**
A: เป็นไปได้ การตรวจจับบอทคือการแข่งขันแบบหนีไล่ แพตช์ในระดับซอร์สโค้ดตรวจจับได้ยากกว่าแพตช์ในระดับ config แต่ก็ไม่ใช่ว่าเป็นไปไม่ได้ เราคอยติดตามและอัปเดตอยู่เสมอเมื่อการตรวจจับมีการพัฒนา

**Q: ฉันใช้พร็อกซีของตัวเองได้ไหม?**
A: ได้ ส่ง `proxy="http://user:pass@host:port"` หรือ `proxy="socks5://user:pass@host:port"` ไปยัง `launch()` รองรับทั้งพร็อกซีแบบ HTTP และ SOCKS5 แบบเนทีฟ

## Roadmap

| ฟีเจอร์ | สถานะ |
|---------|--------|
| Linux x64 — Chromium 146 (57 patches) | ✅ ปล่อยแล้ว |
| macOS arm64/x64 — Chromium 145 (26 patches) | ✅ ปล่อยแล้ว |
| Windows x64 — Chromium 146 (57 patches) | ✅ ปล่อยแล้ว |
| รองรับ JavaScript/Puppeteer + Playwright | ✅ ปล่อยแล้ว |
| การหมุนเวียน Fingerprint ต่อเซสชัน | ✅ ปล่อยแล้ว |
| การหมุนเวียนพร็อกซีในตัว | 📋 วางแผนไว้ |

## Links

- 📋 **บันทึกการเปลี่ยนแปลง** — [CHANGELOG.md](CHANGELOG.md)
- 🌐 **เว็บไซต์** — [cloakbrowser.dev](https://cloakbrowser.dev)
- 🐛 **รายงานบั๊กและคำขอฟีเจอร์** — [GitHub Issues](https://github.com/CloakHQ/CloakBrowser/issues)
- 📦 **PyPI** — [pypi.org/project/cloakbrowser](https://pypi.org/project/cloakbrowser/)
- 📦 **npm** — [npmjs.com/package/cloakbrowser](https://www.npmjs.com/package/cloakbrowser)
- ☕ **สนับสนุน** — [ko-fi.com/cloakhq](https://ko-fi.com/cloakhq)
- 📧 **ติดต่อ** — cloakhq@pm.me

## Security

ทุกรีลีสได้รับการลงนามเพื่อการตรวจสอบห่วงโซ่อุปทาน (supply chain)

```bash
# Verify GPG signature (binary release tag)
gpg --keyserver keyserver.ubuntu.com --recv-keys C60C0DDC9D0DE2DD
git verify-tag chromium-v146.0.7680.177.3

# Verify GitHub binary attestation (Sigstore)
gh attestation verify cloakbrowser-linux-x64.tar.gz --repo CloakHQ/cloakbrowser

# Verify Docker image signature (Cosign/Sigstore)
cosign verify \
  --certificate-identity-regexp "https://github.com/CloakHQ/CloakBrowser/" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
  cloakhq/cloakbrowser:latest
```

## License

- **โค้ด wrapper** (รีโพนี้) — MIT ดู [LICENSE](https://github.com/CloakHQ/CloakBrowser/blob/main/LICENSE)
- **binary ของ CloakBrowser** (Chromium ที่คอมไพล์แล้ว) — ใช้งานได้ฟรี ห้ามแจกจ่ายซ้ำ ดู [BINARY-LICENSE.md](https://github.com/CloakHQ/CloakBrowser/blob/main/BINARY-LICENSE.md)

## Contributing

ยินดีรับ Issue และ PR หากมีบางอย่างไม่ทำงาน [เปิด issue](https://github.com/CloakHQ/CloakBrowser/issues) — เราตอบกลับอย่างรวดเร็ว

## Contributors

- [@evelaa123](https://github.com/evelaa123) — การจำลองพฤติกรรมแบบมนุษย์, persistent context, แก้ไขปัญหา Windows
- [@yahooguntu](https://github.com/yahooguntu) — persistent context
- [@kitiho](https://github.com/kitiho) — แก้ไขปัญหา null viewport
- [@eofreternal](https://github.com/eofreternal) — แก้ไขชนิดข้อมูลของ humanConfig, ชนิดข้อมูลตัวเลือกของเมธอดที่จำลองพฤติกรรมแบบมนุษย์
- [@manaskarra](https://github.com/manaskarra) — แก้ไขขอบเขต iframe สำหรับการกระทำในเฟรมที่จำลองพฤติกรรมแบบมนุษย์, การป้องกัน timeout ของ GeoIP
- [@Youhai020616](https://github.com/Youhai020616) — การบันทึก log การเข้ารหัสข้อมูลรับรองของ SOCKS5
- [@AlexTech314](https://github.com/AlexTech314) — การผสานรวมกับ AWS Lambda, การเสริมความแกร่งของ cold-start
- [@dgtlmoon](https://github.com/dgtlmoon) — การคืนทรัพยากร pw.stop() อย่างนุ่มนวล
- [@zackycodes](https://github.com/zackycodes) — การโหลดส่วนขยาย Chrome
- [@aaronjmars](https://github.com/aaronjmars) — แก้ไขด้านความปลอดภัย (shell injection, การอัปเดต dependency)
- [@Seryiza](https://github.com/Seryiza) — Nix/NixOS flake
- [@245678000000](https://github.com/245678000000) — การซิงค์ package-lock
- [@honor2030](https://github.com/honor2030) — การป้องกัน WebSocket origin ของ cloakserve, ตัวช่วยเปิดใช้งาน JS แบบ composable
- [@0xlally](https://github.com/0xlally) — รายงานด้านความปลอดภัย (cloakserve path traversal, การข้าม WebSocket origin)

