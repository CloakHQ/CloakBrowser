"""Integration tests for connect() / connect_async().

Strategy: start the CloakBrowser binary directly with a remote-debugging port
(the same thing cloakserve does under the hood), then connect() back to it over
CDP. This exercises the full wrapper path — endpoint -> connect_over_cdp -> no
viewport -> humanize -> close cleanup — with no Pro license and no live sites.
"""

import json
import socket
import subprocess
import time
import urllib.request

import pytest

from cloakbrowser import connect, connect_async
from cloakbrowser.download import ensure_binary

pytest.importorskip("playwright", reason="connect() requires playwright")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _remote_alive(port: int) -> bool:
    try:
        urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=1
        ).close()
        return True
    except Exception:
        return False


def _wait_for_cdp(port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _remote_alive(port):
            return
        time.sleep(0.25)
    raise RuntimeError(f"CDP endpoint on :{port} not ready within {timeout}s")


@pytest.fixture
def cdp(tmp_path):
    """Start the binary with a debug port; yield (http_endpoint, port)."""
    binary = ensure_binary()
    port = _free_port()
    proc = subprocess.Popen(
        [
            str(binary),
            "--headless=new",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={tmp_path / 'profile'}",
            "--no-first-run",
            "--no-default-browser-check",
            "--no-sandbox",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        _wait_for_cdp(port)
        yield f"http://127.0.0.1:{port}", port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_connect_returns_usable_browser(cdp):
    endpoint, _ = cdp
    browser = connect(endpoint)
    try:
        assert browser.is_connected()
        page = browser.new_page()
        page.goto("data:text/html,<title>hi</title>")
        assert page.title() == "hi"
    finally:
        browser.close()


def test_connect_humanize_patches_pages(cdp):
    endpoint, _ = cdp
    browser = connect(endpoint, humanize=True)
    try:
        page = browser.new_page()
        # patch_page tags humanized pages with `_original`.
        assert hasattr(page, "_original")
    finally:
        browser.close()


def test_connect_default_no_viewport(cdp):
    endpoint, _ = cdp
    browser = connect(endpoint)  # default_no_viewport=True
    try:
        assert browser.new_page().viewport_size is None
    finally:
        browser.close()

    browser = connect(endpoint, default_no_viewport=False)
    try:
        assert browser.new_page().viewport_size is not None
    finally:
        browser.close()


def test_close_detaches_without_killing_remote(cdp):
    endpoint, port = cdp
    browser = connect(endpoint)
    browser.new_page().goto("data:text/html,x")
    browser.close()
    assert not browser.is_connected()
    # close() detaches our driver; the remote instance keeps running.
    assert _remote_alive(port)


async def test_connect_async(cdp):
    endpoint, _ = cdp
    browser = await connect_async(endpoint)
    try:
        assert browser.is_connected()
        page = await browser.new_page()
        await page.goto("data:text/html,<title>hey</title>")
        assert await page.title() == "hey"
    finally:
        await browser.close()
