"""Tests for proxy URL parsing and credential extraction."""

from unittest.mock import patch

from cloakbrowser.browser import _build_proxy_kwargs, maybe_resolve_geoip, _parse_proxy_url


class TestParseProxyUrl:
    def test_no_credentials(self):
        assert _parse_proxy_url("http://proxy:8080") == {"server": "http://proxy:8080"}

    def test_with_credentials(self):
        result = _parse_proxy_url("http://user:pass@proxy:8080")
        assert result == {"server": "http://proxy:8080", "username": "user", "password": "pass"}

    def test_url_encoded_password(self):
        result = _parse_proxy_url("http://user:p%40ss%3Aword@proxy:8080")
        assert result["password"] == "p@ss:word"
        assert result["username"] == "user"
        assert result["server"] == "http://proxy:8080"

    def test_socks5(self):
        result = _parse_proxy_url("socks5://user:pass@proxy:1080")
        assert result["server"] == "socks5://proxy:1080"
        assert result["username"] == "user"
        assert result["password"] == "pass"

    def test_no_port(self):
        result = _parse_proxy_url("http://user:pass@proxy")
        assert result["server"] == "http://proxy"
        assert result["username"] == "user"

    def test_username_only(self):
        result = _parse_proxy_url("http://user@proxy:8080")
        assert result["server"] == "http://proxy:8080"
        assert result["username"] == "user"
        assert "password" not in result


class TestBuildProxyKwargs:
    def test_none(self):
        assert _build_proxy_kwargs(None) == {}

    def test_simple_proxy(self):
        result = _build_proxy_kwargs("http://proxy:8080")
        assert result == {"proxy": {"server": "http://proxy:8080"}}

    def test_proxy_with_auth(self):
        result = _build_proxy_kwargs("http://user:pass@proxy:8080")
        assert result == {
            "proxy": {"server": "http://proxy:8080", "username": "user", "password": "pass"}
        }

    def test_proxy_dict_passthrough(self):
        proxy_dict = {"server": "http://proxy:8080", "bypass": ".google.com,localhost"}
        result = _build_proxy_kwargs(proxy_dict)
        assert result == {"proxy": proxy_dict}

    def test_proxy_dict_with_auth(self):
        proxy_dict = {
            "server": "http://proxy:8080",
            "username": "user",
            "password": "pass",
            "bypass": ".example.com",
        }
        result = _build_proxy_kwargs(proxy_dict)
        assert result == {"proxy": proxy_dict}


class TestMaybeResolveGeoip:
    @patch("cloakbrowser.geoip.resolve_proxy_geo", return_value=("America/New_York", "en-US"))
    def test_geoip_with_string_proxy(self, mock_geo):
        tz, locale = maybe_resolve_geoip(True, "http://proxy:8080", None, None)
        mock_geo.assert_called_once_with("http://proxy:8080")
        assert tz == "America/New_York"
        assert locale == "en-US"

    @patch("cloakbrowser.geoip.resolve_proxy_geo", return_value=("Europe/London", "en-GB"))
    def test_geoip_with_dict_proxy_extracts_server(self, mock_geo):
        proxy_dict = {"server": "http://proxy:8080", "bypass": ".google.com"}
        tz, locale = maybe_resolve_geoip(True, proxy_dict, None, None)
        mock_geo.assert_called_once_with("http://proxy:8080")
        assert tz == "Europe/London"
        assert locale == "en-GB"

    def test_geoip_disabled_skips_resolution(self):
        tz, locale = maybe_resolve_geoip(False, "http://proxy:8080", None, None)
        assert tz is None
        assert locale is None

    def test_geoip_no_proxy_skips_resolution(self):
        tz, locale = maybe_resolve_geoip(True, None, None, None)
        assert tz is None
        assert locale is None

    @patch("cloakbrowser.geoip.resolve_proxy_geo", return_value=("Asia/Tokyo", "ja-JP"))
    def test_geoip_preserves_explicit_timezone(self, mock_geo):
        tz, locale = maybe_resolve_geoip(True, "http://proxy:8080", "Europe/Berlin", None)
        assert tz == "Europe/Berlin"
        assert locale == "ja-JP"

    @patch("cloakbrowser.geoip.resolve_proxy_geo", return_value=("America/New_York", "en-US"))
    def test_geoip_normalizes_bare_proxy_with_creds(self, mock_geo):
        # "user:pass@host:port" must be normalized to http:// before geoip lookup.
        tz, locale = maybe_resolve_geoip(True, "user:pass@proxy:8080", None, None)
        mock_geo.assert_called_once_with("http://user:pass@proxy:8080")
        assert tz == "America/New_York"
        assert locale == "en-US"

    @patch("cloakbrowser.geoip.resolve_proxy_geo", return_value=("America/New_York", "en-US"))
    def test_geoip_normalizes_schemeless_proxy_no_creds(self, mock_geo):
        # "host:port" (no @ and no scheme) must also be normalized.
        tz, locale = maybe_resolve_geoip(True, "proxy:8080", None, None)
        mock_geo.assert_called_once_with("http://proxy:8080")
        assert tz == "America/New_York"


class TestBareProxyFormat:
    """_parse_proxy_url must handle bare 'user:pass@host:port' strings (no scheme)."""

    def test_bare_with_credentials(self):
        r = _parse_proxy_url("user:pass@proxy:8080")
        assert r["username"] == "user"
        assert r["password"] == "pass"
        assert r["server"] == "http://proxy:8080"

    def test_bare_credentials_not_in_server(self):
        r = _parse_proxy_url("user:pass@proxy1.example.com:5610")
        assert "user" not in r["server"]
        assert "pass" not in r["server"]

    def test_bare_username_only(self):
        r = _parse_proxy_url("user@proxy:8080")
        assert r["username"] == "user"
        assert "password" not in r
        assert r["server"] == "http://proxy:8080"

    def test_bare_no_port(self):
        r = _parse_proxy_url("user:pass@proxy.example.com")
        assert r["username"] == "user"
        assert r["password"] == "pass"
        assert r["server"] == "http://proxy.example.com"

    def test_bare_no_credentials_passthrough(self):
        # "host:port" without @ — no scheme, no creds — pass through unchanged
        r = _parse_proxy_url("proxy:8080")
        assert r == {"server": "proxy:8080"}

    def test_build_proxy_kwargs_bare(self):
        r = _build_proxy_kwargs("user:pass@proxy:8080")
        assert r["proxy"]["username"] == "user"
        assert r["proxy"]["password"] == "pass"
        assert "user" not in r["proxy"]["server"]
