"""Fingerprint seed persistence for persistent profiles (.cloakbrowser-seed)."""

import logging
import threading
from unittest.mock import MagicMock, patch

import pytest

from cloakbrowser.config import PROFILE_SEED_FILE, persistent_seed_args


def _listing(d):
    # macOS adds ._ AppleDouble files on FAT volumes, where these tests also run.
    return [p.name for p in d.iterdir() if not p.name.startswith("._")]


def _seed(args):
    return [a for a in args if a.startswith("--fingerprint=")]


def _launch_args(launcher, *a, **kw):
    """Run launcher with mocked playwright; return the args passed to Chromium."""
    pw = MagicMock()
    pw_cm = MagicMock()
    pw_cm.start.return_value = pw
    with patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome"), \
         patch("cloakbrowser.browser.maybe_resolve_geoip", return_value=(None, None, None)), \
         patch("playwright.sync_api.sync_playwright", return_value=pw_cm):
        launcher(*a, **kw)
    if pw.chromium.launch_persistent_context.called:
        return pw.chromium.launch_persistent_context.call_args[1]["args"]
    return pw.chromium.launch.call_args[1]["args"]


def test_first_launch_writes_seed_and_second_reuses(tmp_path):
    from cloakbrowser.browser import launch_persistent_context

    profile = tmp_path / "profile"  # missing dir is created
    first = _seed(_launch_args(launch_persistent_context, str(profile)))
    stored = (profile / PROFILE_SEED_FILE).read_text()
    assert first == [f"--fingerprint={stored.strip()}"]
    assert stored.endswith("\n") and 10000 <= int(stored) <= 99999

    second = _seed(_launch_args(launch_persistent_context, str(profile)))
    assert second == first


@pytest.mark.asyncio
async def test_async_launch_uses_stored_seed(tmp_path):
    from unittest.mock import AsyncMock

    from cloakbrowser.browser import launch_persistent_context_async

    (tmp_path / PROFILE_SEED_FILE).write_text("12345\n")
    pw = MagicMock()
    pw.chromium.launch_persistent_context = AsyncMock()
    pw_cm = MagicMock()
    pw_cm.start = AsyncMock(return_value=pw)
    with patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome"), \
         patch("cloakbrowser.browser.maybe_resolve_geoip", return_value=(None, None, None)), \
         patch("playwright.async_api.async_playwright", return_value=pw_cm):
        await launch_persistent_context_async(str(tmp_path))
    assert _seed(pw.chromium.launch_persistent_context.call_args[1]["args"]) == ["--fingerprint=12345"]


@pytest.mark.parametrize("flag", ["--fingerprint=4242", "--fingerprint=off"])
def test_explicit_fingerprint_wins_and_file_untouched(tmp_path, flag):
    from cloakbrowser.browser import launch_persistent_context

    assert _seed(_launch_args(launch_persistent_context, str(tmp_path), args=[flag])) == [flag]
    assert not (tmp_path / PROFILE_SEED_FILE).exists()

    (tmp_path / PROFILE_SEED_FILE).write_text("12345\n")
    assert _seed(_launch_args(launch_persistent_context, str(tmp_path), args=[flag])) == [flag]
    assert (tmp_path / PROFILE_SEED_FILE).read_text() == "12345\n"


def test_stealth_args_false_writes_nothing(tmp_path):
    from cloakbrowser.browser import launch_persistent_context

    args = _launch_args(launch_persistent_context, str(tmp_path), stealth_args=False)
    assert _seed(args) == []
    assert list(tmp_path.iterdir()) == []


def test_non_persistent_launch_stays_random(tmp_path, monkeypatch):
    from cloakbrowser.browser import launch

    monkeypatch.chdir(tmp_path)
    seeds = {_seed(_launch_args(launch))[0] for _ in range(5)}
    assert len(seeds) > 1
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("content", [b"", b"abc\n", b"5\n", b"123456\n", b"-12345\n", b"\xff\xfe"])
def test_corrupt_file_logs_and_regenerates(tmp_path, caplog, content):
    path = tmp_path / PROFILE_SEED_FILE
    path.write_bytes(content)
    with caplog.at_level(logging.WARNING, logger="cloakbrowser"):
        args = persistent_seed_args(tmp_path, True, None)
    assert str(path) in caplog.text
    stored = path.read_text()
    assert args == [f"--fingerprint={stored.strip()}"]
    assert 10000 <= int(stored) <= 99999


def test_python_file_format_is_cross_wrapper(tmp_path):
    """JS and .NET tests read this exact content; keep the format pinned."""
    persistent_seed_args(tmp_path, True, None)
    assert (tmp_path / PROFILE_SEED_FILE).read_bytes().decode("ascii").rstrip("\n").isdigit()
    (tmp_path / PROFILE_SEED_FILE).write_text("12345\n")
    assert persistent_seed_args(tmp_path, True, ["--x"]) == ["--fingerprint=12345", "--x"]


def test_empty_user_data_dir_is_ignored():
    assert persistent_seed_args("", True, ["--x"]) == ["--x"]


def test_concurrent_first_launches_agree(tmp_path):
    results, barrier = [], threading.Barrier(16)

    def run():
        barrier.wait()
        results.append(persistent_seed_args(tmp_path, True, None)[0])

    threads = [threading.Thread(target=run) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(set(results)) == 1
    assert _listing(tmp_path) == [PROFILE_SEED_FILE]


def test_no_hard_link_support_falls_back_to_exclusive_create(tmp_path):
    """FAT/exFAT and some network mounts reject link() with ENOTSUP/EPERM."""
    import errno

    with patch("cloakbrowser.config.os.link", side_effect=OSError(errno.ENOTSUP, "not supported")):
        first = persistent_seed_args(tmp_path, True, None)
        assert persistent_seed_args(tmp_path, True, None) == first
    stored = (tmp_path / PROFILE_SEED_FILE).read_text()
    assert first == [f"--fingerprint={stored.strip()}"]
    assert _listing(tmp_path) == [PROFILE_SEED_FILE]
