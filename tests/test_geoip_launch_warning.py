import logging
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cloakbrowser import launch, launch_async


WARNING = (
    "geoip=True without proxy= at launch — timezone/locale will default to "
    "UTC/en-US. Per-context proxies don't trigger geoip resolution. Pass "
    "proxy= to launch() or set explicit timezone=/locale=."
)


def _mock_sync_playwright():
    browser = MagicMock()
    pw = MagicMock()
    pw.chromium.launch.return_value = browser
    pw_cm = MagicMock()
    pw_cm.start.return_value = pw
    return pw_cm


def _mock_async_playwright():
    browser = MagicMock()
    browser.close = AsyncMock()
    pw = MagicMock()
    pw.stop = AsyncMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    pw_cm = MagicMock()
    pw_cm.start = AsyncMock(return_value=pw)
    return pw_cm


def _sync_playwright_modules(pw_cm):
    playwright = ModuleType("playwright")
    sync_api = ModuleType("playwright.sync_api")
    sync_api.sync_playwright = MagicMock(return_value=pw_cm)
    return {"playwright": playwright, "playwright.sync_api": sync_api}


def _async_playwright_modules(pw_cm):
    playwright = ModuleType("playwright")
    async_api = ModuleType("playwright.async_api")
    async_api.async_playwright = MagicMock(return_value=pw_cm)
    return {"playwright": playwright, "playwright.async_api": async_api}


def test_warns_when_geoip_true_and_no_launch_proxy(caplog):
    caplog.set_level(logging.WARNING, logger="cloakbrowser")
    pw_cm = _mock_sync_playwright()

    with patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome"):
        with patch("cloakbrowser.browser.maybe_resolve_geoip", return_value=(None, None, None)):
            with patch.dict("sys.modules", _sync_playwright_modules(pw_cm)):
                launch(geoip=True, stealth_args=False)

    assert any(record.getMessage() == WARNING for record in caplog.records)


def test_does_not_warn_when_launch_proxy_is_set(caplog):
    caplog.set_level(logging.WARNING, logger="cloakbrowser")
    pw_cm = _mock_sync_playwright()

    with patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome"):
        with patch("cloakbrowser.browser.maybe_resolve_geoip", return_value=(None, None, None)):
            with patch.dict("sys.modules", _sync_playwright_modules(pw_cm)):
                launch(
                    geoip=True,
                    proxy="http://example.com:8080",
                    stealth_args=False,
                )

    assert all(record.getMessage() != WARNING for record in caplog.records)


@pytest.mark.asyncio
async def test_launch_async_warns_when_geoip_true_and_no_launch_proxy(caplog):
    caplog.set_level(logging.WARNING, logger="cloakbrowser")
    pw_cm = _mock_async_playwright()

    with patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome"):
        with patch("cloakbrowser.browser.maybe_resolve_geoip", return_value=(None, None, None)):
            with patch.dict("sys.modules", _async_playwright_modules(pw_cm)):
                await launch_async(geoip=True, stealth_args=False)

    assert any(record.getMessage() == WARNING for record in caplog.records)
