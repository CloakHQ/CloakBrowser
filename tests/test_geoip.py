"""Unit tests for GeoIP-based timezone/locale detection."""

from unittest.mock import MagicMock, patch
import threading
import time

import pytest

from cloakbrowser.browser import maybe_resolve_geoip
from cloakbrowser.geoip import (
    COUNTRY_LOCALE_MAP,
    _is_private_ip,
    _resolve_exit_ip,
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
        with pytest.raises(ImportError, match=r"pip install 'cloakbrowser\[geoip\]'"):
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


def test_resolve_geo_keeps_exit_ip_when_db_missing():
    """DB missing but IP resolvable → still return the exit IP for WebRTC spoofing.

    Resolving the egress IP does not need the GeoIP DB, so a DB download failure
    must not drop it — otherwise WebRTC could fall back to the real IP behind a
    proxy while the connection shows the proxy IP (a deanonymization).
    """
    mock_geoip2 = type("module", (), {"database": type("db", (), {"Reader": None})})()
    with patch.dict("sys.modules", {"geoip2": mock_geoip2, "geoip2.database": mock_geoip2.database}):
        with patch("cloakbrowser.geoip._ensure_geoip_db", return_value=None):
            with patch("cloakbrowser.geoip._resolve_exit_ip", return_value="9.8.7.6"):
                from cloakbrowser.geoip import resolve_proxy_geo_with_ip
                assert resolve_proxy_geo_with_ip("http://10.50.96.5:8888") == (None, None, "9.8.7.6")


# ---------------------------------------------------------------------------
# _resolve_exit_ip direct (no-proxy) fetch
# ---------------------------------------------------------------------------


def test_resolve_exit_ip_no_proxy_fetches_directly():
    """No proxy → echo services queried directly (proxy=None)."""
    resp = MagicMock()
    resp.text = "5.6.7.8"
    resp.raise_for_status = MagicMock()
    with patch("httpx.get", return_value=resp) as mock_get:
        ip = _resolve_exit_ip(None)
    assert ip == "5.6.7.8"
    # httpx.get called with proxy=None (direct), not through a proxy
    assert mock_get.call_args.kwargs.get("proxy") is None


# ---------------------------------------------------------------------------
# maybe_resolve_geoip (browser.py helper)
# ---------------------------------------------------------------------------


def test_maybe_resolve_skips_when_geoip_false():
    tz, loc, ip = maybe_resolve_geoip(False, "http://proxy:8080", None, None)
    assert tz is None
    assert loc is None
    assert ip is None


def test_maybe_resolve_no_proxy_uses_machine_ip():
    """With no proxy, geoip resolves the machine's own public IP for tz/locale."""
    with patch(
        "cloakbrowser.geoip.resolve_proxy_geo_with_ip",
        return_value=("Europe/Berlin", "de-DE", "5.6.7.8"),
    ) as m:
        tz, loc, ip = maybe_resolve_geoip(True, None, None, None)
    # Called with proxy_url=None → echo services resolve machine IP
    m.assert_called_once_with(None)
    assert tz == "Europe/Berlin"
    assert loc == "de-DE"
    assert ip == "5.6.7.8"  # drives --fingerprint-webrtc-ip


def test_maybe_resolve_no_proxy_both_explicit_skips_ip():
    """No proxy + explicit tz/locale → skip the exit-IP fetch entirely.

    With no proxy the WebRTC IP would just be the real connection IP the site
    already sees (a no-op), so we don't make a third-party echo call.
    """
    with patch(
        "cloakbrowser.geoip.resolve_proxy_exit_ip", return_value="5.6.7.8"
    ) as m:
        tz, loc, ip = maybe_resolve_geoip(True, None, "Europe/Berlin", "de-DE")
    m.assert_not_called()
    assert tz == "Europe/Berlin"
    assert loc == "de-DE"
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


def test_maybe_resolve_raw_timezone_flag_wins_over_geoip():
    """A raw --fingerprint-timezone in args counts as explicit; geoip must not clobber it."""
    with patch(
        "cloakbrowser.geoip.resolve_proxy_geo_with_ip",
        return_value=("Europe/Berlin", "de-DE", "5.6.7.8"),
    ):
        tz, loc, ip = maybe_resolve_geoip(
            True, "http://proxy:8080", None, None,
            ["--fingerprint-timezone=Asia/Tokyo"],
        )
    assert tz == "Asia/Tokyo"  # user's raw flag survives
    assert loc == "de-DE"  # not raw-flagged → geoip fills it
    assert ip == "5.6.7.8"


def test_maybe_resolve_raw_lang_flag_wins_over_geoip():
    """A raw --lang in args counts as explicit locale; geoip must not clobber it."""
    with patch(
        "cloakbrowser.geoip.resolve_proxy_geo_with_ip",
        return_value=("Europe/Berlin", "de-DE", "5.6.7.8"),
    ):
        tz, loc, ip = maybe_resolve_geoip(
            True, "http://proxy:8080", None, None, ["--lang=fr-FR"],
        )
    assert tz == "Europe/Berlin"  # not raw-flagged → geoip fills it
    assert loc == "fr-FR"  # user's raw flag survives


def test_maybe_resolve_raw_flags_both_skip_geo_lookup():
    """Both tz+locale raw-flagged → treated as fully explicit, only exit IP resolved."""
    with patch("cloakbrowser.geoip.resolve_proxy_geo_with_ip") as geo, patch(
        "cloakbrowser.geoip._resolve_exit_ip", return_value="1.2.3.4"
    ):
        tz, loc, ip = maybe_resolve_geoip(
            True, "http://proxy:8080", None, None,
            ["--fingerprint-timezone=Asia/Tokyo", "--fingerprint-locale=ja-JP"],
        )
    geo.assert_not_called()
    assert tz == "Asia/Tokyo"
    assert loc == "ja-JP"
    assert ip == "1.2.3.4"


def test_maybe_resolve_param_beats_raw_flag():
    """An explicit timezone= param takes precedence over a differing raw flag."""
    with patch("cloakbrowser.geoip._resolve_exit_ip", return_value="1.2.3.4"), patch(
        "cloakbrowser.geoip.resolve_proxy_geo_with_ip",
        return_value=("Europe/Berlin", "de-DE", "5.6.7.8"),
    ):
        tz, loc, ip = maybe_resolve_geoip(
            True, "http://proxy:8080", "America/New_York", None,
            ["--fingerprint-timezone=Asia/Tokyo"],
        )
    assert tz == "America/New_York"  # param wins over raw flag
    assert loc == "de-DE"


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


# ---------------------------------------------------------------------------
# GeoIP DB download: atomic replace + concurrency guard (issue #458)
# ---------------------------------------------------------------------------


def test_download_overwrites_existing_db(tmp_path):
    """os.replace must overwrite a pre-existing DB (Windows rename would fail)."""
    from cloakbrowser import geoip

    dest = tmp_path / "GeoLite2-City.mmdb"
    dest.write_bytes(b"old")

    def fake_stream(*_a, **_k):
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def raise_for_status(self):
                pass

            headers = {"content-length": "3"}

            def iter_bytes(self, chunk_size=0):
                yield b"new"

        return _Resp()

    with patch("httpx.stream", fake_stream):
        geoip._download_geoip_db(dest)

    assert dest.read_bytes() == b"new"


def test_ensure_db_downloads_once_under_concurrency(tmp_path):
    """Concurrent first-use launches must trigger only one download."""
    from cloakbrowser import geoip

    dest = tmp_path / "GeoLite2-City.mmdb"
    calls = []
    barrier = threading.Barrier(5)

    def fake_download(path):
        calls.append(path)
        time.sleep(0.05)  # hold the lock so others queue behind it
        path.write_bytes(b"db")

    with patch.object(geoip, "_get_geoip_dir", return_value=tmp_path), patch.object(
        geoip, "_download_geoip_db", side_effect=fake_download
    ):
        results = []

        def worker():
            barrier.wait()
            results.append(geoip._ensure_geoip_db())

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert len(calls) == 1  # only one thread actually downloaded
    assert all(r == dest for r in results)
