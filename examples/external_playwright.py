"""Compose cloakbrowser's launch args with your own Playwright instance.

Use this pattern when you already manage ``sync_playwright()`` yourself — for
example, when juggling multiple stealth backends inside one Playwright process,
or layering cloakbrowser on top of a modified Playwright build.

``build_launch_options()`` returns the kwargs dict that ``launch()`` would
forward to ``pw.chromium.launch(...)``. You stay in control of the Playwright
lifecycle.
"""

from cloakbrowser import build_launch_options
from playwright.sync_api import sync_playwright

print("Starting Playwright...", flush=True)
pw = sync_playwright().start()
try:
    opts = build_launch_options(headless=False)
    print(f"Launching stealth Chromium ({len(opts['args'])} args)...", flush=True)
    browser = pw.chromium.launch(**opts)
    page = browser.new_page()

    page.goto("https://example.com")
    print(f"Title: {page.title()}")
    print(f"URL: {page.url}")

    browser.close()
finally:
    pw.stop()

print("Done!")
