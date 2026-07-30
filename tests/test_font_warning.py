"""Unit tests for the Linux Windows-font mismatch warning (browser.py).

The warning fires once per environment when spoofing Windows on a font-less
Linux host. These tests mock platform, fc-match, and the cache dir so they are
host-independent and need no binary. The warning is written straight to stderr
(like the welcome banner and the JS/.NET wrappers), so capture it with capsys.
"""

import subprocess
from unittest.mock import patch

import pytest

import cloakbrowser.browser as browser

WIN_ARGS = ["--fingerprint-platform=windows", "--no-sandbox"]
MSG = "Incomplete Windows font set"

ALL_WIN_FONTS = set(browser._WINDOWS_FONT_TELLS)

# What fontconfig answers when it cannot match: a real family, which is exactly
# why the probe has to compare the answer against the request.
FALLBACK_FAMILY = "Nimbus Sans"


@pytest.fixture(autouse=True)
def _reset_in_process_flag():
    """Each test starts with the once-per-process guard cleared."""
    browser._font_warning_checked = False
    yield
    browser._font_warning_checked = False


def _fc_match(present=(), returncode=0):
    """subprocess.run side effect mimicking `fc-match --format=%{family} <fam>`.

    One invocation per family, so the mock answers from the requested family
    rather than returning one listing for everything.
    """
    present = set(present)

    def _run(argv, *args, **kwargs):
        family = argv[-1]
        stdout = family if family in present else FALLBACK_FAMILY
        return subprocess.CompletedProcess(argv, returncode, stdout=stdout, stderr="")

    return _run


def test_warns_when_no_windows_fonts(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("CLOAKBROWSER_SUPPRESS_FONT_WARNING", raising=False)
    with (
        patch("platform.system", return_value="Linux"),
        patch("subprocess.run", side_effect=_fc_match()),
        patch("cloakbrowser.config.get_cache_dir", return_value=tmp_path),
    ):
        browser._maybe_warn_windows_fonts(WIN_ARGS)
    assert MSG in capsys.readouterr().err
    assert (tmp_path / ".font_warning_shown").exists()


def test_in_process_flag_blocks_second_call(tmp_path, capsys):
    with (
        patch("platform.system", return_value="Linux"),
        patch("subprocess.run", side_effect=_fc_match()) as mrun,
        patch("cloakbrowser.config.get_cache_dir", return_value=tmp_path),
    ):
        browser._maybe_warn_windows_fonts(WIN_ARGS)
        assert MSG in capsys.readouterr().err  # first call warns (and drains buffer)
        after_first = mrun.call_count
        browser._maybe_warn_windows_fonts(WIN_ARGS)
    assert MSG not in capsys.readouterr().err
    # One fc-match per family, so count the probe, not the invocations: the
    # second call must add none.
    assert after_first == len(browser._WINDOWS_FONT_TELLS)
    assert mrun.call_count == after_first


def test_marker_suppresses_across_processes(tmp_path, capsys):
    """An existing marker (prior process) skips the warning even after a flag reset."""
    (tmp_path / ".font_warning_shown").write_text("")
    with (
        patch("platform.system", return_value="Linux"),
        patch("subprocess.run", side_effect=_fc_match()),
        patch("cloakbrowser.config.get_cache_dir", return_value=tmp_path),
    ):
        browser._maybe_warn_windows_fonts(WIN_ARGS)
    assert MSG not in capsys.readouterr().err


def test_env_suppresses_and_writes_no_marker(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("CLOAKBROWSER_SUPPRESS_FONT_WARNING", "1")
    with (
        patch("platform.system", return_value="Linux"),
        patch("subprocess.run", side_effect=_fc_match()),
        patch("cloakbrowser.config.get_cache_dir", return_value=tmp_path),
    ):
        browser._maybe_warn_windows_fonts(WIN_ARGS)
    assert MSG not in capsys.readouterr().err
    assert not (tmp_path / ".font_warning_shown").exists()


def test_no_warn_on_non_linux(tmp_path, capsys):
    with (
        patch("platform.system", return_value="Darwin"),
        patch("cloakbrowser.config.get_cache_dir", return_value=tmp_path),
    ):
        browser._maybe_warn_windows_fonts(WIN_ARGS)
    assert MSG not in capsys.readouterr().err


def test_no_warn_when_platform_overridden(tmp_path, capsys):
    with (
        patch("platform.system", return_value="Linux"),
        patch("cloakbrowser.config.get_cache_dir", return_value=tmp_path),
    ):
        browser._maybe_warn_windows_fonts(["--fingerprint-platform=linux"])
    assert MSG not in capsys.readouterr().err


def test_no_warn_no_crash_when_fc_match_absent(tmp_path, capsys):
    with (
        patch("platform.system", return_value="Linux"),
        patch("subprocess.run", side_effect=FileNotFoundError()),
        patch("cloakbrowser.config.get_cache_dir", return_value=tmp_path),
    ):
        browser._maybe_warn_windows_fonts(WIN_ARGS)  # must not raise
    assert MSG not in capsys.readouterr().err
    assert not (tmp_path / ".font_warning_shown").exists()


def test_no_warn_when_full_set_present(tmp_path, capsys):
    with (
        patch("platform.system", return_value="Linux"),
        patch("subprocess.run", side_effect=_fc_match(ALL_WIN_FONTS)),
        patch("cloakbrowser.config.get_cache_dir", return_value=tmp_path),
    ):
        browser._maybe_warn_windows_fonts(WIN_ARGS)
    assert MSG not in capsys.readouterr().err


def test_warns_on_partial_set(tmp_path, capsys):
    # Only 1 of the 8 tells resolves — strict check treats this as incomplete.
    with (
        patch("platform.system", return_value="Linux"),
        patch("subprocess.run", side_effect=_fc_match({"Segoe UI"})),
        patch("cloakbrowser.config.get_cache_dir", return_value=tmp_path),
    ):
        browser._maybe_warn_windows_fonts(WIN_ARGS)
    assert MSG in capsys.readouterr().err


def test_font_file_path_alone_does_not_satisfy_a_family(tmp_path, capsys, monkeypatch):
    """The bug the fc-match switch fixes.

    `fc-list` prints file paths alongside family names, so a host carrying only
    `/usr/share/fonts/framd.ttf` scored as having Franklin Gothic under the old
    substring check while `fc-match "Franklin Gothic"` fell through to a
    fallback. A family the renderer cannot resolve is undetectable by any
    font-fingerprinting script, so it must warn.
    """
    monkeypatch.delenv("CLOAKBROWSER_SUPPRESS_FONT_WARNING", raising=False)
    # Everything resolves except Franklin Gothic, which only exists as a file.
    present = ALL_WIN_FONTS - {"Franklin Gothic"}
    with (
        patch("platform.system", return_value="Linux"),
        patch("subprocess.run", side_effect=_fc_match(present)),
        patch("cloakbrowser.config.get_cache_dir", return_value=tmp_path),
    ):
        browser._maybe_warn_windows_fonts(WIN_ARGS)
    assert MSG in capsys.readouterr().err
    assert browser._count_fonts_present(browser._WINDOWS_FONT_TELLS) is not None
