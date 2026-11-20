"""Shared pytest fixtures."""

import time

import pytest

_ORIGINAL_SLEEP = time.sleep


@pytest.fixture(autouse=True)
def restore_time_sleep():
    """Mocked launches are rarely closed, which would leave time.sleep patched
    for every later test. Drop all tracked sync browsers after each test."""
    yield
    from cloakbrowser import browser

    browser._sleep_owners.clear()
    time.sleep = _ORIGINAL_SLEEP


@pytest.fixture(autouse=True)
def isolated_cache_dir(request, tmp_path_factory, monkeypatch):
    """Keep the suite away from the developer's real ``~/.cloakbrowser``.

    A ``license.key`` (or a cached Pro version marker) in the real cache dir
    would skip the no-key claim flow and point at the developer's cached
    builds — tests then assert against whatever the developer happens to have
    installed. ``monkeypatch``
    means a test setting its own ``CLOAKBROWSER_CACHE_DIR`` still wins.

    Real-browser tests (``slow`` / ``real_browser``) opt out and run like a user
    machine: the developer's key and latest binary, at a stable path. A fresh
    temp cache per test re-downloads the binary every test, and its new
    path re-prompts path-keyed firewalls (LuLu) since the binary is ad-hoc signed.
    """
    if request.node.get_closest_marker("slow") or request.node.get_closest_marker("real_browser"):
        return
    monkeypatch.setenv(
        "CLOAKBROWSER_CACHE_DIR",
        str(tmp_path_factory.mktemp("cloakbrowser-cache")),
    )
