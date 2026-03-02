"""Test against fingerprint-scan.com and CreepJS.

Tests the specific headless detection signals flagged by the community:
- noTaskbar, noContentIndex, noContactsManager, noDownlinkMax
- Bot risk score (fingerprint-scan.com)
- Headless/stealth percentages (CreepJS)
- Full CreepJS signal breakdown (likeHeadless, headless, stealth)

Usage:
    python examples/fingerprint_scan_test.py
    python examples/fingerprint_scan_test.py --proxy http://10.50.96.5:8888
    python examples/fingerprint_scan_test.py --headless
"""

import sys
import time

from cloakbrowser import launch_context

HEADLESS = "--headless" in sys.argv
PROXY = None
for i, arg in enumerate(sys.argv):
    if arg == "--proxy" and i + 1 < len(sys.argv):
        PROXY = sys.argv[i + 1]


def test_fingerprint_scan(page):
    """fingerprint-scan.com — bot risk score + headless detection signals."""
    print("=== fingerprint-scan.com ===")
    page.goto("https://fingerprint-scan.com/", wait_until="domcontentloaded", timeout=30000)
    time.sleep(20)  # Castle.js needs time to compute score

    # Check bot risk score
    score = page.evaluate(
        'document.getElementById("fingerprintScore")?.textContent || "Score not rendered"'
    )
    print(f"Bot Risk Score: {score}")

    # Check headless detection signals
    apis = page.evaluate("""() => ({
        noTaskbar: screen.height === screen.availHeight,
        taskbarSize: screen.height - screen.availHeight,
        noContentIndex: typeof window.ContentIndex === "undefined",
        noContactsManager: !("contacts" in navigator),
        noDownlinkMax: !("downlinkMax" in (navigator.connection || {})),
        downlinkMax: navigator.connection?.downlinkMax ?? null,
        timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        webdriver: navigator.webdriver,
        isPlaywright: "__pwInitScripts" in window || "__playwright__binding__" in window,
        webgpu: typeof navigator.gpu !== "undefined" ? "available" : "NOT_AVAILABLE",
        scrollbarWidth: (() => { const d = document.createElement("div"); d.style.cssText = "overflow:scroll;width:100px;height:100px;position:absolute;top:-999px"; document.body.appendChild(d); const w = d.offsetWidth - d.clientWidth; d.remove(); return w; })()
    })""")

    print("\nHeadless detection signals:")
    headless_fails = 0
    for k, v in apis.items():
        is_fail = k.startswith("no") and v is True
        if is_fail:
            headless_fails += 1
        flag = "FAIL" if is_fail else ""
        print(f"  {k}: {v}  {flag}")

    # Extract bot test results from page
    bot_tests = page.evaluate("""() => {
        const text = document.body.innerText;
        const tests = {};
        for (const key of ['WebDriver', 'Is Selenium Chrome', 'CDP Check', 'Is Playwright']) {
            const match = text.match(new RegExp(key + '\\\\s+(true|false)'));
            if (match) tests[key] = match[1];
        }
        return tests;
    }""")
    print("\nBot Detection Tests:")
    for k, v in bot_tests.items():
        status = "PASS" if v == "false" else "FAIL"
        print(f"  {k}: {v}  [{status}]")

    page.screenshot(path="/results/fingerprint-scan.png", full_page=True)
    print("\nScreenshot: /results/fingerprint-scan.png")

    return {
        "score": score,
        "headless_fails": headless_fails,
        "apis": apis,
        "bot_tests": bot_tests,
    }


def test_creepjs(page):
    """abrahamjuliot.github.io/creepjs — comprehensive fingerprint analysis."""
    print("\n=== CreepJS ===")
    page.goto(
        "https://abrahamjuliot.github.io/creepjs/", wait_until="domcontentloaded", timeout=30000
    )
    print("Waiting 30s for CreepJS analysis...")
    time.sleep(30)

    # Extract % scores from page text (matches test-infra/matrix_tests/group3_bot_detection.py)
    scores = page.evaluate("""() => {
        const text = document.body.innerText;
        const likeMatch = text.match(/(\\d+)%\\s*like headless/i);
        const headlessMatch = text.match(/(\\d+)%\\s*headless:/i);
        const stealthMatch = text.match(/(\\d+)%\\s*stealth:/i);
        return {
            likeHeadlessPct: likeMatch ? parseInt(likeMatch[1]) : null,
            headlessPct: headlessMatch ? parseInt(headlessMatch[1]) : null,
            stealthPct: stealthMatch ? parseInt(stealthMatch[1]) : null,
        };
    }""")

    print(f"\nScores:")
    print(f"  like-headless: {scores['likeHeadlessPct']}%  (target: <=30%)")
    print(f"  headless:      {scores['headlessPct']}%  (target: 0%)")
    print(f"  stealth:       {scores['stealthPct']}%  (target: 0%)")

    # Extract full signal breakdown from window.Fingerprint.headless (CreepJS internal object)
    signals = page.evaluate("""() => {
        try {
            const fp = window.Fingerprint;
            if (!fp || !fp.headless) return null;
            return {
                likeHeadless: fp.headless.likeHeadless || null,
                headless: fp.headless.headless || null,
                stealth: fp.headless.stealth || null,
            };
        } catch { return null; }
    }""")

    if signals:
        if signals.get("likeHeadless"):
            print("\nlikeHeadless signals:")
            fails = 0
            for k, v in signals["likeHeadless"].items():
                is_fail = v is True
                if is_fail:
                    fails += 1
                flag = " FAIL" if is_fail else ""
                print(f"  {k}: {v}{flag}")
            print(f"  ({fails} fails)")

        if signals.get("headless"):
            print("\nheadless signals:")
            for k, v in signals["headless"].items():
                flag = " FAIL" if v is True else ""
                print(f"  {k}: {v}{flag}")

        if signals.get("stealth"):
            print("\nstealth signals:")
            for k, v in signals["stealth"].items():
                flag = " FAIL" if v is True else ""
                print(f"  {k}: {v}{flag}")
    else:
        print("\n(window.Fingerprint.headless not available — signals not extracted)")

    # Extract platform estimate
    platform = page.evaluate("""() => {
        try {
            const fp = window.Fingerprint;
            if (!fp || !fp.platformEstimate) return null;
            return fp.platformEstimate;
        } catch { return null; }
    }""")
    if platform:
        print(f"\nPlatform estimate: {platform}")

    passed = (
        scores["headlessPct"] is not None
        and scores["headlessPct"] <= 30
        and scores["stealthPct"] is not None
        and scores["stealthPct"] <= 30
    )
    print(f"\nVerdict: {'PASS' if passed else 'FAIL'} (<=30% headless, <=30% stealth)")

    page.screenshot(path="/results/creepjs.png", full_page=True)
    print("Screenshot: /results/creepjs.png")

    return {**scores, "signals": signals, "platform": platform}


def main():
    print("=" * 60)
    print("CloakBrowser — Fingerprint & Headless Detection Tests")
    print("=" * 60)
    print(f"Mode: {'headless' if HEADLESS else 'headed'}")
    print(f"Proxy: {PROXY or 'none'}")
    print()

    context = launch_context(
        headless=HEADLESS,
        proxy=PROXY,
        args=[
            "--fingerprint-screen-width=1920",
            "--fingerprint-screen-height=1080",
            "--timezone=Asia/Jerusalem",
        ],
    )
    page = context.new_page()

    try:
        fp_result = test_fingerprint_scan(page)
        creep_result = test_creepjs(page)
    finally:
        context.close()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"fingerprint-scan.com: {fp_result['score']}")
    print(f"  Headless signal fails: {fp_result['headless_fails']}")
    like = creep_result["likeHeadlessPct"]
    headless = creep_result["headlessPct"]
    stealth = creep_result["stealthPct"]
    print(f"CreepJS: like-headless={like}%, headless={headless}%, stealth={stealth}%")

    # Count CreepJS signal fails
    sigs = creep_result.get("signals")
    if sigs and sigs.get("likeHeadless"):
        fail_names = [k for k, v in sigs["likeHeadless"].items() if v is True]
        if fail_names:
            print(f"  likeHeadless fails: {', '.join(fail_names)}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
