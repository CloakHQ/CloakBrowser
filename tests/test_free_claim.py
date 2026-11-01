"""Free-key claim flow: claim code, key save, and the no-key launch path."""
import os
import stat
import threading
import time
from unittest import mock

import httpx
import pytest

from cloakbrowser import download, license as lic
from cloakbrowser.license import CloakBrowserLicenseError, LicenseInfo


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOAKBROWSER_CACHE_DIR", str(tmp_path))
    monkeypatch.delenv("CLOAKBROWSER_LICENSE_KEY", raising=False)
    monkeypatch.delenv("CLOAKBROWSER_BINARY_PATH", raising=False)
    monkeypatch.setattr(download, "_claim_poll_started", False)
    return tmp_path


def _mode(path):
    return stat.S_IMODE(path.stat().st_mode)


# ── claim code ──────────────────────────────────────────────────────────────


def test_claim_code_is_reused_and_private(cache):
    code = lic.get_claim_code()
    assert lic.CLAIM_CODE_RE.fullmatch(code)
    assert lic.get_claim_code() == code
    assert _mode(cache / ".free_claim") == 0o600


def test_claim_code_rotates_after_seven_days(cache):
    old = lic.get_claim_code()
    stale = time.time() - lic.CLAIM_MAX_AGE - 1
    os.utime(cache / ".free_claim", (stale, stale))
    assert lic.get_claim_code() != old


def test_parallel_workers_share_one_code(cache):
    """Concurrent first launches must print the same link."""
    codes, start = [], threading.Barrier(8)

    def worker():
        start.wait()
        codes.append(lic.get_claim_code())

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(codes)) == 1


# ── key save ────────────────────────────────────────────────────────────────


def test_save_key_is_private_and_retires_claim(cache):
    lic.get_claim_code()
    assert lic.save_license_key("cb_abc") is True
    assert (cache / "license.key").read_text() == "cb_abc\n"
    assert _mode(cache / "license.key") == 0o600
    assert not (cache / ".free_claim").exists()


def test_save_key_rejects_non_keys(cache):
    with pytest.raises(ValueError):
        lic.save_license_key("<script>")
    assert not (cache / "license.key").exists()


def test_poller_never_overwrites_an_existing_key(cache):
    lic.save_license_key("cb_mine")
    assert lic.save_license_key("cb_claimed", overwrite=False) is False
    assert (cache / "license.key").read_text() == "cb_mine\n"


# ── check_claim ─────────────────────────────────────────────────────────────


def _resp(status, payload):
    return httpx.Response(status, json=payload, request=httpx.Request("POST", lic.CLAIM_URL))


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"status": "pending"}, None),
        ({"status": "ready", "license_key": "cb_ok"}, "cb_ok"),
        ({"status": "ready", "license_key": "bad key"}, None),  # trust boundary
    ],
)
def test_check_claim_answers(payload, expected):
    with mock.patch("httpx.post", return_value=_resp(200, payload)) as post:
        assert lic.check_claim("c" * 32) == expected
    # The code is a bearer secret: body, never the URL.
    assert post.call_args.args[0] == lic.CLAIM_URL
    assert post.call_args.kwargs["json"] == {"code": "c" * 32}


@pytest.mark.parametrize("payload", [None, [], "ready", 7])
def test_check_claim_non_object_json_is_pending(payload):
    with mock.patch("httpx.post", return_value=_resp(200, payload)):
        assert lic.check_claim("c" * 32) is None


def test_ready_claim_is_retired_even_when_a_key_is_kept(cache):
    """A ready claim must not linger: after `logout` it would re-save the key."""
    lic.save_license_key("cb_mine")
    lic.get_claim_code()
    with mock.patch.object(lic, "check_claim", return_value="cb_claimed"):
        assert lic.poll_claim("c" * 32, overwrite=False) is None  # nothing saved
    assert (cache / "license.key").read_text() == "cb_mine\n"
    assert not (cache / ".free_claim").exists()


def test_background_poll_starts_once_under_concurrency(cache, monkeypatch):
    started, gate = [], threading.Barrier(8)

    def go():
        gate.wait()
        download._start_claim_poll("c" * 32)

    # Real threads race the check; the poller thread itself is mocked.
    real = threading.Thread
    with mock.patch.object(download.threading, "Thread", side_effect=lambda **kw: started.append(1) or mock.Mock()):
        ts = [real(target=go) for _ in range(8)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
    assert len(started) == 1


@pytest.mark.parametrize("env, expected", [({}, False), ({"DISPLAY": ":0"}, True), ({"WAYLAND_DISPLAY": "w"}, True)])
def test_no_browser_open_without_display_on_linux(monkeypatch, env, expected):
    monkeypatch.setattr(download.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert download._has_display() is expected


def test_check_claim_network_error_is_pending():
    with mock.patch("httpx.post", side_effect=httpx.ConnectError("down")):
        assert lic.check_claim("c" * 32) is None


# ── ensure_binary with no key ───────────────────────────────────────────────


def _valid_launch(monkeypatch):
    seen = {}

    def fake_validate(key):
        seen["key"] = key
        return LicenseInfo(valid=True, plan="free", expires=None)

    monkeypatch.setattr(lic, "validate_license", fake_validate)
    monkeypatch.setattr(download, "_ensure_pro_binary", lambda key, **kw: "/bin/chrome")
    monkeypatch.setattr(download, "_maybe_trigger_update_check", lambda: None)
    return seen


def test_no_key_without_terminal_raises_with_link_and_polls(cache, monkeypatch, capsys):
    monkeypatch.setattr(lic, "check_claim", lambda code: None)
    monkeypatch.setattr(download, "_isatty", lambda s: False)
    with mock.patch.object(download, "_start_claim_poll") as poll:
        with pytest.raises(CloakBrowserLicenseError, match=r"cloakbrowser\.dev/#claim="):
            download.ensure_binary()
    poll.assert_called_once()
    assert "#claim=" in capsys.readouterr().err  # stderr only: MCP owns stdout


def test_no_key_off_main_thread_never_waits(cache, monkeypatch):
    """launch_async runs ensure_binary on a worker thread Ctrl+C can't reach."""
    monkeypatch.setattr(lic, "check_claim", lambda code: None)
    monkeypatch.setattr(download, "_isatty", lambda s: True)
    errors = []

    def run():
        with mock.patch.object(download, "_start_claim_poll"):
            try:
                download.ensure_binary()
            except CloakBrowserLicenseError as e:
                errors.append(e)

    t = threading.Thread(target=run)
    t.start()
    t.join(timeout=5)
    assert not t.is_alive() and len(errors) == 1


def test_no_key_in_terminal_menu_default_gets_free_key(cache, monkeypatch, capsys):
    answers = iter([None, None, "cb_claimed"])  # first check, then two polls
    monkeypatch.setattr(lic, "check_claim", lambda code: next(answers))
    monkeypatch.setattr(lic.time, "sleep", lambda s: None)
    monkeypatch.setattr(download, "_isatty", lambda s: True)
    monkeypatch.setattr(download, "_has_display", lambda: True)  # CI runners have none
    seen = _valid_launch(monkeypatch)
    with mock.patch("builtins.input", return_value="") as ask, \
            mock.patch("webbrowser.open", return_value=True) as opened:
        assert download.ensure_binary() == "/bin/chrome"
    assert ask.call_count == 1  # Enter = option 1
    assert opened.call_args.args[0].startswith(lic.FREE_CLAIM_LINK)
    assert seen["key"] == "cb_claimed"
    assert (cache / "license.key").read_text() == "cb_claimed\n"
    err = capsys.readouterr().err
    assert "Welcome to CloakBrowser" in err and "1) Get a free key" in err
    # The menu was the welcome: the regular banner must not repeat this launch.
    download._show_welcome("free")
    assert capsys.readouterr().err == ""


def test_no_key_in_terminal_menu_paste_key(cache, monkeypatch):
    monkeypatch.setattr(lic, "check_claim", lambda code: None)
    monkeypatch.setattr(download, "_isatty", lambda s: True)
    seen = _valid_launch(monkeypatch)
    # 2, then a non-key (asked again), then the real key.
    with mock.patch("builtins.input", side_effect=["2", "hello", "cb_mine"]), \
            mock.patch("webbrowser.open") as opened:
        assert download.ensure_binary() == "/bin/chrome"
    opened.assert_not_called()
    assert seen["key"] == "cb_mine"
    assert (cache / "license.key").read_text() == "cb_mine\n"


def test_menu_rejects_invalid_pasted_key(cache, monkeypatch):
    monkeypatch.setattr(
        lic, "validate_license",
        lambda key: LicenseInfo(valid=key == "cb_good", plan="free", expires=None),
    )
    with mock.patch("builtins.input", side_effect=["7", "2", "cb_bad", "cb_good"]):
        assert download.prompt_license_key() == "cb_good"
    assert (cache / "license.key").read_text() == "cb_good\n"


def test_check_claim_has_key_raises_and_retires_code(cache):
    lic.get_claim_code()
    with mock.patch("httpx.post", return_value=_resp(200, {"status": "has_key"})):
        with pytest.raises(lic.FreeKeyAlreadyHeld):
            lic.check_claim("c" * 32)
    assert not (cache / ".free_claim").exists()


def test_menu_email_already_has_key_switches_to_paste(cache, monkeypatch, capsys):
    """The server never sends an existing key to a claim: stop waiting, ask to paste."""
    def claim(code):
        raise lic.FreeKeyAlreadyHeld

    monkeypatch.setattr(lic, "check_claim", claim)
    monkeypatch.setattr(
        lic, "validate_license", lambda key: LicenseInfo(valid=True, plan="free", expires=None)
    )
    with mock.patch("builtins.input", side_effect=["1", "cb_old"]), \
            mock.patch("webbrowser.open"):
        assert download.prompt_license_key() == "cb_old"
    assert "already has a free key" in capsys.readouterr().err
    assert (cache / "license.key").read_text() == "cb_old\n"


def test_no_terminal_email_already_has_key_says_so(cache, monkeypatch):
    def claim(code):
        raise lic.FreeKeyAlreadyHeld

    monkeypatch.setattr(lic, "check_claim", claim)
    monkeypatch.setattr(download, "_isatty", lambda s: False)
    with pytest.raises(CloakBrowserLicenseError, match="already has a free key"):
        download.ensure_binary()


def test_ctrl_c_at_menu_exits_quietly(cache, monkeypatch):
    monkeypatch.setattr(lic, "check_claim", lambda code: None)
    monkeypatch.setattr(download, "_isatty", lambda s: True)
    with mock.patch("builtins.input", side_effect=KeyboardInterrupt):
        with pytest.raises(SystemExit) as e:
            download.ensure_binary()
    assert e.value.code == 130


def test_menu_eof_falls_back_to_link_error(cache, monkeypatch):
    monkeypatch.setattr(lic, "check_claim", lambda code: None)
    monkeypatch.setattr(download, "_isatty", lambda s: True)
    with mock.patch("builtins.input", side_effect=EOFError), \
            mock.patch.object(download, "_start_claim_poll"):
        with pytest.raises(CloakBrowserLicenseError, match=r"#claim="):
            download.ensure_binary()


def test_key_confirmed_since_last_launch_is_picked_up(cache, monkeypatch, capsys):
    monkeypatch.setattr(lic, "check_claim", lambda code: "cb_ready")
    seen = _valid_launch(monkeypatch)
    assert download.ensure_binary() == "/bin/chrome"
    assert seen["key"] == "cb_ready"
    assert "#claim=" not in capsys.readouterr().err  # no link once it's ready


def test_any_key_source_skips_the_claim(cache, monkeypatch):
    monkeypatch.setenv("CLOAKBROWSER_LICENSE_KEY", "cb_env")
    seen = _valid_launch(monkeypatch)
    with mock.patch.object(download, "_claim_free_key", side_effect=AssertionError):
        download.ensure_binary()
    assert seen["key"] == "cb_env"


def test_background_poll_runs_once_per_process(cache, monkeypatch):
    with mock.patch("threading.Thread") as thread:
        download._start_claim_poll("c" * 32)
        download._start_claim_poll("c" * 32)
    assert thread.call_count == 1
