"""Unit tests for GeoIP-based timezone/locale detection."""

from unittest.mock import patch

import pytest

from cloakbrowser.browser import _maybe_resolve_geoip
from cloakbrowser.geoip import (
    COUNTRY_LOCALE_MAP,
    _resolve_proxy_ip,
)


# ---------------------------------------------------------------------------
# _resolve_proxy_ip
# ---------------------------------------------------------------------------


def test_resolve_literal_ipv4():
    assert _resolve_proxy_ip("http://10.50.96.5:8888") == "10.50.96.5"


def test_resolve_literal_ipv4_with_auth():
    assert _resolve_proxy_ip("http://user:pass@10.50.96.5:8888") == "10.50.96.5"


def test_resolve_literal_ipv6():
    ip = _resolve_proxy_ip("http://[::1]:8888")
    assert ip == "::1"


def test_resolve_hostname():
    """DNS resolution of a known hostname should return an IP."""
    ip = _resolve_proxy_ip("http://localhost:8888")
    assert ip is not None
    assert ip in ("127.0.0.1", "::1")


def test_resolve_invalid_url():
    assert _resolve_proxy_ip("not-a-url") is None


def test_resolve_empty():
    assert _resolve_proxy_ip("") is None


# ---------------------------------------------------------------------------
# COUNTRY_LOCALE_MAP
# ---------------------------------------------------------------------------


def test_locale_map_has_common_countries():
    for code in ("US", "GB", "DE", "FR", "JP", "BR", "IL", "RU"):
        assert code in COUNTRY_LOCALE_MAP, f"Missing {code}"


def test_locale_map_values_are_bcp47():
    """All locales should be language-REGION format."""
    for code, locale in COUNTRY_LOCALE_MAP.items():
        parts = locale.split("-")
        assert len(parts) == 2, f"{code}: {locale} not language-REGION"
        assert parts[0].islower(), f"{code}: language part should be lowercase"
        assert parts[1].isupper(), f"{code}: region part should be uppercase"


# ---------------------------------------------------------------------------
# resolve_proxy_geo fallbacks
# ---------------------------------------------------------------------------


def test_resolve_geo_raises_when_geoip2_missing():
    """Should raise ImportError with install instructions when geoip2 not installed."""
    with patch.dict("sys.modules", {"geoip2": None, "geoip2.database": None}):
        from importlib import reload
        import cloakbrowser.geoip as geoip_mod
        reload(geoip_mod)
        with pytest.raises(ImportError, match="pip install cloakbrowser"):
            geoip_mod.resolve_proxy_geo("http://10.50.96.5:8888")
        # Restore
        reload(geoip_mod)


def test_resolve_geo_returns_none_when_db_missing():
    """Should return (None, None) when DB file doesn't exist."""
    mock_geoip2 = type("module", (), {"database": type("db", (), {"Reader": None})})()
    with patch.dict("sys.modules", {"geoip2": mock_geoip2, "geoip2.database": mock_geoip2.database}):
        with patch("cloakbrowser.geoip._ensure_geoip_db", return_value=None):
            with patch("cloakbrowser.geoip._resolve_exit_ip", return_value=None):
                from cloakbrowser.geoip import resolve_proxy_geo
                assert resolve_proxy_geo("http://10.50.96.5:8888") == (None, None)


# ---------------------------------------------------------------------------
# _maybe_resolve_geoip (browser.py helper)
# ---------------------------------------------------------------------------


def test_maybe_resolve_skips_when_geoip_false():
    tz, loc = _maybe_resolve_geoip(False, "http://proxy:8080", None, None)
    assert tz is None
    assert loc is None


def test_maybe_resolve_skips_when_no_proxy():
    tz, loc = _maybe_resolve_geoip(True, None, None, None)
    assert tz is None
    assert loc is None


def test_maybe_resolve_skips_when_both_explicit():
    """Explicit values should not trigger geoip resolution."""
    tz, loc = _maybe_resolve_geoip(True, "http://proxy:8080", "Europe/Berlin", "de-DE")
    assert tz == "Europe/Berlin"
    assert loc == "de-DE"


def test_maybe_resolve_fills_missing_timezone():
    """When only locale is explicit, geoip should fill timezone."""
    with patch("cloakbrowser.geoip.resolve_proxy_geo", return_value=("America/New_York", "en-US")):
        tz, loc = _maybe_resolve_geoip(True, "http://proxy:8080", None, "fr-FR")
        assert tz == "America/New_York"
        assert loc == "fr-FR"  # Explicit wins


def test_maybe_resolve_fills_missing_locale():
    """When only timezone is explicit, geoip should fill locale."""
    with patch("cloakbrowser.geoip.resolve_proxy_geo", return_value=("America/New_York", "en-US")):
        tz, loc = _maybe_resolve_geoip(True, "http://proxy:8080", "Asia/Tokyo", None)
        assert tz == "Asia/Tokyo"  # Explicit wins
        assert loc == "en-US"


def test_maybe_resolve_fills_both():
    """When neither is set, geoip should fill both."""
    with patch("cloakbrowser.geoip.resolve_proxy_geo", return_value=("Europe/Berlin", "de-DE")):
        tz, loc = _maybe_resolve_geoip(True, "http://proxy:8080", None, None)
        assert tz == "Europe/Berlin"
        assert loc == "de-DE"
