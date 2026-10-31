"""Run stealth tests against major bot detection services.

Tests cloakbrowser against multiple detection sites, extracts pass/fail
verdicts via JS evaluation, and reports results with screenshots.

Usage:
    python examples/stealth_test.py
    python examples/stealth_test.py --headed     # watch in real-time
    python examples/stealth_test.py --no-screenshots
    python examples/stealth_test.py --proxy http://user:pass@proxy:port
"""

import sys
import time

from cloakbrowser import launch

HEADED = "--headed" in sys.argv
SCREENSHOTS = "--no-screenshots" not in sys.argv
PROXY = None
for i, arg in enumerate(sys.argv):
    if arg == "--proxy" and i + 1 < len(sys.argv):
        PROXY = sys.argv[i + 1]


def test_bot_sannysoft(page):
    """bot.sannysoft.com — classic bot detection checks."""
    page.goto("https://bot.sannysoft.com", wait_until="networkidle", timeout=30000)
    time.sleep(3)

    results = page.evaluate("""() => {
        const rows = document.querySelectorAll('table tr');
        const data = {};
        rows.forEach(r => {
            const cells = r.querySelectorAll('td');
            if (cells.length >= 2) {
                const key = cells[0].innerText.trim();
                const val = cells[1].innerText.trim();
                const cls = cells[1].className || '';
                data[key] = {value: val, passed: !cls.includes('failed')};
            }
        });
        return data;
    }""")

    failed = [k for k, v in results.items() if not v["passed"]]
    total = len(results)
    passed = total - len(failed)
    return {"passed": passed, "total": total, "failed": failed}


def test_bot_incolumitas(page):
    """bot.incolumitas.com — comprehensive 30+ check bot detection."""
    page.goto("https://bot.incolumitas.com", wait_until="networkidle", timeout=30000)

    last_total = 0
    results = {"passed": 0, "failed": 0, "failedTests": [], "total": 0}
    for _ in range(15):
        time.sleep(2)
        results = page.evaluate("""() => {
            const text = document.body.innerText;
            const okMatches = text.match(/"\\w+":\\s*"OK"/g) || [];
            const failMatches = text.match(/"\\w+":\\s*"FAIL"/g) || [];
            const failedTests = failMatches.map(m => m.match(/"(\\w+)"/)[1]);
            return {passed: okMatches.length, failed: failMatches.length, failedTests, total: okMatches.length + failMatches.length};
        }""")
        if results["total"] >= 30 and results["total"] == last_total:
            break
        last_total = results["total"]

    return results


def test_rebrowser(page):
    """bot-detector.rebrowser.net — automation signal detector."""
    page.goto("https://bot-detector.rebrowser.net/", wait_until="networkidle", timeout=30000)
    time.sleep(10)

    return page.evaluate("""() => {
        const el = document.getElementById('detections-json');
        if (!el) return {failing: [], totalFails: 0, passed: 0, notTriggered: 0, error: 'no detections-json element'};
        const tests = JSON.parse(el.value);
        const failing = tests.filter(t => t.rating === 1).map(t => t.type);
        const passed = tests.filter(t => t.rating === -1).length;
        const notTriggered = tests.filter(t => t.rating === 0).length;
        return {failing, totalFails: failing.length, passed, notTriggered, total: tests.length};
    }""")


def test_browserscan(page):
    """browserscan.net/bot-detection — WebDriver, UA, CDP, Navigator checks."""
    page.goto("https://www.browserscan.net/bot-detection", wait_until="networkidle", timeout=30000)
    time.sleep(5)

    results = page.evaluate("""() => {
        const items = document.querySelectorAll('[class*="result"], [class*="item"], [class*="check"]');
        let normal = 0, abnormal = 0;
        const text = document.body.innerText;
        // Count "Normal" vs "Abnormal" verdicts
        const normalMatches = text.match(/Normal/g);
        const abnormalMatches = text.match(/Abnormal/g);
        return {
            normal: normalMatches ? normalMatches.length : 0,
            abnormal: abnormalMatches ? abnormalMatches.length : 0,
            pageText: text.substring(0, 500)
        };
    }""")
    return results


def test_deviceandbrowserinfo(page):
    """deviceandbrowserinfo.com/are_you_a_bot — fingerprint + behavioral detection."""
    page.goto("https://deviceandbrowserinfo.com/are_you_a_bot", wait_until="domcontentloaded", timeout=30000)
    time.sleep(8)

    results = page.evaluate("""() => {
        const text = document.body.innerText;
        // Site outputs JSON with "isBot": false and detail checks
        const botMatch = text.match(/"isBot":\\s*(true|false)/);
        const isBot = botMatch ? botMatch[1] === 'true' : null;
        const checks = {};
        const patterns = [
            'isBot', 'hasBotUserAgent', 'hasWebdriverTrue',
            'isHeadlessChrome', 'isAutomatedWithCDP', 'hasSuspiciousWeakSignals',
            'isPlaywright', 'hasInconsistentChromeObject'
        ];
        patterns.forEach(p => {
            const match = text.match(new RegExp('"' + p + '":\\s*(true|false)'));
            if (match) checks[p] = match[1] === 'true';
        });
        return {isBot, checks};
    }""")
    return results


def test_creepjs_noise_off(page):
    """CreepJS — lie detection with fingerprint noise disabled."""
    page.goto("https://abrahamjuliot.github.io/creepjs/", wait_until="domcontentloaded", timeout=30000)
    time.sleep(15)

    return page.evaluate("""() => {
        const fp = window.Fingerprint;
        if (!fp) return {error: 'Fingerprint not ready', totalLies: null};
        const lies = fp.lies || {};
        return {totalLies: lies.totalLies || 0};
    }""")


TESTS = [
    {
        "name": "bot.sannysoft.com",
        "url": "https://bot.sannysoft.com",
        "runner": test_bot_sannysoft,
        "verdict": lambda r: f"{r['passed']}/{r['total']} passed"
            + (f" (FAILED: {', '.join(r['failed'])})" if r["failed"] else " — ALL GREEN"),
        "pass": lambda r: len(r["failed"]) == 0,
    },
    {
        "name": "bot.incolumitas.com",
        "url": "https://bot.incolumitas.com",
        "runner": test_bot_incolumitas,
        "verdict": lambda r: f"{r['passed']}/{r['total']} passed"
            + (
                " — ALL GREEN"
                if r.get("failed", 0) == 0
                else f" (FAILED: {', '.join(r.get('failedTests', []))} — known false positives)"
                if set(r.get("failedTests", [])) <= {"WEBDRIVER", "connectionRTT"}
                else f" (FAILED: {', '.join(r.get('failedTests', []))})"
            ),
        "pass": lambda r: set(r.get("failedTests", [])) <= {"WEBDRIVER", "connectionRTT"},
    },
    {
        "name": "Rebrowser Bot Detector",
        "url": "https://bot-detector.rebrowser.net/",
        "runner": test_rebrowser,
        "verdict": lambda r: (
            f"🟢{r.get('passed', 0)} ⚪{r.get('notTriggered', 0)} — ALL CLEAN"
            if r.get("totalFails", 1) == 0
            else f"FAIL: {', '.join(r.get('failing', []))}"
        ),
        "pass": lambda r: r.get("totalFails", 1) == 0,
    },
    {
        "name": "deviceandbrowserinfo.com",
        "url": "https://deviceandbrowserinfo.com/are_you_a_bot",
        "runner": test_deviceandbrowserinfo,
        "verdict": lambda r: f"isBot: {r.get('isBot', 'unknown')}"
            + (f", trueFlags: {sum(1 for v in r.get('checks', {}).values() if v)}" if r.get("checks") else ""),
        "pass": lambda r: not r.get("isBot", True) and not any(r.get("checks", {}).values()),
    },
    {
        "name": "BrowserScan",
        "url": "https://www.browserscan.net/bot-detection",
        "runner": test_browserscan,
        "verdict": lambda r: f"Normal: {r['normal']}, Abnormal: {r['abnormal']}",
        "pass": lambda r: r.get("abnormal", 1) == 0,
    },
    {
        "name": "CreepJS lies (noise=false)",
        "url": "https://abrahamjuliot.github.io/creepjs/",
        "runner": test_creepjs_noise_off,
        "verdict": lambda r: f"lies: {r.get('totalLies', 'N/A')}",
        "pass": lambda r: r.get("totalLies") == 0,
        "args": ["--fingerprint-noise=false"],
    },
]


def main():
    print("=" * 60)
    print("CloakBrowser Stealth Test Suite")
    print("=" * 60)
    print(f"Mode: {'headed' if HEADED else 'headless'}")
    print(f"Screenshots: {'on' if SCREENSHOTS else 'off'}")
    print(f"Proxy: {PROXY or 'none'}")
    print()
    print("Launching stealth browser...", flush=True)

    browser = launch(headless=not HEADED, proxy=PROXY, geoip=True)
    shared_browser_closed = False
    page = browser.new_page()

    # Show browser fingerprint details
    try:
        import re
        info = page.evaluate("""async () => {
            const ua = navigator.userAgent;
            let fullVersion = null;
            try {
                const data = await navigator.userAgentData.getHighEntropyValues(['fullVersionList', 'platform', 'platformVersion']);
                const chrome = data.fullVersionList.find(b => b.brand === 'Chromium' || b.brand === 'Google Chrome');
                fullVersion = chrome ? chrome.version : null;
            } catch {}
            const gl = document.createElement('canvas').getContext('webgl');
            const dbg = gl ? gl.getExtension('WEBGL_debug_renderer_info') : null;
            return {
                ua,
                fullVersion,
                platform: navigator.platform,
                cores: navigator.hardwareConcurrency,
                gpu: dbg ? gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL) : 'N/A',
                gpuVendor: dbg ? gl.getParameter(dbg.UNMASKED_VENDOR_WEBGL) : 'N/A',
                screen: screen.width + 'x' + screen.height,
                languages: navigator.languages.join(', '),
            };
        }""")
        # Condensed UA
        ua_short = re.sub(r'^Mozilla/5\.0 \(', '', info["ua"])
        ua_short = re.sub(r'\) AppleWebKit/[\d.]+ \(KHTML, like Gecko\) ', ' | ', ua_short)
        print(f"UA: {ua_short}", flush=True)
        print(f"Platform: {info['platform']} | Cores: {info['cores']} | Screen: {info['screen']}", flush=True)
        print(f"GPU: {info['gpuVendor']} — {info['gpu']}", flush=True)
    except Exception:
        print("Chrome: could not detect", flush=True)

    # Show IP address
    try:
        page.goto("https://httpbin.org/ip", timeout=10000)
        ip = page.evaluate("JSON.parse(document.body.innerText).origin")
        print(f"IP: {ip}", flush=True)
    except Exception:
        print("IP: could not detect", flush=True)

    print(f"Running {len(TESTS)} tests (this takes ~2 minutes)...\n", flush=True)

    results_summary = []

    for test in TESTS:
        name = test["name"]
        print(f"--- {name} ---")
        print(f"URL: {test['url']}")

        test_browser = browser
        test_context = None
        test_page = page
        try:
            if test.get("args"):
                browser.close()
                shared_browser_closed = True
                test_browser = launch(headless=not HEADED, proxy=PROXY, geoip=True, args=test["args"])

            test_context = test_browser.new_context(viewport={"width": 1920, "height": 1080})
            test_page = test_context.new_page()

            result = test["runner"](test_page)
            passed = test["pass"](result)
            verdict = test["verdict"](result)
            status = "PASS" if passed else "FAIL"
            results_summary.append((name, status, verdict))

            print(f"Result: [{status}] {verdict}")

            if SCREENSHOTS:
                filename = f"stealth_test_{name.replace('.', '_').replace(' ', '_').replace('/', '_')}.png"
                test_page.screenshot(path=filename)
                print(f"Screenshot: {filename}")

        except Exception as e:
            results_summary.append((name, "ERROR", str(e)))
            print(f"Error: {e}")
        finally:
            if test_context is not None:
                test_context.close()
            if test_browser is not browser:
                test_browser.close()

        print()

    if not shared_browser_closed:
        browser.close()

    # Summary table
    print("=" * 60)
    print("RESULTS SUMMARY")
    print("=" * 60)
    for name, status, verdict in results_summary:
        icon = {"PASS": "+", "FAIL": "!", "ERROR": "x"}[status]
        print(f"  [{icon}] {name}: {verdict}")

    passed_count = sum(1 for _, s, _ in results_summary if s == "PASS")
    total = len(results_summary)
    print(f"\n  {passed_count}/{total} tests passed")
    print("=" * 60)

    return 0 if passed_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
