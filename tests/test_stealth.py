"""Stealth detection tests for cloakbrowser.

These tests verify that the stealth Chromium binary passes common
bot detection checks. They require network access.
"""

import os
import time

import pytest
from cloakbrowser import launch

PROXY = os.environ.get("CLOAKBROWSER_TEST_PROXY")


@pytest.fixture(scope="module")
def browser():
    """Shared browser instance for stealth tests."""
    b = launch(headless=True, proxy=PROXY)
    yield b
    b.close()


@pytest.fixture
def page(browser):
    """Fresh page for each test."""
    p = browser.new_page()
    yield p
    p.close()


class TestWebDriverDetection:
    """Tests for WebDriver/automation detection signals."""

    def test_navigator_webdriver_false(self, page):
        """navigator.webdriver must be false."""
        page.goto("https://example.com")
        assert page.evaluate("navigator.webdriver") is False

    def test_no_headless_chrome_ua(self, page):
        """User agent must not contain 'HeadlessChrome'."""
        page.goto("https://example.com")
        ua = page.evaluate("navigator.userAgent")
        assert "HeadlessChrome" not in ua
        assert "Chrome/" in ua

    def test_window_chrome_exists(self, page):
        """window.chrome must be an object (not undefined)."""
        page.goto("https://example.com")
        assert page.evaluate("typeof window.chrome") == "object"

    def test_plugins_present(self, page):
        """Must have browser plugins (real Chrome has 5)."""
        page.goto("https://example.com")
        count = page.evaluate("navigator.plugins.length")
        assert count >= 5, f"Expected 5+ plugins (real Chrome), got {count}"

    def test_languages_present(self, page):
        """navigator.languages must be populated."""
        page.goto("https://example.com")
        langs = page.evaluate("navigator.languages")
        assert len(langs) >= 1

    def test_cdp_not_detected(self, page):
        """Chrome DevTools Protocol should not be detectable."""
        page.goto("https://example.com")
        # Common CDP detection: check for Runtime.evaluate artifacts
        has_cdp = page.evaluate("""
            () => {
                try {
                    // Check common CDP leak: window.cdc_
                    const keys = Object.keys(window);
                    return keys.some(k => k.startsWith('cdc_') || k.startsWith('__webdriver'));
                } catch(e) {
                    return false;
                }
            }
        """)
        assert has_cdp is False


class TestBotDetectionSites:
    """Live tests against bot detection services.

    These require network access and may be slow.
    Mark with pytest -m slow to skip in CI.
    """

    @pytest.mark.slow
    def test_bot_sannysoft(self, page):
        """bot.sannysoft.com — all checks should pass (0 failures)."""
        page.goto("https://bot.sannysoft.com", wait_until="networkidle", timeout=30000)
        time.sleep(3)

        results = page.evaluate("""() => {
            const rows = document.querySelectorAll('table tr');
            const failed = [];
            let total = 0;
            rows.forEach(r => {
                const cells = r.querySelectorAll('td');
                if (cells.length >= 2) {
                    total++;
                    const cls = cells[1].className || '';
                    if (cls.includes('failed')) {
                        failed.push(cells[0].innerText.trim());
                    }
                }
            });
            return {total, failed};
        }""")

        failed = results["failed"]
        assert len(failed) == 0, f"Sannysoft failures: {', '.join(failed)}"

    @pytest.mark.slow
    def test_bot_incolumitas(self, page):
        """bot.incolumitas.com — max 1 failure (WEBDRIVER false positive expected)."""
        page.goto("https://bot.incolumitas.com", wait_until="networkidle", timeout=30000)
        time.sleep(12)

        # Known acceptable failures (not browser fingerprint issues):
        # - WEBDRIVER: spec-level false positive across all builds
        # - connectionRTT: detects datacenter/proxy network latency, not browser
        KNOWN_ACCEPTABLE = {"WEBDRIVER", "connectionRTT"}

        results = page.evaluate("""() => {
            const text = document.body.innerText;
            const okMatches = text.match(/"\\w+":\\s*"OK"/g) || [];
            const failMatches = text.match(/"\\w+":\\s*"FAIL"/g) || [];
            const failedTests = failMatches.map(m => m.match(/"(\\w+)"/)[1]);
            return {passed: okMatches.length, failed: failMatches.length, failedTests};
        }""")

        failed_names = results["failedTests"]
        real_failures = [f for f in failed_names if f not in KNOWN_ACCEPTABLE]
        assert len(real_failures) == 0, f"Incolumitas unexpected failures: {', '.join(real_failures)}"

    @pytest.mark.slow
    def test_browserscan(self, page):
        """BrowserScan bot detection — 0 abnormal checks."""
        page.goto("https://www.browserscan.net/bot-detection", wait_until="networkidle", timeout=30000)
        time.sleep(5)

        results = page.evaluate("""() => {
            const text = document.body.innerText;
            const normalMatches = text.match(/Normal/g);
            const abnormalMatches = text.match(/Abnormal/g);
            return {
                normal: normalMatches ? normalMatches.length : 0,
                abnormal: abnormalMatches ? abnormalMatches.length : 0
            };
        }""")

        assert results["abnormal"] == 0, \
            f"BrowserScan: {results['abnormal']} abnormal, {results['normal']} normal"

    @pytest.mark.slow
    def test_device_and_browser_info(self, page):
        """deviceandbrowserinfo.com — isBot must be false."""
        page.goto("https://deviceandbrowserinfo.com/are_you_a_bot", wait_until="domcontentloaded", timeout=30000)
        time.sleep(8)

        results = page.evaluate("""() => {
            const text = document.body.innerText;
            const botMatch = text.match(/"isBot":\\s*(true|false)/);
            const isBot = botMatch ? botMatch[1] === 'true' : null;
            const checks = {};
            ['isBot', 'hasBotUserAgent', 'hasWebdriverTrue', 'isHeadlessChrome',
             'isAutomatedWithCDP', 'hasSuspiciousWeakSignals', 'isPlaywright',
             'hasInconsistentChromeObject'].forEach(p => {
                const match = text.match(new RegExp('"' + p + '":\\s*(true|false)'));
                if (match) checks[p] = match[1] === 'true';
            });
            return {isBot, checks};
        }""")

        assert results["isBot"] is False, f"Detected as bot! Checks: {results['checks']}"

    @pytest.mark.slow
    def test_fingerprintjs(self, page):
        """FingerprintJS — must not be blocked, should see flight data."""
        page.goto("https://demo.fingerprint.com/web-scraping", wait_until="domcontentloaded", timeout=30000)
        time.sleep(8)

        try:
            page.click("button:has-text('Search')", timeout=5000)
            time.sleep(5)
        except Exception:
            pass

        results = page.evaluate("""() => {
            const text = document.body.innerText;
            const hasFlights = text.includes('Price per adult') || text.includes('$');
            const isBlocked = text.includes('request was blocked') || text.includes('bot visit detected');
            return {passed: hasFlights && !isBlocked, isBlocked, hasFlights};
        }""")

        assert not results["isBlocked"], "FingerprintJS blocked us as a bot"
        assert results["passed"], "FingerprintJS: no flight data shown"

    @pytest.mark.slow
    def test_recaptcha_v3(self, page):
        """reCAPTCHA v3 — score must be >= 0.7."""
        page.goto(
            "https://recaptcha-demo.appspot.com/recaptcha-v3-request-scores.php",
            wait_until="domcontentloaded",
            timeout=60000,
        )
        time.sleep(8)

        results = page.evaluate("""() => {
            const text = document.body.innerText;
            const scoreMatch = text.match(/"score":\\s*(\\d+\\.\\d+)/);
            return {score: scoreMatch ? parseFloat(scoreMatch[1]) : null};
        }""")

        score = results["score"]
        assert score is not None, "Could not extract reCAPTCHA score"
        assert score >= 0.7, f"reCAPTCHA score too low: {score}"
