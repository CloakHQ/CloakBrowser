"""Unit tests for the Windows-font probe used by `cloakbrowser info`.

The probe verifies *resolution* (fc-match), not presence in an fc-list dump.
The old substring check over-counted two ways and reported a complete font set
on an image where one family did not resolve at all — an `ok (8/8)` that hid a
real gap. These tests pin the resolution semantics.
"""

import subprocess
from unittest.mock import patch

import pytest

from cloakbrowser.browser import (
    _OFFICE_FONT_TELLS,
    _WINDOWS_FONT_TELLS,
    _count_fonts_present,
    _font_family_resolves,
    _windows_fonts_present,
)


def _fc_match(stdout: str, returncode: int = 0):
    """Patch fc-match to answer with `stdout`."""
    return patch(
        "subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=["fc-match"], returncode=returncode, stdout=stdout, stderr=""
        ),
    )


def test_exact_family_resolves():
    with _fc_match("Consolas"):
        assert _font_family_resolves("Consolas") is True


def test_case_and_whitespace_insensitive():
    with _fc_match("  consolas  "):
        assert _font_family_resolves("Consolas") is True


def test_alias_list_counts_as_resolved():
    """fc-match can answer with comma-separated aliases for one family."""
    with _fc_match("Segoe UI,Segoe UI Light"):
        assert _font_family_resolves("Segoe UI Light") is True


def test_fallback_font_does_not_count():
    """fc-match always answers something — the default when it cannot match.

    This is the whole point: asking for Franklin Gothic on an image that lacks it
    returns NimbusSans, and the family is undetectable by any font-fingerprinting
    script. It must read as absent.
    """
    with _fc_match("Nimbus Sans"):
        assert _font_family_resolves("Franklin Gothic") is False


def test_longer_family_does_not_satisfy_a_shorter_request():
    """"Segoe UI" must not be satisfied by "Segoe UI Emoji".

    Different family, different metrics, and commonly present on its own — the
    substring check scored it as a hit.
    """
    with _fc_match("Segoe UI Emoji"):
        assert _font_family_resolves("Segoe UI") is False


def test_missing_fc_match_is_unknown_not_absent():
    """None means "cannot tell"; 0 means "genuinely none installed"."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert _font_family_resolves("Consolas") is None
        assert _count_fonts_present(_WINDOWS_FONT_TELLS) is None
        assert _windows_fonts_present() is None


def test_nonzero_exit_is_unknown():
    with _fc_match("", returncode=1):
        assert _font_family_resolves("Consolas") is None


@pytest.mark.parametrize("tells", [_WINDOWS_FONT_TELLS, _OFFICE_FONT_TELLS])
def test_all_resolving_counts_the_whole_set(tells):
    with patch("cloakbrowser.browser._font_family_resolves", return_value=True):
        assert _count_fonts_present(tells) == len(tells)


def test_partial_set_is_counted_and_reported_incomplete():
    """The reported case: one family of eight fails to resolve.

    The old check said ok (8/8); the fix must say 7/8 and refuse to call the set
    complete, since a missing font degrades the Windows persona.
    """
    def _resolves(family: str, timeout: float = 5.0) -> bool:
        return family != "Franklin Gothic"

    with patch("cloakbrowser.browser._font_family_resolves", side_effect=_resolves):
        assert _count_fonts_present(_WINDOWS_FONT_TELLS) == len(_WINDOWS_FONT_TELLS) - 1
        assert _windows_fonts_present() is False


def test_none_resolving_is_zero_not_unknown():
    """fc-match present but nothing matches -> a real 0, distinct from None."""
    with patch("cloakbrowser.browser._font_family_resolves", return_value=False):
        assert _count_fonts_present(_WINDOWS_FONT_TELLS) == 0


def test_a_single_undeterminable_family_makes_the_count_unknown():
    """A partial answer must not be reported as a count.

    An unresolved family is indistinguishable from a missing one, so counting
    what did answer would under-report and nag about fonts that are installed.
    """
    def _resolves(family: str, timeout: float = 5.0):
        return None if family == "Consolas" else True

    with patch("cloakbrowser.browser._font_family_resolves", side_effect=_resolves):
        assert _count_fonts_present(_WINDOWS_FONT_TELLS) is None


def test_probe_is_bounded_across_all_families_not_per_call():
    """One fc-match per family must not multiply the ceiling by the family count.

    A wedged fontconfig previously cost 5s per family. The budget now covers the
    whole probe, and running out reports unknown rather than a wrong count.
    """
    import time

    from cloakbrowser.browser import _FONT_PROBE_TIMEOUT_SECONDS

    calls: list[float] = []

    def _slow(argv, *args, **kwargs):
        calls.append(kwargs.get("timeout", -1))
        time.sleep(0.05)
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))

    start = time.monotonic()
    with patch("subprocess.run", side_effect=_slow):
        assert _count_fonts_present(_WINDOWS_FONT_TELLS) is None
    assert time.monotonic() - start < _FONT_PROBE_TIMEOUT_SECONDS + 2
    # Each call gets the REMAINING budget, so the allowance shrinks monotonically.
    assert calls == sorted(calls, reverse=True)
