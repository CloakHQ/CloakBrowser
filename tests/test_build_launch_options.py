"""Unit tests for build_launch_options and external humanize helpers."""

import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cloakbrowser.config import IGNORE_DEFAULT_ARGS


def test_build_launch_options_preserves_current_launch_behaviour():
    """build_launch_options includes the current launch() pre-launch steps."""
    from cloakbrowser.browser import build_launch_options

    proxy_option = {"server": "http://proxy:8080"}
    launch_env = {"CUSTOM": "1", "CLOAKBROWSER_LICENSE_KEY": "cb_key"}

    with (
        patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome") as mock_ensure,
        patch(
            "cloakbrowser.browser.maybe_resolve_geoip",
            return_value=("Europe/Berlin", "de-DE", "5.6.7.8"),
        ) as mock_geoip,
        patch(
            "cloakbrowser.browser._resolve_proxy_config",
            return_value=({"proxy": proxy_option}, ["--proxy-server=http://proxy:8080"]),
        ) as mock_proxy,
        patch("cloakbrowser.browser.binary_supports_maximized_window", return_value=True) as mock_maximized,
        patch("cloakbrowser.browser.build_launch_env", return_value=launch_env) as mock_env,
        patch("cloakbrowser.browser._maybe_warn_windows_fonts") as mock_font_warning,
    ):
        opts = build_launch_options(
            headless=False,
            proxy="http://proxy:8080",
            args=["--custom-flag"],
            stealth_args=False,
            timezone="America/New_York",
            locale="en-US",
            geoip=True,
            extension_paths=["/tmp/ext"],
            license_key="cb_key",
            browser_version="148.0.7778.215.4",
            env={"CUSTOM": "1"},
            timeout=1234,
        )

    assert opts["executable_path"] == "/fake/chrome"
    assert opts["headless"] is False
    assert opts["ignore_default_args"] == IGNORE_DEFAULT_ARGS
    assert opts["proxy"] is proxy_option
    assert opts["env"] == launch_env
    assert opts["timeout"] == 1234
    assert "--custom-flag" in opts["args"]
    assert "--proxy-server=http://proxy:8080" in opts["args"]
    assert "--fingerprint-webrtc-ip=5.6.7.8" in opts["args"]
    assert "--fingerprint-timezone=Europe/Berlin" in opts["args"]
    assert "--lang=de-DE" in opts["args"]
    assert "--fingerprint-locale=de-DE" in opts["args"]
    assert "--start-maximized" in opts["args"]

    mock_ensure.assert_called_once_with(
        license_key="cb_key",
        browser_version="148.0.7778.215.4",
    )
    mock_geoip.assert_called_once_with(True, "http://proxy:8080", "America/New_York", "en-US")
    mock_proxy.assert_called_once_with("http://proxy:8080", "148.0.7778.215.4", "cb_key")
    mock_maximized.assert_called_once_with("cb_key", "148.0.7778.215.4")
    mock_env.assert_called_once_with("cb_key", user_env={"CUSTOM": "1"})
    mock_font_warning.assert_called_once_with(opts["args"])


def test_build_launch_options_threads_suppress_maximize():
    """_suppress_maximize disables --start-maximized even on supporting binaries."""
    from cloakbrowser.browser import build_launch_options

    with (
        patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome"),
        patch("cloakbrowser.browser.binary_supports_maximized_window", return_value=True),
        patch("cloakbrowser.browser.build_launch_env", return_value=None),
        patch("cloakbrowser.browser._maybe_warn_windows_fonts"),
    ):
        opts = build_launch_options(stealth_args=False, _suppress_maximize=True)

    assert "--start-maximized" not in opts["args"]


def test_build_launch_options_removed_backend_raises():
    """Removed kwargs still fail before any launch side effects."""
    from cloakbrowser.browser import build_launch_options

    with pytest.raises(TypeError, match="backend"):
        build_launch_options(backend="patchright")


def test_humanize_browser_patches_existing_browser():
    """humanize_browser resolves config and patches the passed sync browser."""
    from cloakbrowser.browser import humanize_browser

    browser = object()
    cfg = object()
    overrides = {"typing_delay": 12}

    with (
        patch("cloakbrowser.human.config.resolve_config", return_value=cfg) as mock_resolve,
        patch("cloakbrowser.human.patch_browser") as mock_patch,
    ):
        humanize_browser(browser, human_preset="careful", human_config=overrides)

    mock_resolve.assert_called_once_with("careful", overrides)
    mock_patch.assert_called_once_with(browser, cfg)


def test_humanize_browser_async_patches_existing_browser():
    """humanize_browser_async resolves config and patches the passed async browser."""
    from cloakbrowser.browser import humanize_browser_async

    browser = object()
    cfg = object()
    overrides = {"typing_delay": 12}

    with (
        patch("cloakbrowser.human.config.resolve_config", return_value=cfg) as mock_resolve,
        patch("cloakbrowser.human.patch_browser_async") as mock_patch,
    ):
        humanize_browser_async(browser, human_preset="careful", human_config=overrides)

    mock_resolve.assert_called_once_with("careful", overrides)
    mock_patch.assert_called_once_with(browser, cfg)


def test_launch_delegates_to_build_launch_options_and_humanize_browser():
    """launch forwards build_launch_options output directly to Playwright."""
    from cloakbrowser.browser import launch

    launch_opts = {
        "executable_path": "/fake/chrome",
        "headless": True,
        "args": ["--custom-flag"],
        "ignore_default_args": IGNORE_DEFAULT_ARGS,
        "timeout": 1234,
    }
    browser = MagicMock()
    pw = MagicMock()
    pw.chromium.launch.return_value = browser
    launcher = MagicMock()
    launcher.start.return_value = pw
    overrides = {"typing_delay": 12}
    sync_api = types.ModuleType("playwright.sync_api")
    sync_api.sync_playwright = MagicMock(return_value=launcher)
    playwright = types.ModuleType("playwright")
    playwright.sync_api = sync_api

    with (
        patch.dict(sys.modules, {"playwright": playwright, "playwright.sync_api": sync_api}),
        patch("cloakbrowser.browser.build_launch_options", return_value=launch_opts) as mock_build,
        patch("cloakbrowser.browser.binary_supports_headless_no_viewport", return_value=False),
        patch("cloakbrowser.browser.humanize_browser") as mock_humanize,
    ):
        result = launch(
            headless=True,
            proxy="http://proxy:8080",
            args=["--custom-flag"],
            stealth_args=False,
            timezone="Europe/Berlin",
            locale="de-DE",
            geoip=True,
            humanize=True,
            human_preset="careful",
            human_config=overrides,
            extension_paths=["/tmp/ext"],
            license_key="cb_key",
            browser_version="148.0.7778.215.4",
            _suppress_maximize=True,
            timeout=1234,
        )

    mock_build.assert_called_once_with(
        headless=True,
        proxy="http://proxy:8080",
        args=["--custom-flag"],
        stealth_args=False,
        timezone="Europe/Berlin",
        locale="de-DE",
        geoip=True,
        extension_paths=["/tmp/ext"],
        license_key="cb_key",
        browser_version="148.0.7778.215.4",
        _suppress_maximize=True,
        timeout=1234,
    )
    pw.chromium.launch.assert_called_once_with(**launch_opts)
    mock_humanize.assert_called_once_with(browser, "careful", overrides)
    assert result is browser


@pytest.mark.asyncio
async def test_launch_async_delegates_to_build_launch_options():
    """launch_async forwards build_launch_options output directly to Playwright."""
    from cloakbrowser.browser import launch_async

    launch_opts = {
        "executable_path": "/fake/chrome",
        "headless": True,
        "args": ["--custom-flag"],
        "ignore_default_args": IGNORE_DEFAULT_ARGS,
        "timeout": 1234,
    }
    browser = AsyncMock()
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    pw.stop = AsyncMock()
    launcher = MagicMock()
    launcher.start = AsyncMock(return_value=pw)
    async_api = types.ModuleType("playwright.async_api")
    async_api.async_playwright = MagicMock(return_value=launcher)
    playwright = types.ModuleType("playwright")
    playwright.async_api = async_api

    with (
        patch.dict(sys.modules, {"playwright": playwright, "playwright.async_api": async_api}),
        patch("cloakbrowser.browser.build_launch_options", return_value=launch_opts) as mock_build,
        patch("cloakbrowser.browser.binary_supports_headless_no_viewport", return_value=False),
    ):
        result = await launch_async(
            headless=True,
            proxy="http://proxy:8080",
            args=["--custom-flag"],
            stealth_args=False,
            timezone="Europe/Berlin",
            locale="de-DE",
            geoip=True,
            extension_paths=["/tmp/ext"],
            license_key="cb_key",
            browser_version="148.0.7778.215.4",
            timeout=1234,
        )

    mock_build.assert_called_once_with(
        headless=True,
        proxy="http://proxy:8080",
        args=["--custom-flag"],
        stealth_args=False,
        timezone="Europe/Berlin",
        locale="de-DE",
        geoip=True,
        extension_paths=["/tmp/ext"],
        license_key="cb_key",
        browser_version="148.0.7778.215.4",
        _suppress_maximize=False,
        timeout=1234,
    )
    pw.chromium.launch.assert_awaited_once_with(**launch_opts)
    assert result is browser
