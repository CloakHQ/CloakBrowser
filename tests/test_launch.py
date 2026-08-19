"""Basic launch tests for cloakbrowser."""

import os

import pytest
from cloakbrowser import (
    launch,
    launch_async,
    launch_chrome_direct,
    launch_context,
    launch_persistent_context,
    binary_info,
)
from cloakbrowser.config import get_chromium_version


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


def test_launch_chrome_direct_exposes_tcp_cdp(tmp_path, monkeypatch):
    """launch_chrome_direct() starts Chrome with a TCP remote-debugging port
    (not Playwright's pipe) and no --remote-debugging-pipe in argv.

    Regression for: the MCP browser runtime passed --remote-debugging-port
    through launch_persistent_context(), where Playwright injects
    --remote-debugging-pipe and manages the connection over it, leaving the TCP
    endpoint non-functional for external CDP clients.
    """
    import socket
    import subprocess

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    # Use the real binary (skip download/network checks)
    import cloakbrowser.download as download
    binary = download.ensure_binary()
    monkeypatch.setattr(download, "ensure_binary", lambda **kw: binary)

    proc = launch_chrome_direct(
        str(tmp_path / "profile"),
        host="127.0.0.1",
        port=port,
        headless=True,
        startup_timeout=45.0,
    )
    try:
        assert proc.poll() is None
        assert "--remote-debugging-pipe" not in proc_args(proc)
        # The TCP CDP endpoint must actually serve /json/version
        import urllib.request
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=5
        ) as resp:
            assert resp.status == 200
            body = resp.read().decode()
        assert "Chrome" in body
    finally:
        if proc.poll() is None:
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                capture_output=True,
            )
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass


def proc_args(proc) -> str:
    import subprocess
    res = subprocess.run(
        ["wmic", "process", "where", f"ProcessId={proc.pid}", "get", "CommandLine"],
        capture_output=True, text=True,
    )
    return res.stdout


def test_launch_chrome_direct_auto_delevate_always_on_windows(
    tmp_path, monkeypatch
):
    """On Windows the patched binary exits 0 on launch unless Chromium's
    AutoDeElevate feature is disabled. launch_chrome_direct() must always pass
    --disable-features including AutoDeElevate, even when the caller supplied
    their own --disable-features list or none at all.
    """
    if os.name != "nt":
        pytest.skip("Windows-only binary behavior")

    import cloakbrowser.download as download
    binary = download.ensure_binary()

    captured = {}

    def fake_popen(args, **kw):
        captured["args"] = args
        captured["kw"] = kw
        proc = object.__new__(type("FakeProc", (), {}))
        proc.pid = 12345
        proc.poll = lambda: None  # stays alive; no early-exit
        return proc

    import cloakbrowser.browser as browser_mod
    monkeypatch.setattr(browser_mod, "ensure_binary", lambda **kw: binary)

    import subprocess as _subprocess_mod
    import socket as _socket_mod

    monkeypatch.setattr(_subprocess_mod, "Popen", fake_popen)
    # Port connects immediately so we skip the wait loop
    def fake_connect(addr, timeout=1.0):
        class _FakeConn:
            def __enter__(self): return self
            def __exit__(self, *a): return False
        return _FakeConn()

    monkeypatch.setattr(_socket_mod, "create_connection", fake_connect)

    if os.name == "nt":
        # Case 1: no caller features — AutoDeElevate must be added
        launch_chrome_direct(str(tmp_path / "p1"), port=9991, headless=True)
        assert any(
            a == "--disable-features=AutoDeElevate" for a in captured["args"]
        ), captured["args"]
        # Case 2: caller provided --disable-features=X — must be merged
        launch_chrome_direct(
            str(tmp_path / "p2"), port=9992, headless=True,
            extra_args=["--disable-features=Foo"],
        )
        assert any(
            a == "--disable-features=Foo,AutoDeElevate" for a in captured["args"]
        ), captured["args"]
        # Case 3: caller passed --disable-features=Foo,AutoDeElevate already
        launch_chrome_direct(
            str(tmp_path / "p3"), port=9993, headless=True,
            extra_args=["--disable-features=Foo,AutoDeElevate"],
        )
        assert any(
            a == "--disable-features=Foo,AutoDeElevate" for a in captured["args"]
        ), captured["args"]
    else:
        # Non-Windows: no AutoDeElevate injection at all
        launch_chrome_direct(str(tmp_path / "p4"), port=9994, headless=True)
        assert not any(
            "AutoDeElevate" in a for a in captured["args"]
        ), captured["args"]
