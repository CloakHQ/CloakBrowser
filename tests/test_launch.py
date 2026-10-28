"""Basic launch tests for cloakbrowser."""

import pytest
from cloakbrowser import (
    launch,
    launch_async,
    launch_context,
    launch_persistent_context,
    binary_info,
)
from cloakbrowser.config import get_chromium_version

pytestmark = pytest.mark.real_browser


@pytest.mark.parametrize("env", [None, "patchright"])
def test_removed_backend_kwarg_raises(env, monkeypatch):
    """The removed `backend` parameter raises a clear TypeError before any
    launch side effects, regardless of the (also removed) CLOAKBROWSER_BACKEND
    env var. Guards the patchright removal."""
    if env is None:
        monkeypatch.delenv("CLOAKBROWSER_BACKEND", raising=False)
    else:
        monkeypatch.setenv("CLOAKBROWSER_BACKEND", env)
    with pytest.raises(TypeError, match="backend"):
        launch(backend="patchright")
    with pytest.raises(TypeError, match="backend"):
        launch_context(backend="patchright")
    with pytest.raises(TypeError, match="backend"):
        launch_persistent_context("/tmp/cloakbrowser-test-profile", backend="patchright")


def test_binary_info(tmp_path, monkeypatch):
    """binary_info() returns expected structure.

    Isolate the cache dir: with no cached Pro binary present, binary_info reports
    the free base version. (Without isolation this reads the developer's real
    ~/.cloakbrowser, which may hold a cached Pro build and flip the version.)
    """
    monkeypatch.setenv("CLOAKBROWSER_CACHE_DIR", str(tmp_path))
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
