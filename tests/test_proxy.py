"""Tests for proxy URL parsing and credential extraction."""

from cloakbrowser.browser import _build_proxy_kwargs, _parse_proxy_url


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
