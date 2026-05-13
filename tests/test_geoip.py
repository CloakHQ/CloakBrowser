"""Unit tests for GeoIP-based timezone/locale detection."""

import types
from unittest.mock import patch
import time

import pytest

from cloakbrowser.browser import maybe_resolve_geoip
from cloakbrowser.geoip import (
    COUNTRY_LOCALE_MAP,
    _download_geoip_db,
    _ensure_geoip_db,
    _maybe_trigger_update,
    _resolve_exit_ip,
    _is_private_ip,
    _resolve_proxy_ip,
    resolve_proxy_geo_with_ip,
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


def test_resolve_hostname_returns_none_when_dns_empty():
    with patch("cloakbrowser.geoip.socket.getaddrinfo", return_value=[]):
        assert _resolve_proxy_ip("http://proxy.example:8888") is None


def test_resolve_hostname_returns_none_when_dns_raises():
    with patch("cloakbrowser.geoip.socket.getaddrinfo", side_effect=OSError("dns fail")):
        assert _resolve_proxy_ip("http://proxy.example:8888") is None


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


class _FakeCityResponse:
    def __init__(self, timezone="Europe/Berlin", country="DE"):
        self.location = types.SimpleNamespace(time_zone=timezone)
        self.country = types.SimpleNamespace(iso_code=country)


class _FakeReader:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def city(self, ip):
        return _FakeCityResponse()


def _install_fake_geoip(monkeypatch, reader=_FakeReader):
    geoip2_mod = types.ModuleType("geoip2")
    database_mod = types.ModuleType("geoip2.database")
    database_mod.Reader = reader
    geoip2_mod.database = database_mod
    monkeypatch.setitem(__import__("sys").modules, "geoip2", geoip2_mod)
    monkeypatch.setitem(__import__("sys").modules, "geoip2.database", database_mod)


def test_resolve_geo_with_exit_ip_success(monkeypatch, tmp_path):
    _install_fake_geoip(monkeypatch)
    with patch("cloakbrowser.geoip._ensure_geoip_db", return_value=tmp_path / "GeoLite2-City.mmdb"):
        with patch("cloakbrowser.geoip._resolve_exit_ip", return_value="8.8.8.8"):
            assert resolve_proxy_geo_with_ip("http://proxy:8080") == (
                "Europe/Berlin",
                "de-DE",
                "8.8.8.8",
            )


def test_resolve_geo_falls_back_to_proxy_ip(monkeypatch, tmp_path):
    _install_fake_geoip(monkeypatch)
    with patch("cloakbrowser.geoip._ensure_geoip_db", return_value=tmp_path / "GeoLite2-City.mmdb"):
        with patch("cloakbrowser.geoip._resolve_exit_ip", return_value=None):
            with patch("cloakbrowser.geoip._resolve_proxy_ip", return_value="1.1.1.1"):
                assert resolve_proxy_geo_with_ip("http://proxy:8080")[2] == "1.1.1.1"


def test_resolve_geo_returns_none_when_no_ip(monkeypatch, tmp_path):
    _install_fake_geoip(monkeypatch)
    with patch("cloakbrowser.geoip._ensure_geoip_db", return_value=tmp_path / "GeoLite2-City.mmdb"):
        with patch("cloakbrowser.geoip._resolve_exit_ip", return_value=None):
            with patch("cloakbrowser.geoip._resolve_proxy_ip", return_value=None):
                assert resolve_proxy_geo_with_ip("http://proxy:8080") == (None, None, None)


def test_resolve_geo_returns_ip_when_reader_fails(monkeypatch, tmp_path):
    class BrokenReader(_FakeReader):
        def city(self, ip):
            raise RuntimeError("bad mmdb")

    _install_fake_geoip(monkeypatch, BrokenReader)
    with patch("cloakbrowser.geoip._ensure_geoip_db", return_value=tmp_path / "GeoLite2-City.mmdb"):
        with patch("cloakbrowser.geoip._resolve_exit_ip", return_value="8.8.8.8"):
            assert resolve_proxy_geo_with_ip("http://proxy:8080") == (None, None, "8.8.8.8")


def test_resolve_exit_ip_success():
    import httpx

    response = types.SimpleNamespace(
        text="8.8.8.8\n",
        raise_for_status=lambda: None,
    )
    with patch.object(httpx, "get", return_value=response):
        assert _resolve_exit_ip("http://proxy:8080") == "8.8.8.8"


def test_resolve_exit_ip_unsupported_protocol_returns_none():
    import httpx

    with patch.object(httpx, "get", side_effect=httpx.UnsupportedProtocol("socks")):
        assert _resolve_exit_ip("socks5://proxy:1080") is None


def test_resolve_exit_ip_all_services_fail_returns_none():
    import httpx

    with patch.object(httpx, "get", side_effect=RuntimeError("timeout")):
        assert _resolve_exit_ip("http://proxy:8080") is None


def test_ensure_geoip_db_downloads_missing_db(tmp_path):
    db_path = tmp_path / "geoip" / "GeoLite2-City.mmdb"
    with patch("cloakbrowser.geoip._get_geoip_dir", return_value=db_path.parent):
        with patch("cloakbrowser.geoip._download_geoip_db") as download:
            assert _ensure_geoip_db() == db_path

    download.assert_called_once_with(db_path)


def test_ensure_geoip_db_returns_none_when_download_fails(tmp_path):
    db_path = tmp_path / "geoip" / "GeoLite2-City.mmdb"
    with patch("cloakbrowser.geoip._get_geoip_dir", return_value=db_path.parent):
        with patch("cloakbrowser.geoip._download_geoip_db", side_effect=RuntimeError("net")):
            assert _ensure_geoip_db() is None


def test_ensure_geoip_db_triggers_update_for_existing_db(tmp_path):
    db_path = tmp_path / "geoip" / "GeoLite2-City.mmdb"
    db_path.parent.mkdir()
    db_path.write_bytes(b"mmdb")
    with patch("cloakbrowser.geoip._get_geoip_dir", return_value=db_path.parent):
        with patch("cloakbrowser.geoip._maybe_trigger_update") as maybe_update:
            assert _ensure_geoip_db() == db_path

    maybe_update.assert_called_once_with(db_path)


def test_download_geoip_db_writes_chunks_atomically(tmp_path):
    import httpx

    dest = tmp_path / "GeoLite2-City.mmdb"

    class StreamResponse:
        headers = {"content-length": "4"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            return None

        def iter_bytes(self, chunk_size):
            yield b"ab"
            yield b"cd"

    with patch.object(httpx, "stream", return_value=StreamResponse()):
        _download_geoip_db(dest)

    assert dest.read_bytes() == b"abcd"
    assert not list(tmp_path.glob("*.tmp"))


def test_download_geoip_db_removes_temp_file_on_error(tmp_path):
    import httpx

    dest = tmp_path / "GeoLite2-City.mmdb"

    class BrokenStreamResponse:
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def raise_for_status(self):
            raise RuntimeError("bad status")

    with patch.object(httpx, "stream", return_value=BrokenStreamResponse()):
        with pytest.raises(RuntimeError, match="bad status"):
            _download_geoip_db(dest)

    assert not list(tmp_path.glob("*.tmp"))


def test_maybe_trigger_update_skips_fresh_db(tmp_path):
    db_path = tmp_path / "GeoLite2-City.mmdb"
    db_path.write_bytes(b"mmdb")
    with patch("cloakbrowser.geoip.threading.Thread") as thread:
        _maybe_trigger_update(db_path)

    thread.assert_not_called()


def test_maybe_trigger_update_starts_thread_for_stale_db(tmp_path):
    db_path = tmp_path / "GeoLite2-City.mmdb"
    db_path.write_bytes(b"mmdb")
    with patch("cloakbrowser.geoip.time.time", return_value=10_000_000_000):
        with patch("cloakbrowser.geoip.threading.Thread") as thread:
            _maybe_trigger_update(db_path)

    thread.assert_called_once()
    assert thread.call_args.kwargs["daemon"] is True


def test_maybe_trigger_update_ignores_stat_error(tmp_path):
    missing = tmp_path / "missing.mmdb"
    with patch("cloakbrowser.geoip.threading.Thread") as thread:
        _maybe_trigger_update(missing)

    thread.assert_not_called()


# ---------------------------------------------------------------------------
# maybe_resolve_geoip (browser.py helper)
# ---------------------------------------------------------------------------


def test_maybe_resolve_skips_when_geoip_false():
    tz, loc, ip = maybe_resolve_geoip(False, "http://proxy:8080", None, None)
    assert tz is None
    assert loc is None
    assert ip is None


def test_maybe_resolve_skips_when_no_proxy():
    tz, loc, ip = maybe_resolve_geoip(True, None, None, None)
    assert tz is None
    assert loc is None
    assert ip is None


def test_maybe_resolve_skips_when_both_explicit():
    """Explicit values should still resolve exit IP for WebRTC."""
    with patch("cloakbrowser.geoip._resolve_exit_ip", return_value="1.2.3.4"):
        tz, loc, ip = maybe_resolve_geoip(True, "http://proxy:8080", "Europe/Berlin", "de-DE")
    assert tz == "Europe/Berlin"
    assert loc == "de-DE"
    assert ip == "1.2.3.4"


def test_maybe_resolve_fills_missing_timezone():
    """When only locale is explicit, geoip should fill timezone."""
    with patch("cloakbrowser.geoip.resolve_proxy_geo_with_ip", return_value=("America/New_York", "en-US", "1.2.3.4")):
        tz, loc, ip = maybe_resolve_geoip(True, "http://proxy:8080", None, "fr-FR")
        assert tz == "America/New_York"
        assert loc == "fr-FR"  # Explicit wins


def test_maybe_resolve_fills_missing_locale():
    """When only timezone is explicit, geoip should fill locale."""
    with patch("cloakbrowser.geoip.resolve_proxy_geo_with_ip", return_value=("America/New_York", "en-US", "1.2.3.4")):
        tz, loc, ip = maybe_resolve_geoip(True, "http://proxy:8080", "Asia/Tokyo", None)
        assert tz == "Asia/Tokyo"  # Explicit wins
        assert loc == "en-US"


def test_maybe_resolve_fills_both():
    """When neither is set, geoip should fill both."""
    with patch("cloakbrowser.geoip.resolve_proxy_geo_with_ip", return_value=("Europe/Berlin", "de-DE", "5.6.7.8")):
        tz, loc, ip = maybe_resolve_geoip(True, "http://proxy:8080", None, None)
        assert tz == "Europe/Berlin"
        assert loc == "de-DE"
        assert ip == "5.6.7.8"


def test_maybe_resolve_geoip_timeout_returns_existing_values(monkeypatch):
    """A stalled proxy lookup should not block launch indefinitely."""
    mock_geoip2 = type("module", (), {"database": type("db", (), {"Reader": None})})()
    monkeypatch.setenv("CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS", "0.05")
    with patch.dict("sys.modules", {"geoip2": mock_geoip2, "geoip2.database": mock_geoip2.database}):
        with patch("cloakbrowser.geoip._ensure_geoip_db", return_value=object()):
            start = time.monotonic()
            tz, loc, ip = maybe_resolve_geoip(True, "http://203.0.113.10:8080", None, "fr-FR")
            elapsed = time.monotonic() - start

    assert (tz, loc, ip) == (None, "fr-FR", None)
    assert elapsed < 0.5


# ---------------------------------------------------------------------------
# _is_private_ip
# ---------------------------------------------------------------------------


def test_private_ip_loopback():
    assert _is_private_ip("127.0.0.1") is True


def test_private_ip_rfc1918():
    assert _is_private_ip("192.168.1.1") is True
    assert _is_private_ip("10.0.0.1") is True
    assert _is_private_ip("172.16.0.1") is True


def test_private_ip_public():
    assert _is_private_ip("8.8.8.8") is False
    assert _is_private_ip("64.176.168.43") is False
