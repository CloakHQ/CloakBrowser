"""Tier-aware launch banner: keyless (v146) / free key / paid, + cadence."""
import io
import sys
import time
from pathlib import Path

import pytest

from cloakbrowser import download


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOAKBROWSER_CACHE_DIR", str(tmp_path))
    return tmp_path


def _banner(capsys, tier):
    download._show_welcome(tier)
    return capsys.readouterr().err


def test_keyless_banner(cache, capsys):
    out = _banner(capsys, "keyless")
    assert "Running the free binary" in out
    assert "cloakbrowser login" in out                      # invite the free login
    assert "For more than one concurrent session" in out
    assert "Pro active" not in out


def test_free_key_banner(cache, capsys):
    out = _banner(capsys, "free")
    assert "CloakBrowser free" in out
    assert "1 concurrent session" in out
    assert "For more than one concurrent session" in out
    assert "Pro active" not in out                          # not a paid user
    assert "cloakbrowser login" not in out                  # they already have a key


def test_pro_banner(cache, capsys):
    out = _banner(capsys, "pro")
    assert "Pro active" in out
    assert "Pro support" in out
    assert "cloakbrowser login" not in out


def test_pro_shows_once(cache, capsys):
    assert _banner(capsys, "pro") != ""
    assert _banner(capsys, "pro") == ""                     # marker written -> never again


def test_free_reshows_after_interval(cache, capsys):
    assert _banner(capsys, "free") != ""
    assert _banner(capsys, "free") == ""                    # fresh marker -> suppressed
    marker = cache / ".welcome_shown"
    marker.write_text(str(int(time.time()) - download.WELCOME_FREE_INTERVAL - 1))
    assert _banner(capsys, "free") != ""                    # interval passed -> shows again


@pytest.mark.parametrize("tier", ["keyless", "free", "pro"])
def test_banner_is_ascii_only(cache, capsys, tier):
    """Banner must be pure ASCII so a legacy Windows console (cp1252/strict)
    can always encode it. Regression for ticket 2354 (the '->' glyph)."""
    out = _banner(capsys, tier)
    assert out != ""
    non_ascii = [c for c in out if ord(c) > 0x7F]
    assert non_ascii == [], f"non-ASCII in {tier} banner: {non_ascii!r}"


@pytest.mark.parametrize("tier", ["keyless", "free", "pro"])
def test_banner_never_raises_on_cp1252_stderr(cache, monkeypatch, tier):
    """Even if a future glyph slips in, a cp1252/strict stderr must not abort
    the launch — the banner is cosmetic. Reproduces ticket 2354's crash path."""
    strict = io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stderr", strict)
    download._show_welcome(tier)  # pre-fix: UnicodeEncodeError; post-fix: returns


def test_ensure_pro_binary_maps_plan_to_tier(monkeypatch):
    """A free-plan key shows the free banner; any other plan shows Pro."""
    seen = []
    monkeypatch.setattr(download, "_show_welcome", lambda tier="keyless": seen.append(tier))
    monkeypatch.setattr(download, "_pro_binary_ready", lambda v: True)
    monkeypatch.setattr(download, "get_binary_path", lambda v, pro=False: Path("/tmp/chrome"))

    # Pinned + cached path returns immediately after the banner call.
    download._ensure_pro_binary("cb_x", requested_version="150.0.7871.114.3", plan="free")
    download._ensure_pro_binary("cb_x", requested_version="150.0.7871.114.3", plan="business")
    download._ensure_pro_binary("cb_x", requested_version="150.0.7871.114.3", plan=None)
    assert seen == ["free", "pro", "pro"]
