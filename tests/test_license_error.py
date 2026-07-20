"""Tests for license exit-code -> message surfacing (license_error_message)."""

import pytest

from cloakbrowser import CloakBrowserLicenseError
from cloakbrowser.license import license_error_message


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
        (79, "not writable"),
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
