"""Unit tests for _build_args timezone/locale injection."""

from cloakbrowser.browser import _build_args


def test_timezone_injected():
    """--timezone flag should appear when timezone is set."""
    args = _build_args(stealth_args=True, extra_args=None, timezone="America/New_York")
    assert "--timezone=America/New_York" in args


def test_locale_injected():
    """--lang flag should appear when locale is set."""
    args = _build_args(stealth_args=True, extra_args=None, locale="en-US")
    assert "--lang=en-US" in args


def test_both_injected():
    """Both flags should appear when both are set."""
    args = _build_args(stealth_args=True, extra_args=None, timezone="Europe/Berlin", locale="de-DE")
    assert "--timezone=Europe/Berlin" in args
    assert "--lang=de-DE" in args


def test_timezone_independent_of_stealth_args():
    """--timezone should be injected even when stealth_args=False."""
    args = _build_args(stealth_args=False, extra_args=None, timezone="America/New_York", locale="en-US")
    assert "--timezone=America/New_York" in args
    assert "--lang=en-US" in args
    # No stealth fingerprint args
    assert not any(a.startswith("--fingerprint=") for a in args)


def test_no_flags_when_not_set():
    """No timezone/lang flags when params are None."""
    args = _build_args(stealth_args=True, extra_args=None)
    assert not any(a.startswith("--timezone=") for a in args)
    assert not any(a.startswith("--lang=") for a in args)


def test_extra_args_preserved():
    """Extra args should still be included alongside timezone/locale."""
    args = _build_args(stealth_args=True, extra_args=["--disable-gpu"], timezone="Asia/Tokyo", locale="ja-JP")
    assert "--disable-gpu" in args
    assert "--timezone=Asia/Tokyo" in args
    assert "--lang=ja-JP" in args
