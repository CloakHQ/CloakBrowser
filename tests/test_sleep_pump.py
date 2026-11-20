"""time.sleep() while a sync browser is open waits inside Playwright's event loop."""

import asyncio
import threading
import time
from unittest.mock import MagicMock, patch

import cloakbrowser.browser as b
from cloakbrowser import launch


class FakeOwner:
    """Stands in for a sync Browser/BrowserContext: _sync runs the coroutine."""

    def __init__(self):
        self.calls = 0

    def _sync(self, coro):
        self.calls += 1
        return asyncio.run(coro)


def test_long_sleep_runs_in_playwright_loop():
    owner = FakeOwner()
    b._track_sleep_owner(owner)
    with patch.object(b, "_real_sleep") as real:
        time.sleep(0.1)
    assert owner.calls == 1
    real.assert_not_called()


def test_short_sleep_keeps_real_sleep():
    owner = FakeOwner()
    b._track_sleep_owner(owner)
    with patch.object(b, "_real_sleep") as real:
        time.sleep(0.05)
    assert owner.calls == 0
    real.assert_called_once_with(0.05)


def test_other_thread_keeps_real_sleep():
    owner = FakeOwner()
    b._track_sleep_owner(owner)
    with patch.object(b, "_real_sleep") as real:
        t = threading.Thread(target=time.sleep, args=(0.2,))
        t.start()
        t.join()
    assert owner.calls == 0
    real.assert_called_once_with(0.2)


def test_untrack_restores_time_sleep():
    owner = FakeOwner()
    b._track_sleep_owner(owner)
    assert time.sleep is b._pumping_sleep
    b._untrack_sleep_owner(owner)
    assert time.sleep is b._real_sleep


def test_dead_loop_falls_back_to_real_sleep(caplog):
    owner = MagicMock()
    owner._sync.side_effect = _closed_loop
    b._track_sleep_owner(owner)
    with patch.object(b, "_real_sleep") as real:
        time.sleep(0.3)
    real.assert_called_once_with(0.3)
    assert "Event loop is closed" in caplog.text
    assert b._sleep_owners == {}  # the dead owner was dropped


def _closed_loop(coro):
    coro.close()
    raise RuntimeError("Event loop is closed")


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("playwright.sync_api.sync_playwright")
def test_launch_tracks_until_close(mock_sync_playwright, _):
    mock_pw = MagicMock()
    mock_sync_playwright.return_value.start.return_value = mock_pw
    browser = launch()
    assert time.sleep is b._pumping_sleep
    browser.close()
    assert time.sleep is b._real_sleep
