"""Basic launch tests for cloakbrowser."""

import pytest
from cloakbrowser import launch, launch_async, binary_info
from cloakbrowser.config import get_chromium_version


def test_binary_info():
    """binary_info() returns expected structure."""
    info = binary_info()
    assert "version" in info
    assert "platform" in info
    assert "binary_path" in info
    assert "installed" in info
    assert info["version"] == get_chromium_version()


def test_launch_and_close():
    """Can launch browser and close it."""
    browser = launch(headless=True)
    assert browser.is_connected()
    browser.close()


def test_launch_new_page():
    """Can create a page and navigate."""
    browser = launch(headless=True)
    page = browser.new_page()
    page.goto("https://example.com")
    assert "Example Domain" in page.title()
    browser.close()


def test_launch_with_extra_args():
    """Can pass extra Chrome args."""
    browser = launch(headless=True, args=["--disable-gpu"])
    page = browser.new_page()
    page.goto("https://example.com")
    assert page.title()
    browser.close()


def test_webdriver_flag():
    """navigator.webdriver should be false (patched)."""
    browser = launch(headless=True)
    page = browser.new_page()
    page.goto("https://example.com")
    webdriver = page.evaluate("navigator.webdriver")
    assert webdriver is False, f"navigator.webdriver should be false, got {webdriver}"
    browser.close()


def test_chrome_object_exists():
    """window.chrome should exist (Playwright leaks undefined)."""
    browser = launch(headless=True)
    page = browser.new_page()
    page.goto("https://example.com")
    chrome_exists = page.evaluate("typeof window.chrome")
    assert chrome_exists == "object", f"window.chrome should be 'object', got '{chrome_exists}'"
    browser.close()


def test_plugins_count():
    """navigator.plugins should have entries (Playwright has 0)."""
    browser = launch(headless=True)
    page = browser.new_page()
    page.goto("https://example.com")
    plugins = page.evaluate("navigator.plugins.length")
    assert plugins > 0, f"Expected plugins > 0, got {plugins}"
    browser.close()


@pytest.mark.asyncio
async def test_launch_async():
    """Async launch works."""
    browser = await launch_async(headless=True)
    assert browser.is_connected()
    page = await browser.new_page()
    await page.goto("https://example.com")
    title = await page.title()
    assert "Example Domain" in title
    await browser.close()
