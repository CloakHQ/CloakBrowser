"""Tests for license exit-code -> message surfacing (license_error_message)."""

import json

import pytest

from cloakbrowser import CloakBrowserLicenseError
from cloakbrowser.license import (
    license_error_for_code,
    license_error_message,
    mint_denial_file,
    read_denial_file,
)


def _launch_text(code: int) -> str:
    return (
        "BrowserType.launch: Target page, context or browser has been closed\n"
        f"Browser logs:\n- [pid=123] <process did exit: exitCode={code}, signal=null>"
    )


@pytest.mark.parametrize(
    "code,fragment",
    [
        (76, "session limit"),
        (77, "invalid, expired, or missing"),
        (78, "couldn't verify"),
        (79, "--license-route"),
    ],
)
def test_known_license_codes_map_to_message(code, fragment):
    msg = license_error_message(_launch_text(code))
    assert msg is not None
    assert msg.startswith("CloakBrowser Pro:")
    assert fragment in msg


def test_non_license_exit_code_returns_none():
    # A normal/crash exit code is not ours -> passthrough (None).
    assert license_error_message(_launch_text(1)) is None
    assert license_error_message(_launch_text(139)) is None
    # A large SEH-style code (e.g. Windows access violation 0xC0000005) must not
    # crash or false-match -- this is the case that overflows a 32-bit int parse.
    assert license_error_message(_launch_text(3221225477)) is None


def test_no_exit_code_in_text_returns_none():
    # A bare TargetClosedError (post-ready death) carries no code -> None.
    assert license_error_message("Target page, context or browser has been closed") is None
    assert license_error_message("") is None


def test_error_type_is_runtimeerror_subclass():
    assert issubclass(CloakBrowserLicenseError, RuntimeError)
    assert str(CloakBrowserLicenseError("x")) == "x"


# ── license_error_for_code (int -> error, the post-handshake file path) ──


@pytest.mark.parametrize("code,fragment", [
    (76, "session limit"),
    (77, "invalid, expired, or missing"),
    (78, "couldn't verify"),
    (79, "--license-route"),
])
def test_license_error_for_code_known(code, fragment):
    err = license_error_for_code(code)
    assert isinstance(err, CloakBrowserLicenseError)
    assert fragment in str(err)


def test_license_error_for_code_unknown_returns_none():
    assert license_error_for_code(1) is None
    assert license_error_for_code(0) is None


# ── read_denial_file (destructive read of the binary's denial marker) ──


def test_read_denial_file_returns_code_and_consumes(tmp_path):
    f = tmp_path / "d.json"
    f.write_text(json.dumps(76))
    assert read_denial_file(str(f)) == 76
    assert not f.exists()  # consumed so a later launch can't see a stale code


def test_read_denial_file_missing_returns_none(tmp_path):
    assert read_denial_file(str(tmp_path / "nope.json")) is None


def test_read_denial_file_second_read_still_returns_code_after_consumed(tmp_path):
    """The read is destructive, but a concurrent/second guarded call for the same
    launch must still see the denial (cached in-process)."""
    f = tmp_path / "d.json"
    f.write_text(json.dumps(76))
    assert read_denial_file(str(f)) == 76
    assert not f.exists()                      # consumed
    assert read_denial_file(str(f)) == 76      # file gone, still surfaced from cache


def test_read_denial_file_garbage_returns_none(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("not-json")
    assert read_denial_file(str(f)) is None
    assert not f.exists()  # garbage is still cleaned up


def test_read_denial_file_empty_returns_none(tmp_path):
    f = tmp_path / "empty.json"
    f.write_text("")
    assert read_denial_file(str(f)) is None


# ── mint_denial_file ──


def test_mint_denial_file_path_in_denials_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("cloakbrowser.license.Path.home", lambda: tmp_path)
    path = mint_denial_file()
    assert path is not None
    assert path.endswith(".json")
    assert "denials" in path
    assert (tmp_path / ".cloakbrowser" / "denials").is_dir()


def test_mint_denial_file_unwritable_returns_none(monkeypatch):
    def boom(*a, **k):
        raise OSError("not writable")
    monkeypatch.setattr("cloakbrowser.license.Path.mkdir", boom)
    assert mint_denial_file() is None  # never breaks a launch


def test_mint_sweeps_stale_denial_files_keeps_fresh(tmp_path, monkeypatch):
    """A denial the binary wrote but nobody consumed would leak forever; mint
    sweeps files older than the TTL and leaves fresh (concurrent) ones alone."""
    import os as _os
    import time as _time
    from cloakbrowser.license import _DENIAL_FILE_TTL_SECONDS
    monkeypatch.setattr("cloakbrowser.license.Path.home", lambda: tmp_path)
    denials = tmp_path / ".cloakbrowser" / "denials"
    denials.mkdir(parents=True)
    stale = denials / "stale.json"
    stale.write_text("76")
    old = _time.time() - (_DENIAL_FILE_TTL_SECONDS + 60)
    _os.utime(stale, (old, old))
    fresh = denials / "fresh.json"       # e.g. a concurrent launch's live denial
    fresh.write_text("76")

    mint_denial_file()

    assert not stale.exists()  # orphan swept
    assert fresh.exists()      # in-flight denial untouched


# ── _install_license_guard (surfacing on the user's next call) ──


class _StubBrowser:
    """Minimal stand-in: new_page raises like a dead browser would."""
    def __init__(self, exc):
        self._exc = exc

    def new_page(self, *a, **k):
        raise self._exc

    def new_context(self, *a, **k):
        raise self._exc


def _target_closed():
    return RuntimeError("Target page, context or browser has been closed")


def test_guard_raises_license_error_when_denial_file_present(tmp_path):
    from cloakbrowser.browser import _install_license_guard
    denial = tmp_path / "d.json"
    denial.write_text(json.dumps(76))
    b = _StubBrowser(_target_closed())
    _install_license_guard(b, str(denial))
    with pytest.raises(CloakBrowserLicenseError) as ei:
        b.new_page()
    assert "session limit" in str(ei.value)


def test_guard_passthrough_when_no_file(tmp_path):
    from cloakbrowser.browser import _install_license_guard
    original = _target_closed()
    b = _StubBrowser(original)
    _install_license_guard(b, str(tmp_path / "absent.json"))
    with pytest.raises(RuntimeError) as ei:
        b.new_page()
    assert ei.value is original  # a genuine failure is never relabelled


def test_guard_passthrough_when_file_garbage(tmp_path):
    from cloakbrowser.browser import _install_license_guard
    denial = tmp_path / "bad.json"
    denial.write_text("garbage")
    original = _target_closed()
    b = _StubBrowser(original)
    _install_license_guard(b, str(denial))
    with pytest.raises(RuntimeError) as ei:
        b.new_page()
    assert ei.value is original


@pytest.mark.asyncio
async def test_guard_async_raises_license_error(tmp_path):
    from cloakbrowser.browser import _install_license_guard_async
    denial = tmp_path / "d.json"
    denial.write_text(json.dumps(77))

    class _AsyncStub:
        async def new_page(self, *a, **k):
            raise _target_closed()

    b = _AsyncStub()
    _install_license_guard_async(b, str(denial))
    with pytest.raises(CloakBrowserLicenseError) as ei:
        await b.new_page()
    assert "invalid, expired, or missing" in str(ei.value)


# ── the denial can land while calls still SUCCEED ──
# The binary writes the denial file the instant it's over cap but keeps serving
# (blank) responses for ~1s before it exits. The guard checks the file after
# every call — success or failure — so a fast flow that never triggers an
# exception still surfaces the denial.


def test_guard_surfaces_denial_on_successful_call(tmp_path):
    from cloakbrowser.browser import _install_license_guard
    denial = tmp_path / "d.json"
    denial.write_text(json.dumps(76))

    class _StubPage:
        def goto(self, *a, **k):
            return "ok"  # succeeds — no exception at all

    page = _StubPage()
    _install_license_guard(page, str(denial))
    with pytest.raises(CloakBrowserLicenseError) as ei:
        page.goto("https://example.com")
    assert "session limit" in str(ei.value)


def test_guard_survives_class_attribute_rebinding(tmp_path):
    """Humanize copies page methods into a class attribute (``type("Originals",
    ...)``) and reads them back off an instance. A plain-function guard would be
    re-bound there and inject a spurious ``self`` arg (a real bug we hit); the
    guard must behave like a bound method and pass args through unchanged."""
    from cloakbrowser.browser import _install_license_guard

    calls = []

    class _StubPage:
        def goto(self, url, **k):
            calls.append(url)
            return "ok"

    page = _StubPage()
    _install_license_guard(page, str(tmp_path / "absent.json"))
    # Mimic humanize: stash the guarded method on a class, call it via an instance.
    originals = type("Originals", (), {"goto": page.goto})()
    assert originals.goto("https://example.com") == "ok"
    assert calls == ["https://example.com"]  # url passed through, no spurious self


# ── the page a factory hands back is guarded too (deep) ──
# A denial that lands AFTER launch — once the user already holds a page from
# new_page() — must surface on that page's first call, not only on a second
# new_page(). new_page/new_context guard the object they return.


def test_guard_deep_wraps_returned_page(tmp_path):
    from cloakbrowser.browser import _install_license_guard
    denial = tmp_path / "d.json"

    class _StubPage:
        def goto(self, *a, **k):
            raise _target_closed()

    class _StubFactory:
        def new_page(self, *a, **k):
            return _StubPage()

    b = _StubFactory()
    _install_license_guard(b, str(denial))
    page = b.new_page()  # succeeds; no denial yet
    denial.write_text(json.dumps(76))  # denial lands after the page is handed over
    with pytest.raises(CloakBrowserLicenseError) as ei:
        page.goto("https://example.com")
    assert "session limit" in str(ei.value)


@pytest.mark.asyncio
async def test_guard_deep_wraps_returned_page_async(tmp_path):
    from cloakbrowser.browser import _install_license_guard_async
    denial = tmp_path / "d.json"

    class _AsyncPage:
        async def goto(self, *a, **k):
            raise _target_closed()

    class _AsyncFactory:
        async def new_page(self, *a, **k):
            return _AsyncPage()

    b = _AsyncFactory()
    _install_license_guard_async(b, str(denial))
    page = await b.new_page()
    denial.write_text(json.dumps(76))
    with pytest.raises(CloakBrowserLicenseError) as ei:
        await page.goto("https://example.com")
    assert "session limit" in str(ei.value)


# ── the realistic navigation calls each surface the denial ──
# A persistent context is handed back with pages[0] already open, so the user
# navigates that page directly. Each navigation entry point must surface it.


@pytest.mark.parametrize("method", [
    "goto", "reload", "wait_for_load_state", "wait_for_url", "wait_for_selector",
])
def test_guard_surfaces_denial_on_each_pre_open_page_nav_method(tmp_path, method):
    """The bug: pages[0].goto() on a denied persistent context threw a bare
    TargetClosedError. With the page's methods guarded, each one surfaces
    CloakBrowserLicenseError instead."""
    from cloakbrowser.browser import _install_license_guard

    class _StubPage:
        # every nav method raises like a dead browser would
        def goto(self, *a, **k): raise _target_closed()
        def reload(self, *a, **k): raise _target_closed()
        def wait_for_load_state(self, *a, **k): raise _target_closed()
        def wait_for_url(self, *a, **k): raise _target_closed()
        def wait_for_selector(self, *a, **k): raise _target_closed()

    denial = tmp_path / "d.json"
    denial.write_text(json.dumps(76))
    page = _StubPage()
    _install_license_guard(page, str(denial))
    with pytest.raises(CloakBrowserLicenseError) as ei:
        getattr(page, method)("https://example.com")
    assert "session limit" in str(ei.value)


def test_guard_passthrough_on_pre_open_page_without_denial(tmp_path):
    """No denial file -> a genuine navigation failure is never relabelled."""
    from cloakbrowser.browser import _install_license_guard

    original = _target_closed()

    class _StubPage:
        def goto(self, *a, **k): raise original
        def reload(self, *a, **k): raise original
        def wait_for_load_state(self, *a, **k): raise original
        def wait_for_url(self, *a, **k): raise original
        def wait_for_selector(self, *a, **k): raise original

    page = _StubPage()
    _install_license_guard(page, str(tmp_path / "absent.json"))
    with pytest.raises(RuntimeError) as ei:
        page.goto("https://example.com")
    assert ei.value is original
