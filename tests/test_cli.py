"""Unit tests for the cloakbrowser CLI diagnostics (`info` / `doctor`)."""

import json
import os
import sys
from argparse import Namespace
from unittest.mock import patch

import pytest

import cloakbrowser.__main__
from cloakbrowser.__main__ import _binary_version, cmd_info
from cloakbrowser.license import LicenseInfo, ProReleaseInfo, SessionSeats


def _run(args, *, key=None, license_info=None, sessions=None):
    """Run cmd_info with license resolution mocked and the real downloaders patched.

    key=None  -> no license -> free binary.
    key set   -> validate_license returns license_info (entitled to Pro if valid).
    sessions  -> the SessionSeats the seat lookup reports (it is mocked out, so a
                 non-quick Pro run never reaches the network). None defaults to a
                 server-cannot-count result, which keeps unrelated tests offline.

    Returns (download_free_mock, download_pro_mock, session_count_mock) so callers
    can assert the command never triggers a binary download or an unwanted lookup.
    """
    with (
        patch("cloakbrowser.license.resolve_license_key", return_value=key),
        patch("cloakbrowser.license.validate_license", return_value=license_info),
        patch(
            "cloakbrowser.license.get_session_seats",
            return_value=sessions if sessions is not None else SessionSeats(state="unknown"),
        ) as mock_sessions,
        patch("cloakbrowser.download._download_and_extract") as mock_dl_free,
        patch("cloakbrowser.download._download_pro_binary") as mock_dl_pro,
    ):
        cmd_info(args)
    return mock_dl_free, mock_dl_pro, mock_sessions


def test_info_text_never_downloads(capsys):
    free_dl, pro_dl, _ = _run(Namespace(quick=True, json=False))
    free_dl.assert_not_called()
    pro_dl.assert_not_called()
    out = capsys.readouterr().out
    assert "CloakBrowser diagnostics" in out
    assert "Python:" in out
    assert "Platform:" in out
    assert "License:   Free" in out
    assert "Modules:" in out


def test_info_quick_skips_launch(capsys):
    _run(Namespace(quick=True, json=False))
    out = capsys.readouterr().out
    assert "skipped (--quick)" in out


def test_info_without_proxy_shows_hint_and_never_resolves(capsys):
    with patch("cloakbrowser.geoip.resolve_proxy_geo_with_ip") as resolver:
        _run(Namespace(quick=True, json=False))
    resolver.assert_not_called()
    out = capsys.readouterr().out
    assert "pass --proxy" in out
    assert "Exit IP:" not in out


def test_info_proxy_resolves_and_prints_exit_ip(capsys):
    with patch(
        "cloakbrowser.geoip.resolve_proxy_geo_with_ip",
        return_value=("Europe/Berlin", "de-DE", "203.0.113.9"),
    ) as resolver:
        _run(Namespace(quick=True, json=False, proxy="http://p:8080"))
    resolver.assert_called_once_with("http://p:8080")
    out = capsys.readouterr().out
    assert "Exit IP:   203.0.113.9" in out
    assert "Timezone:  Europe/Berlin" in out
    assert "Locale:    de-DE" in out
    assert "pass --proxy" not in out  # hint suppressed once resolved


def test_info_proxy_json_includes_resolved(capsys):
    with patch(
        "cloakbrowser.geoip.resolve_proxy_geo_with_ip",
        return_value=("Europe/Berlin", "de-DE", "203.0.113.9"),
    ):
        _run(Namespace(quick=True, json=True, proxy="http://p:8080"))
    data = json.loads(capsys.readouterr().out)
    assert data["geoip"]["resolved"] == {
        "exit_ip": "203.0.113.9",
        "timezone": "Europe/Berlin",
        "locale": "de-DE",
    }


def test_info_proxy_resolution_failure_is_reported_not_fatal(capsys):
    with patch(
        "cloakbrowser.geoip.resolve_proxy_geo_with_ip",
        side_effect=RuntimeError("proxy refused"),
    ):
        _run(Namespace(quick=True, json=False, proxy="http://p:8080"))
    out = capsys.readouterr().out
    assert "could not resolve" in out
    assert "proxy refused" in out


def test_keyless_reports_free_binary(capsys):
    """No license key -> the binary section reflects the FREE binary."""
    _run(Namespace(quick=True, json=True))
    data = json.loads(capsys.readouterr().out)
    assert data["binary"]["tier"] == "free"
    assert data["license"]["tier"] == "free"


def test_valid_key_reports_pro_binary(capsys):
    """A server-validated key -> the binary section reflects the PRO binary.

    ``latest_version`` reports the server's latest (mocked); ``version`` is the
    build that will actually launch (a cached Pro build if present, otherwise the
    latest it will fetch). The two are surfaced separately so they can't diverge.
    """
    valid = LicenseInfo(valid=True, plan="business", expires=None)
    # quick=False: the server latest lookup is skipped under --quick (network-free),
    # so exercise the full path to see latest_version populated.
    release = ProReleaseInfo("148.0.0.0", "stable", "stable", False)
    with patch("cloakbrowser.license.get_pro_latest_release", return_value=release):
        _run(Namespace(quick=False, json=True), key="cb_test", license_info=valid)
    data = json.loads(capsys.readouterr().out)
    assert data["binary"]["tier"] == "pro"
    assert data["binary"]["latest_version"] == "148.0.0.0"
    # A Pro user always resolves to a Pro version (cached-or-latest), never the free base.
    assert data["binary"]["version"]
    assert data["license"]["tier"] == "business"


def test_quick_skips_pro_latest_lookup(capsys):
    """--quick keeps `info` network-free: no server latest-version lookup for Pro."""
    valid = LicenseInfo(valid=True, plan="business", expires=None)
    with patch(
        "cloakbrowser.license.get_pro_latest_release",
        return_value=ProReleaseInfo("148.0.0.0", "stable", "stable", False),
    ) as mock_latest:
        _run(Namespace(quick=True, json=True), key="cb_test", license_info=valid)
    data = json.loads(capsys.readouterr().out)
    mock_latest.assert_not_called()
    assert data["binary"]["latest_version"] is None


def test_info_reports_preview_stable_fallback(capsys):
    valid = LicenseInfo(valid=True, plan="business", expires=None)
    release = ProReleaseInfo("150.0.7871.114.3", "preview", "stable", True)
    with (
        patch.dict(os.environ, {"CLOAKBROWSER_RELEASE_CHANNEL": "preview"}),
        patch("cloakbrowser.license.get_pro_latest_release", return_value=release),
    ):
        _run(Namespace(quick=False, json=False), key="cb_test", license_info=valid)
    assert "Channel:   Preview → Stable fallback" in capsys.readouterr().out


def test_invalid_key_falls_back_to_free(capsys):
    """A key the server rejects -> not entitled -> free binary, not Pro."""
    invalid = LicenseInfo(valid=False, plan="solo", expires=None)
    _run(Namespace(quick=True, json=True), key="cb_bad", license_info=invalid)
    data = json.loads(capsys.readouterr().out)
    assert data["binary"]["tier"] == "free"
    assert data["license"]["tier"] == "invalid"


# ── Seat count ────────────────────────────────────────

_PRO = LicenseInfo(valid=True, plan="business", expires=None)


def _seats(args_json=False, **seat_kwargs):
    """Render the Sessions line for one SessionSeats result."""
    return _run(
        Namespace(quick=False, json=args_json),
        key="cb_test",
        license_info=_PRO,
        sessions=SessionSeats(**seat_kwargs),
    )


def test_pro_reports_seats_and_limit_in_json(capsys):
    _seats(args_json=True, active=8, limit=2000, state="ok")
    data = json.loads(capsys.readouterr().out)
    assert data["license"]["sessions"] == {
        "active": 8, "limit": 2000, "state": "ok", "reason": None,
    }


def test_seat_line_shows_used_over_limit(capsys):
    """The point of the change: a scale-plan customer can see they are nowhere near
    the ceiling (or right on it) instead of reading a bare number."""
    _seats(active=8, limit=2000, state="ok")
    assert "Sessions:  8/2000 in use" in capsys.readouterr().out


def test_seat_line_falls_back_when_the_server_sends_no_limit(capsys):
    """Older server, unlimited licence, or an unrecognised plan. Print the count we do
    have rather than "8/unknown"."""
    _seats(active=8, limit=None, state="ok")
    out = capsys.readouterr().out
    assert "Sessions:  8 seats in use" in out
    assert "unavailable" not in out


def test_seat_fallback_is_singular_for_one(capsys):
    _seats(active=1, limit=None, state="ok")
    assert "Sessions:  1 seat in use" in capsys.readouterr().out


def test_one_of_one_seat_shows_the_limit(capsys):
    """A free key holds exactly one seat — the cohort most likely to hit its cap."""
    _seats(active=1, limit=1, state="ok")
    assert "Sessions:  1/1 in use" in capsys.readouterr().out


def test_zero_seats_reads_as_a_real_answer_not_unavailable(capsys):
    """0 is a real answer ("nothing running"); only an unknown prints unavailable."""
    _seats(active=0, limit=5, state="ok")
    out = capsys.readouterr().out
    assert "Sessions:  0/5 in use" in out
    assert "unavailable" not in out


def test_unreachable_server_says_so(capsys):
    _seats(state="unreachable")
    assert "Sessions:  unavailable (cannot reach cloakbrowser.dev)" in capsys.readouterr().out


@pytest.mark.parametrize(
    "code,shown",
    [
        ("license_inactive", "license inactive"),
        ("invalid_key", "invalid key"),
        ("rate_limited", "rate limited"),
    ],
)
def test_denial_reasons_are_spelled_out(capsys, code, shown):
    """These four used to be one string. A dead key and a healthy key behind a
    degraded backend must not read identically."""
    _seats(state="denied", reason=code)
    assert f"Sessions:  unavailable ({shown})" in capsys.readouterr().out


def test_unrecognised_denial_reason_is_passed_through(capsys):
    """A server code we have no wording for still says something actionable."""
    _seats(state="denied", reason="some_new_code")
    assert "Sessions:  unavailable (some_new_code)" in capsys.readouterr().out


def test_server_cannot_count_is_not_an_error(capsys):
    """Leaseless mode / seat store down: the customer's key is fine and there is
    nothing for them to do. Must not read like a licence problem."""
    _seats(state="unknown")
    out = capsys.readouterr().out
    assert "Sessions:  unavailable (server cannot report seats right now)" in out
    assert "invalid" not in out


def test_quick_skips_the_seat_lookup(capsys):
    """--quick keeps `info` network-free — same rule as the Pro latest lookup."""
    _, _, mock_sessions = _run(
        Namespace(quick=True, json=True), key="cb_test", license_info=_PRO, sessions=3
    )
    data = json.loads(capsys.readouterr().out)
    mock_sessions.assert_not_called()
    assert "sessions" not in data["license"]


def test_free_tier_never_looks_up_seats(capsys):
    """A free tier holds no seats — don't ask the server about it."""
    _, _, mock_sessions = _run(Namespace(quick=False, json=True))
    data = json.loads(capsys.readouterr().out)
    mock_sessions.assert_not_called()
    assert "sessions" not in data["license"]


def test_invalid_key_never_looks_up_seats(capsys):
    invalid = LicenseInfo(valid=False, plan="solo", expires=None)
    _, _, mock_sessions = _run(
        Namespace(quick=False, json=True), key="cb_bad", license_info=invalid
    )
    mock_sessions.assert_not_called()


def test_info_json_is_valid(capsys):
    _run(Namespace(quick=True, json=True))
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["environment"]["python"]
    assert "modules" in data
    # Upgrade hint is text-only; JSON exposes tier as a field instead.
    assert "cloakbrowser.dev" not in out


def test_free_license_shows_upgrade_hint(capsys):
    _run(Namespace(quick=True, json=False))
    out = capsys.readouterr().out
    # Keyless free: invite the free-latest login + point at paid for more sessions.
    assert "License:   Free (no key)" in out
    assert "cloakbrowser login" in out
    assert "For more than one concurrent session" in out
    assert "cloakbrowser.dev" in out


# ---------------------------------------------------------------------------
# Launch test — exercises the real subprocess path (not --quick) against a stub
# executable, so the launch-test code is actually covered by CI.
# ---------------------------------------------------------------------------

pytestmark_posix = pytest.mark.skipif(
    sys.platform == "win32", reason="uses a POSIX shell stub binary"
)


@pytestmark_posix
def test_binary_version_runs_stub(tmp_path):
    stub = tmp_path / "fakechrome"
    stub.write_text("#!/bin/sh\necho 'Chromium 1.2.3.4'\n")
    stub.chmod(0o755)
    ok, version, err = _binary_version(str(stub))
    assert ok
    assert "Chromium 1.2.3.4" in version
    assert err == ""


def test_console_glyph_falls_back_on_legacy_windows_encoding(monkeypatch):
    """cmd.exe defaults to cp850/cp1252, which carry no check mark — printing one
    there aborted the whole report with UnicodeEncodeError."""
    import io

    monkeypatch.setattr(
        cloakbrowser.__main__.sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    )
    assert cloakbrowser.__main__._console_glyph("✓", "OK") == "OK"
    assert cloakbrowser.__main__._console_glyph("→", "->") == "->"
    # cp1252 does carry the em dash, so it is kept — the check is per glyph.
    assert cloakbrowser.__main__._console_glyph("—", "-") == "—"


def test_console_glyph_kept_on_utf8(monkeypatch):
    import io

    monkeypatch.setattr(
        cloakbrowser.__main__.sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    )
    assert cloakbrowser.__main__._console_glyph("✓", "OK") == "✓"
    assert cloakbrowser.__main__._console_glyph("✗", "x") == "✗"


@pytestmark_posix
def test_binary_version_windows_probe_does_not_hang(tmp_path, monkeypatch):
    """Real Windows Chrome ignores --version and starts a browser instead of
    printing, so the stub here hangs unless --no-startup-window is passed —
    mirroring the binary rather than a stub that prints and exits."""
    stub = tmp_path / "winchrome"
    stub.write_text(
        "#!/bin/sh\n"
        'case "$*" in\n'
        "  *--no-startup-window*) exit 0 ;;\n"
        "  *) sleep 30 ;;\n"  # stands in for the browser that never returns
        "esac\n"
    )
    stub.chmod(0o755)
    monkeypatch.setattr(cloakbrowser.__main__.platform, "system", lambda: "Windows")
    ok, version, err = _binary_version(str(stub))
    assert ok, f"probe hung on a healthy Windows binary: {err}"
    assert version == ""  # Windows prints no version
    assert err == ""


@pytestmark_posix
def test_binary_version_reports_failure(tmp_path):
    stub = tmp_path / "failchrome"
    stub.write_text("#!/bin/sh\necho 'libfoo missing' >&2\nexit 1\n")
    stub.chmod(0o755)
    ok, version, err = _binary_version(str(stub))
    assert not ok
    assert "libfoo missing" in err


@pytestmark_posix
def test_launch_section_runs_binary_without_downloading(tmp_path, capsys):
    """Full non-quick run: the launch test executes the resolved binary, and no
    download function is ever invoked."""
    stub = tmp_path / "fakechrome"
    stub.write_text("#!/bin/sh\necho 'Chromium 9.9.9.9'\n")
    stub.chmod(0o755)
    fake_binary = {
        "version": "9.9.9.9",
        "tier": "free",
        "bundled_version": "x",
        "path": str(stub),
        "installed": True,
        "cache_dir": str(tmp_path),
        "override": None,
    }
    with (
        patch("cloakbrowser.license.resolve_license_key", return_value=None),
        patch("cloakbrowser.__main__._effective_binary", return_value=fake_binary),
        patch("cloakbrowser.download._download_and_extract") as mock_dl_free,
        patch("cloakbrowser.download._download_pro_binary") as mock_dl_pro,
    ):
        cmd_info(Namespace(quick=False, json=True))
    data = json.loads(capsys.readouterr().out)
    assert data["launch"]["tested"] is True
    assert data["launch"]["ok"] is True
    assert "Chromium 9.9.9.9" in data["launch"]["version"]
    mock_dl_free.assert_not_called()
    mock_dl_pro.assert_not_called()
