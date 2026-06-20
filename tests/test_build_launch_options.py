"""Unit tests for build_launch_options and external humanize helpers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cloakbrowser.config import IGNORE_DEFAULT_ARGS


def test_build_launch_options_schema():
    """build_launch_options returns Playwright launch kwargs."""
    from cloakbrowser.browser import build_launch_options

    with patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome"):
        opts = build_launch_options(
            headless=False,
            args=["--disable-gpu"],
            timezone="Europe/Berlin",
            locale="de-DE",
            downloads_path="/tmp/downloads",
        )

    assert opts["executable_path"] == "/fake/chrome"
    assert opts["headless"] is False
    assert opts["ignore_default_args"] == IGNORE_DEFAULT_ARGS
    assert opts["downloads_path"] == "/tmp/downloads"
    assert "--disable-gpu" in opts["args"]
    assert "--fingerprint-timezone=Europe/Berlin" in opts["args"]
    assert "--lang=de-DE" in opts["args"]
    assert "--fingerprint-locale=de-DE" in opts["args"]


def test_humanize_browser_patches_existing_browser():
    """humanize_browser resolves config and patches the passed sync browser."""
    from cloakbrowser.browser import humanize_browser

    browser = object()
    cfg = object()
    overrides = {"typing_delay": 12}

    with patch("cloakbrowser.human.config.resolve_config", return_value=cfg) as mock_resolve:
        with patch("cloakbrowser.human.patch_browser") as mock_patch:
            humanize_browser(browser, preset="careful", config=overrides)

    mock_resolve.assert_called_once_with("careful", overrides)
    mock_patch.assert_called_once_with(browser, cfg)


def test_humanize_browser_async_patches_existing_browser():
    """humanize_browser_async resolves config and patches the passed async browser."""
    from cloakbrowser.browser import humanize_browser_async

    browser = object()
    cfg = object()
    overrides = {"typing_delay": 12}

    with patch("cloakbrowser.human.config.resolve_config", return_value=cfg) as mock_resolve:
        with patch("cloakbrowser.human.patch_browser_async") as mock_patch:
            humanize_browser_async(browser, preset="careful", config=overrides)

    mock_resolve.assert_called_once_with("careful", overrides)
    mock_patch.assert_called_once_with(browser, cfg)


@pytest.mark.asyncio
async def test_launch_async_delegates_to_build_launch_options():
    """launch_async forwards build_launch_options output directly to Playwright."""
    from cloakbrowser.browser import launch_async

    launch_opts = {
        "executable_path": "/fake/chrome",
        "headless": False,
        "args": ["--disable-gpu"],
        "ignore_default_args": IGNORE_DEFAULT_ARGS,
        "downloads_path": "/tmp/downloads",
    }
    browser = AsyncMock()
    pw = AsyncMock()
    pw.chromium.launch.return_value = browser
    launcher = MagicMock()
    launcher.start = AsyncMock(return_value=pw)
    async_playwright = MagicMock(return_value=launcher)

    with patch("cloakbrowser.browser._import_async_playwright", return_value=async_playwright):
        with patch("cloakbrowser.browser.build_launch_options", return_value=launch_opts) as mock_build:
            result = await launch_async(
                headless=False,
                proxy="http://proxy:8080",
                args=["--disable-gpu"],
                stealth_args=False,
                timezone="Europe/Berlin",
                locale="de-DE",
                geoip=True,
                extension_paths=["/tmp/ext"],
                downloads_path="/tmp/downloads",
            )

    mock_build.assert_called_once_with(
        headless=False,
        proxy="http://proxy:8080",
        args=["--disable-gpu"],
        stealth_args=False,
        timezone="Europe/Berlin",
        locale="de-DE",
        geoip=True,
        extension_paths=["/tmp/ext"],
        downloads_path="/tmp/downloads",
    )
    pw.chromium.launch.assert_awaited_once_with(**launch_opts)
    assert result is browser
