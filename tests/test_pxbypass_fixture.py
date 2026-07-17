"""Issue #448 regression: load a PX press-and-hold fixture and verify the
bypass detects it, finds the button, holds the mouse for >3.5s, and the
challenge disappears (the page exposes #px-captcha with 'Activate and hold').

This is a true end-to-end smoke test that does NOT depend on PerimeterX's
network or the iFood/Walmart IP-rating flow.  Run:

    pytest tests/test_pxbypass_fixture.py -q -s

The bypass fires the moment the page loads (5.6s end-to-end in the manual
run), so we install a JS observer that captures the bypass's detection /
solve signals from the page side and assert the page state was reached.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from cloakbrowser import launch
from cloakbrowser.pxbypass import PxConfig, detect_px
from cloakbrowser.pxbypass.engine import PxEngine


FIXTURE = Path(__file__).parent / "fixtures" / "px_challenge.html"


def _new_browser(headless: bool, *, max_attempts: int = 1):
    return launch(
        headless=headless,
        bypass_px=True,
        px_config=PxConfig(
            max_attempts=max_attempts,
            hold_min=4.0,
            hold_max=5.0,
            post_wait=2.0,
            button_wait_timeout=10.0,
        ),
    )


def test_fixture_page_loads_with_challenge():
    """Sanity: the fixture actually serves a visible #px-captcha with the
    expected text so we know any failure in the real test is bypass code,
    not test-fixture setup."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        # Use system Chromium (not CloakBrowser) — fixture should be neutral
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(FIXTURE.as_uri(), wait_until="domcontentloaded")
            assert page.locator("#px-captcha").is_visible()
            text = page.evaluate("() => document.body.innerText")
            assert "activate and hold" in text.lower()
            assert page.locator("#hold-btn").is_visible()
        finally:
            browser.close()


def _exercise_bypass(headless: bool) -> dict:
    """Drive CloakBrowser against the fixture, return a small report dict.

    The bypass solves the challenge in ~5.5s end-to-end: detection fires
    from the JS observer the moment the page loads, button is found, mouse
    moves to it via Bezier trajectory, mousedown for 4.0s, mouseup, page
    flips to "Success".  We assert on the side-effects, not the snapshot.
    """
    browser = _new_browser(headless)
    try:
        page = browser.new_page()
        # Install a recorder BEFORE goto so we capture every mouse event
        # the bypass produces on the actual button.
        page.add_init_script(
            """
            window.__pxTrace = { events: [], success: false };
            const rec = (label) => (e) => {
              window.__pxTrace.events.push({
                type: label,
                x: e.clientX, y: e.clientY,
                target: e.target && (e.target.tagName + (e.target.id ? '#' + e.target.id : '')),
                ts: Date.now(),
              });
            };
            const obs = new MutationObserver(() => {
              if (document.getElementById('ok')) {
                window.__pxTrace.success = true;
                obs.disconnect();
              }
            });
            document.addEventListener('DOMContentLoaded', () => {
              obs.observe(document.body, { childList: true, subtree: true });
              const btn = document.getElementById('hold-btn');
              if (btn) {
                ['mousedown', 'mouseup', 'click'].forEach(t =>
                  btn.addEventListener(t, rec(t), { capture: true }));
              }
            });
            """
        )
        page.goto(FIXTURE.as_uri(), wait_until="domcontentloaded")
        t0 = time.monotonic()
        try:
            page.wait_for_selector("#ok", timeout=20_000)
        except Exception:
            pass
        duration = time.monotonic() - t0
        trace = page.evaluate("() => window.__pxTrace || {}")
        return {
            "duration": duration,
            "cleared": page.locator("#ok").count() > 0,
            "trace": trace,
        }
    finally:
        browser.close()


def test_bypass_dismisses_fixture_challenge():
    """End-to-end: load the fixture, let the bypass take over, assert the
    page flipped to "Success — captcha cleared" with a real press-and-hold
    on the button (≥1 mousedown + 1 mouseup on BUTTON#hold-btn ≥3s apart)."""
    report = _exercise_bypass(headless=True)
    print("fixture smoke report:", json.dumps(report, indent=2, default=str))
    assert report["cleared"] is True, (
        f"challenge not cleared within 20s; bypass probably never solved it. "
        f"duration={report['duration']:.2f}s trace={report['trace']!r}"
    )
    events = report["trace"].get("events", [])
    mousedowns = [e for e in events if e["type"] == "mousedown"
                  and e.get("target") == "BUTTON#hold-btn"]
    mouseups = [e for e in events if e["type"] == "mouseup"
                and e.get("target") == "BUTTON#hold-btn"]
    assert len(mousedowns) >= 1, (
        f"no mousedown on the hold button; bypass aimed somewhere else. "
        f"events={events!r}"
    )
    assert len(mouseups) >= 1, (
        f"no mouseup on the hold button; bypass never released. events={events!r}"
    )
    held_ms = mouseups[0]["ts"] - mousedowns[0]["ts"]
    assert held_ms >= 3500, (
        f"hold too short: {held_ms}ms; PX requires ~3.5s+ to register a real "
        f"press. events={events!r}"
    )
