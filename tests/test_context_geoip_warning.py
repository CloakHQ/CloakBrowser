"""Warnings for geoip=True with per-context proxies."""

import warnings
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class _FakeBrowser:
    def __init__(self):
        self.contexts = []
        self.new_context_calls = []
        self.close_calls = 0

    def new_context(self, *args, **kwargs):
        self.new_context_calls.append((args, kwargs))
        return object()

    def close(self):
        self.close_calls += 1


class _FakeAsyncBrowser:
    def __init__(self):
        self.contexts = []
        self.new_context_calls = []
        self.close_calls = 0

    async def new_context(self, *args, **kwargs):
        self.new_context_calls.append((args, kwargs))
        return object()

    async def close(self):
        self.close_calls += 1


def _sync_playwright_factory(browser):
    playwright = MagicMock()
    playwright.chromium.launch.return_value = browser
    starter = MagicMock()
    starter.start.return_value = playwright
    return lambda: starter


def test_geoip_context_proxy_warns_once():
    from cloakbrowser.browser import launch

    browser = _FakeBrowser()
    with patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome"):
        with patch(
            "cloakbrowser.browser._import_sync_playwright",
            return_value=_sync_playwright_factory(browser),
        ):
            launched = launch(geoip=True)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        launched.new_context(proxy={"server": "http://proxy-1:8080"})
        launched.new_context(proxy={"server": "http://proxy-2:8080"})

    assert len(caught) == 1
    assert "geoip=True was set at browser launch" in str(caught[0].message)
    assert "browser.new_context()" in str(caught[0].message)


@pytest.mark.asyncio
async def test_geoip_context_proxy_warns_once_async():
    from cloakbrowser.browser import launch_async

    browser = _FakeAsyncBrowser()
    playwright = MagicMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)

    class _Starter:
        async def start(self):
            return playwright

    with patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome"):
        with patch("cloakbrowser.browser._import_async_playwright", return_value=lambda: _Starter()):
            launched = await launch_async(geoip=True)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        await launched.new_context(proxy={"server": "http://proxy-1:8080"})
        await launched.new_context(proxy={"server": "http://proxy-2:8080"})

    assert len(caught) == 1
    assert "geoip=True was set at browser launch" in str(caught[0].message)
    assert "browser.new_context()" in str(caught[0].message)


@pytest.mark.asyncio
async def test_geoip_launch_proxy_without_context_proxy_is_quiet_async():
    from cloakbrowser.browser import launch_async

    browser = _FakeAsyncBrowser()
    playwright = MagicMock()
    playwright.chromium.launch = AsyncMock(return_value=browser)

    class _Starter:
        async def start(self):
            return playwright

    with patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome"):
        with patch(
            "cloakbrowser.browser.maybe_resolve_geoip",
            return_value=("Europe/Berlin", "de-DE", "5.6.7.8"),
        ):
            with patch("cloakbrowser.browser._import_async_playwright", return_value=lambda: _Starter()):
                launched = await launch_async(proxy="http://proxy:8080", geoip=True)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        await launched.new_context()

    assert caught == []
