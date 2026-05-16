"""Unit tests for cloakserve — parse_connection_params, parse_cli_args, URL rewriting, connection tracking."""

import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

aiohttp = pytest.importorskip("aiohttp", reason="cloakserve requires aiohttp (install with .[serve])")

# Load cloakserve as a module from bin/ (no .py extension).
_bin_path = str(Path(__file__).resolve().parents[1] / "bin" / "cloakserve")
_loader = importlib.machinery.SourceFileLoader("cloakserve", _bin_path)
_spec = importlib.util.spec_from_file_location("cloakserve", _bin_path, loader=_loader)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["cloakserve"] = _mod
_loader.exec_module(_mod)

parse_connection_params = _mod.parse_connection_params
parse_cli_args = _mod.parse_cli_args
ChromePool = _mod.ChromePool
_default_data_dir = _mod._default_data_dir
SAFE_SEED_RE = _mod.SAFE_SEED_RE
RESERVED_SEEDS = _mod.RESERVED_SEEDS


# ---------------------------------------------------------------------------
# parse_connection_params
# ---------------------------------------------------------------------------


class TestParseConnectionParams:
    def test_empty_query(self):
        result = parse_connection_params("")
        assert result["seed"] is None
        assert result["extra_args"] == []

    def test_fingerprint_seed(self):
        result = parse_connection_params("fingerprint=12345")
        assert result["seed"] == "12345"

    def test_timezone_and_locale(self):
        result = parse_connection_params("fingerprint=1&timezone=Asia/Tokyo&locale=ja-JP")
        assert result["timezone"] == "Asia/Tokyo"
        assert result["locale"] == "ja-JP"

    def test_proxy(self):
        result = parse_connection_params("proxy=http://proxy:8080")
        assert result["proxy"] == "http://proxy:8080"

    def test_geoip_true_variants(self):
        for val in ("true", "1", "yes", "True", "YES"):
            result = parse_connection_params(f"geoip={val}")
            assert result["geoip"] is True, f"geoip={val} should be True"

    def test_geoip_false(self):
        for val in ("false", "0", "no", "anything"):
            result = parse_connection_params(f"geoip={val}")
            assert result["geoip"] is False, f"geoip={val} should be False"

    def test_generic_fingerprint_params(self):
        qs = "fingerprint=1&platform=windows&hardware-concurrency=8&gpu-vendor=NVIDIA"
        result = parse_connection_params(qs)
        assert "--fingerprint-platform=windows" in result["extra_args"]
        assert "--fingerprint-hardware-concurrency=8" in result["extra_args"]
        assert "--fingerprint-gpu-vendor=NVIDIA" in result["extra_args"]

    def test_special_params_not_in_extra_args(self):
        qs = "fingerprint=1&timezone=UTC&locale=en-US&proxy=http://x:1&geoip=true"
        result = parse_connection_params(qs)
        assert result["extra_args"] == []

    def test_multiple_values_takes_first(self):
        result = parse_connection_params("fingerprint=111&fingerprint=222")
        assert result["seed"] == "111"

    def test_token_query_param_is_not_forwarded_to_chrome(self):
        """``token`` is the auth-flow secret (#217); it must NEVER fall through
        to the generic ``--fingerprint-{key}={val}`` branch, or the secret
        would leak to Chrome's argv (visible in ``ps``) and emit an
        unsupported flag."""
        qs = "fingerprint=1&token=super-secret-token-value"
        result = parse_connection_params(qs)
        for arg in result["extra_args"]:
            assert "token" not in arg.lower(), (
                f"token query param leaked into Chrome args: {arg!r}"
            )
        assert "--fingerprint-token=super-secret-token-value" not in result["extra_args"]
        # Sanity: the non-token fingerprint setup is otherwise untouched.
        assert result["seed"] == "1"

    def test_token_query_param_alone_is_silently_consumed(self):
        """A bare ``?token=`` (no other params) yields a clean parse — no
        leaked args and no error."""
        result = parse_connection_params("token=abc")
        assert result["seed"] is None
        assert result["extra_args"] == []


# ---------------------------------------------------------------------------
# parse_cli_args
# ---------------------------------------------------------------------------


class TestParseCliArgs:
    def test_defaults(self):
        config, passthrough = parse_cli_args([])
        assert config["port"] == 9222
        assert config["headless"] is True
        assert config["data_dir"] is not None
        assert passthrough == []

    def test_custom_port(self):
        config, _ = parse_cli_args(["--port=8080"])
        assert config["port"] == 8080

    def test_headless_false(self):
        config, passthrough = parse_cli_args(["--headless=false"])
        assert config["headless"] is False
        # headless flag still passed through to Chrome
        assert "--headless=false" in passthrough

    def test_strips_remote_debugging_flags(self):
        args = ["--remote-debugging-port=9999", "--remote-debugging-address=0.0.0.0", "--no-sandbox"]
        config, passthrough = parse_cli_args(args)
        assert passthrough == ["--no-sandbox"]

    def test_passthrough_args(self):
        args = ["--no-sandbox", "--disable-gpu", "--fingerprint=999"]
        config, passthrough = parse_cli_args(args)
        # --fingerprint=999 is consumed into config["default_seed"], not passed through
        assert passthrough == ["--no-sandbox", "--disable-gpu"]
        assert config["default_seed"] == "999"

    def test_port_not_in_passthrough(self):
        _, passthrough = parse_cli_args(["--port=9222", "--no-sandbox"])
        assert "--port=9222" not in passthrough
        assert "--no-sandbox" in passthrough

    def test_custom_data_dir(self):
        config, passthrough = parse_cli_args(["--data-dir=/custom/path", "--no-sandbox"])
        assert config["data_dir"] == "/custom/path"
        assert "--data-dir=/custom/path" not in passthrough

    def test_data_dir_not_in_passthrough(self):
        _, passthrough = parse_cli_args(["--data-dir=/tmp/test"])
        assert not any(a.startswith("--data-dir=") for a in passthrough)

    @patch("os.path.exists", return_value=True)
    def test_default_data_dir_docker(self, _mock):
        assert _default_data_dir() == "/tmp/cloakserve"

    @patch("os.path.exists", return_value=False)
    def test_default_data_dir_bare_metal(self, _mock):
        result = _default_data_dir()
        assert result.endswith(".cloakbrowser/cloakserve")


# ---------------------------------------------------------------------------
# URL rewriting logic (pure string manipulation, extracted from handlers)
# ---------------------------------------------------------------------------


class TestURLRewriting:
    """Test the URL rewriting logic used by /json/version and /json/list."""

    def _rewrite_version(self, orig_ws: str, host: str, seed: str | None, scheme: str = "ws") -> str:
        """Replicate the URL rewrite logic from handle_json_version."""
        if seed:
            ws_path = f"fingerprint/{seed}/devtools/browser"
        else:
            ws_path = "devtools/browser"
        guid = orig_ws.rsplit("/", 1)[-1] if "/devtools/" in orig_ws else ""
        return f"{scheme}://{host}/{ws_path}/{guid}"

    def _rewrite_list_entry(self, orig_ws: str, host: str, seed: str | None, scheme: str = "ws") -> str:
        """Replicate the URL rewrite logic from handle_json_list."""
        ws_tail = orig_ws.split("/devtools/")[-1]
        if seed:
            return f"{scheme}://{host}/fingerprint/{seed}/devtools/{ws_tail}"
        else:
            return f"{scheme}://{host}/devtools/{ws_tail}"

    def test_version_rewrite_with_seed(self):
        orig = "ws://127.0.0.1:5100/devtools/browser/abc-123"
        result = self._rewrite_version(orig, "container:9222", "12345")
        assert result == "ws://container:9222/fingerprint/12345/devtools/browser/abc-123"

    def test_version_rewrite_no_seed(self):
        orig = "ws://127.0.0.1:5100/devtools/browser/abc-123"
        result = self._rewrite_version(orig, "container:9222", None)
        assert result == "ws://container:9222/devtools/browser/abc-123"

    def test_list_rewrite_page_with_seed(self):
        orig = "ws://127.0.0.1:5100/devtools/page/DEF-456"
        result = self._rewrite_list_entry(orig, "host:9222", "99")
        assert result == "ws://host:9222/fingerprint/99/devtools/page/DEF-456"

    def test_list_rewrite_page_no_seed(self):
        orig = "ws://127.0.0.1:5100/devtools/page/DEF-456"
        result = self._rewrite_list_entry(orig, "host:9222", None)
        assert result == "ws://host:9222/devtools/page/DEF-456"

    def test_list_rewrite_browser(self):
        orig = "ws://127.0.0.1:5100/devtools/browser/XYZ"
        result = self._rewrite_list_entry(orig, "host:9222", "seed1")
        assert result == "ws://host:9222/fingerprint/seed1/devtools/browser/XYZ"

    def test_wss_scheme_version(self):
        orig = "ws://127.0.0.1:5100/devtools/browser/abc-123"
        result = self._rewrite_version(orig, "host:443", "seed1", scheme="wss")
        assert result == "wss://host:443/fingerprint/seed1/devtools/browser/abc-123"

    def test_wss_scheme_list(self):
        orig = "ws://127.0.0.1:5100/devtools/page/DEF-456"
        result = self._rewrite_list_entry(orig, "host:443", "seed1", scheme="wss")
        assert result == "wss://host:443/fingerprint/seed1/devtools/page/DEF-456"


# ---------------------------------------------------------------------------
# Connection refcounting
# ---------------------------------------------------------------------------


class TestConnectionTracking:
    """Test ChromePool.connect() / disconnect() without real Chrome."""

    def _make_pool(self):
        return ChromePool(
            binary="/fake/chrome",
            global_args=[],
            headless=True,
            data_dir="/tmp/test-cloakserve",
        )

    def test_connect_increments(self):
        pool = self._make_pool()
        pool.connect("seed1")
        assert pool._connections["seed1"] == 1
        pool.connect("seed1")
        assert pool._connections["seed1"] == 2

    def test_disconnect_decrements(self):
        pool = self._make_pool()
        pool.connect("seed1")
        pool.connect("seed1")
        pool.disconnect("seed1")
        assert pool._connections["seed1"] == 1

    def test_disconnect_to_zero_removes_key(self):
        pool = self._make_pool()
        pool.connect("seed1")
        pool.disconnect("seed1")
        assert "seed1" not in pool._connections

    def test_disconnect_below_zero_safe(self):
        pool = self._make_pool()
        pool.disconnect("nonexistent")
        assert "nonexistent" not in pool._connections

    def test_multiple_seeds_independent(self):
        pool = self._make_pool()
        pool.connect("a")
        pool.connect("b")
        pool.connect("a")
        pool.disconnect("a")
        assert pool._connections["a"] == 1
        assert pool._connections["b"] == 1


# ---------------------------------------------------------------------------
# Seed validation (CVE fix — path traversal via fingerprint param)
# ---------------------------------------------------------------------------


class TestSeedValidation:
    """Verify SAFE_SEED_RE rejects path traversal and reserved names."""

    @pytest.mark.parametrize("seed", [
        "../foo", "../../etc", "/etc/passwd", "..", ".", "foo/bar",
        "foo\\bar", "\x00evil", "", "a" * 129,
    ])
    def test_malicious_seeds_rejected(self, seed):
        assert not SAFE_SEED_RE.match(seed)

    @pytest.mark.parametrize("seed", [
        "__default__",
    ])
    def test_reserved_seeds_rejected(self, seed):
        assert seed in RESERVED_SEEDS

    @pytest.mark.parametrize("seed", [
        "12345", "my-seed_01", "ABC", "a" * 128, "0", "test-seed",
    ])
    def test_valid_seeds_accepted(self, seed):
        assert SAFE_SEED_RE.match(seed)
        assert seed not in RESERVED_SEEDS


# ---------------------------------------------------------------------------
# Path containment (_safe_rmtree)
# ---------------------------------------------------------------------------


class TestSafeRmtree:
    """Verify _safe_rmtree refuses to delete outside data_dir."""

    def _make_pool(self, data_dir: str):
        return ChromePool(
            binary="/fake/chrome",
            global_args=[],
            headless=True,
            data_dir=data_dir,
        )

    def test_refuses_path_outside_data_dir(self, tmp_path):
        data_dir = tmp_path / "profiles"
        data_dir.mkdir()
        victim = tmp_path / "victim"
        victim.mkdir()
        (victim / "sentinel").touch()

        pool = self._make_pool(str(data_dir))
        pool._safe_rmtree(str(victim))

        assert victim.exists(), "Directory outside data_dir must not be deleted"

    def test_refuses_data_dir_itself(self, tmp_path):
        data_dir = tmp_path / "profiles"
        data_dir.mkdir()
        (data_dir / "sentinel").touch()

        pool = self._make_pool(str(data_dir))
        pool._safe_rmtree(str(data_dir))

        assert data_dir.exists(), "data_dir itself must not be deleted"

    def test_deletes_valid_subdirectory(self, tmp_path):
        data_dir = tmp_path / "profiles"
        data_dir.mkdir()
        subdir = data_dir / "seed-12345"
        subdir.mkdir()
        (subdir / "data").touch()

        pool = self._make_pool(str(data_dir))
        pool._safe_rmtree(str(subdir))

        assert not subdir.exists(), "Valid subdirectory should be deleted"

    def test_refuses_traversal_path(self, tmp_path):
        data_dir = tmp_path / "profiles"
        data_dir.mkdir()
        victim = tmp_path / "victim"
        victim.mkdir()

        traversal = str(data_dir / ".." / "victim")
        pool = self._make_pool(str(data_dir))
        pool._safe_rmtree(traversal)

        assert victim.exists(), "Traversal path must not be deleted"


# ---------------------------------------------------------------------------
# CLI: --host and --auth-token (#217)
# ---------------------------------------------------------------------------


class TestHostAndAuthCli:
    def test_host_defaults_to_none(self):
        config, _ = parse_cli_args([])
        assert config["host"] is None

    def test_custom_host(self):
        config, passthrough = parse_cli_args(["--host=127.0.0.1"])
        assert config["host"] == "127.0.0.1"
        assert "--host=127.0.0.1" not in passthrough

    def test_auth_token_defaults_to_none(self):
        config, _ = parse_cli_args([])
        assert config["auth_token"] is None

    def test_auth_token_from_cli(self):
        config, passthrough = parse_cli_args(["--auth-token=s3cret"])
        assert config["auth_token"] == "s3cret"
        assert "--auth-token=s3cret" not in passthrough

    def test_auth_token_from_env(self, monkeypatch):
        monkeypatch.setenv("CLOAKSERVE_AUTH_TOKEN", "envsecret")
        config, _ = parse_cli_args([])
        assert config["auth_token"] == "envsecret"

    def test_cli_token_beats_env_token(self, monkeypatch):
        monkeypatch.setenv("CLOAKSERVE_AUTH_TOKEN", "envsecret")
        config, _ = parse_cli_args(["--auth-token=clisecret"])
        assert config["auth_token"] == "clisecret"


# ---------------------------------------------------------------------------
# auth_middleware (#217)
# ---------------------------------------------------------------------------


class TestAuthMiddleware:
    """Verify the shared-secret middleware behaves correctly.

    Each test wires the middleware into a minimal aiohttp app and uses
    aiohttp_client (pytest-aiohttp not required — we use the loop fixture).
    """

    def _build_app(self, token: str | None):
        from aiohttp import web
        app = web.Application(middlewares=[_mod.auth_middleware])
        app["auth_token"] = token

        async def root(_request):
            return web.json_response({"ok": True})

        async def json_version(_request):
            return web.json_response({"Browser": "test"})

        async def devtools(_request):
            return web.json_response({"path": "ok"})

        app.router.add_get("/", root)
        app.router.add_get("/json/version", json_version)
        app.router.add_get("/devtools/browser/abc", devtools)
        app.router.add_get("/fingerprint/abc/devtools/browser/xyz", devtools)
        return app

    async def _get_status_and_body(self, app, path, *, headers=None, params=None):
        from aiohttp.test_utils import TestServer, TestClient
        async with TestServer(app) as server:
            async with TestClient(server) as client:
                async with client.get(
                    path, headers=headers or {}, params=params or {},
                ) as resp:
                    body = None
                    try:
                        body = await resp.json()
                    except Exception:
                        pass
                    return resp.status, body

    @pytest.mark.asyncio
    async def test_no_token_configured_allows_all_routes(self):
        app = self._build_app(token=None)
        for path in ["/", "/json/version", "/devtools/browser/abc"]:
            status, _ = await self._get_status_and_body(app, path)
            assert status == 200, f"{path} should be open when no token set"

    @pytest.mark.asyncio
    async def test_root_status_route_always_open(self):
        app = self._build_app(token="s3cret")
        status, _ = await self._get_status_and_body(app, "/")
        assert status == 200, "/ must stay reachable for health checks"

    @pytest.mark.asyncio
    async def test_json_route_rejects_missing_token(self):
        app = self._build_app(token="s3cret")
        status, body = await self._get_status_and_body(app, "/json/version")
        assert status == 401
        assert body and "Authentication required" in body.get("error", "")

    @pytest.mark.asyncio
    async def test_json_route_rejects_wrong_token(self):
        app = self._build_app(token="s3cret")
        status, _ = await self._get_status_and_body(
            app, "/json/version",
            headers={"Authorization": "Bearer wrong"},
        )
        assert status == 401

    @pytest.mark.asyncio
    async def test_json_route_accepts_correct_bearer(self):
        app = self._build_app(token="s3cret")
        status, _ = await self._get_status_and_body(
            app, "/json/version",
            headers={"Authorization": "Bearer s3cret"},
        )
        assert status == 200

    @pytest.mark.asyncio
    async def test_json_route_accepts_correct_query_param(self):
        app = self._build_app(token="s3cret")
        status, _ = await self._get_status_and_body(
            app, "/json/version", params={"token": "s3cret"},
        )
        assert status == 200

    @pytest.mark.asyncio
    async def test_devtools_ws_path_protected(self):
        app = self._build_app(token="s3cret")
        status, _ = await self._get_status_and_body(app, "/devtools/browser/abc")
        assert status == 401

    @pytest.mark.asyncio
    async def test_fingerprint_ws_path_protected(self):
        app = self._build_app(token="s3cret")
        status, _ = await self._get_status_and_body(
            app, "/fingerprint/abc/devtools/browser/xyz",
        )
        assert status == 401


# ---------------------------------------------------------------------------
# webSocketDebuggerUrl token propagation (#217 review follow-up)
# ---------------------------------------------------------------------------


class TestAppendTokenQuery:
    """Unit tests for the ``_append_token_query`` helper that propagates the
    auth token onto rewritten WebSocket URLs.  Without this, a client that
    authenticates ``/json/version`` via ``?token=`` gets back a
    ``ws://.../devtools/...`` URL with no token, and the WS handshake
    immediately fails with 401 — which breaks the Playwright
    ``connect_over_cdp(URL_STRING)`` use case the PR advertises."""

    def test_returns_url_unchanged_when_no_token(self):
        url = "ws://host:9222/devtools/browser/abc"
        assert _mod._append_token_query(url, None) == url
        assert _mod._append_token_query(url, "") == url

    def test_appends_token_when_no_existing_query(self):
        out = _mod._append_token_query(
            "ws://host:9222/devtools/browser/abc", "s3cret",
        )
        assert out == "ws://host:9222/devtools/browser/abc?token=s3cret"

    def test_appends_with_ampersand_when_query_exists(self):
        out = _mod._append_token_query(
            "ws://host:9222/devtools/browser/abc?keepme=1", "s3cret",
        )
        assert out == "ws://host:9222/devtools/browser/abc?keepme=1&token=s3cret"

    def test_token_is_url_encoded(self):
        out = _mod._append_token_query(
            "ws://host:9222/devtools/browser/abc",
            "token with spaces & special=chars",
        )
        # `quote(..., safe='')` encodes spaces, ampersands, equals.
        assert "token=token%20with%20spaces%20%26%20special%3Dchars" in out

    def test_fingerprint_ws_url_gets_token_too(self):
        """The /fingerprint/<seed>/devtools/... rewrite branch must also
        propagate — same client compat concern."""
        out = _mod._append_token_query(
            "ws://host:9222/fingerprint/abc/devtools/browser/xyz", "s3cret",
        )
        assert out.endswith("?token=s3cret")


class TestHandleJsonVersionTokenPropagation:
    """End-to-end test that exercises ``handle_json_version`` against a
    stubbed Chrome upstream, asserting the rewritten ``webSocketDebuggerUrl``
    carries ``?token=`` when ``auth_token`` is configured on the app.

    This is the regression coverage requested in review of #217 — without
    the propagation the rewritten URL would be unauthenticated and the
    Playwright ``connect_over_cdp(URL_STRING)`` flow would 401 on the WS
    handshake immediately after a successful ``/json/version`` probe.
    """

    class _StubProc:
        def __init__(self, port: int):
            self.cdp_port = port

    class _StubPool:
        def __init__(self, port: int):
            self._port = port

        async def get_or_launch(self, **_kwargs):
            return TestHandleJsonVersionTokenPropagation._StubProc(self._port)

    async def _serve_chrome_upstream(self, payload: dict):
        """Spin up a minimal aiohttp server that returns ``payload`` from
        ``/json/version``.  Returns ``(host, port, server, runner)`` and the
        caller is responsible for ``await runner.cleanup()``."""
        from aiohttp import web
        app = web.Application()

        async def _v(_request):
            return web.json_response(payload)

        app.router.add_get("/json/version", _v)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        sock = site._server.sockets[0]
        port = sock.getsockname()[1]
        return "127.0.0.1", port, runner

    @pytest.mark.asyncio
    async def test_json_version_propagates_token_to_ws_url(self):
        from aiohttp import web
        from aiohttp.test_utils import TestServer, TestClient

        upstream_payload = {
            "Browser": "Chrome/120",
            "webSocketDebuggerUrl": "ws://127.0.0.1:5100/devtools/browser/abc-guid",
        }
        _host, port, runner = await self._serve_chrome_upstream(upstream_payload)
        try:
            app = web.Application(middlewares=[_mod.auth_middleware])
            app["pool"] = self._StubPool(port)
            app["port"] = 9222
            app["auth_token"] = "rev-secret"
            app.router.add_get("/json/version", _mod.handle_json_version)

            async with TestServer(app) as server:
                async with TestClient(server) as client:
                    # Authenticate via ?token= (the URL-string compat flow).
                    async with client.get(
                        "/json/version", params={"token": "rev-secret"},
                    ) as resp:
                        assert resp.status == 200
                        data = await resp.json()

            ws = data.get("webSocketDebuggerUrl", "")
            assert "/devtools/browser/abc-guid" in ws, (
                f"WS URL not rewritten correctly: {ws!r}"
            )
            assert "token=rev-secret" in ws, (
                f"WS URL missing ?token=: {ws!r} (breaks connect_over_cdp URL flow)"
            )
        finally:
            await runner.cleanup()

    @pytest.mark.asyncio
    async def test_json_version_no_token_when_auth_unconfigured(self):
        """Without ``auth_token`` set, the rewritten URL stays clean — we
        don't add a bogus ``?token=`` query param."""
        from aiohttp import web
        from aiohttp.test_utils import TestServer, TestClient

        upstream_payload = {
            "Browser": "Chrome/120",
            "webSocketDebuggerUrl": "ws://127.0.0.1:5100/devtools/browser/abc-guid",
        }
        _host, port, runner = await self._serve_chrome_upstream(upstream_payload)
        try:
            app = web.Application(middlewares=[_mod.auth_middleware])
            app["pool"] = self._StubPool(port)
            app["port"] = 9222
            app["auth_token"] = None
            app.router.add_get("/json/version", _mod.handle_json_version)

            async with TestServer(app) as server:
                async with TestClient(server) as client:
                    async with client.get("/json/version") as resp:
                        assert resp.status == 200
                        data = await resp.json()

            ws = data.get("webSocketDebuggerUrl", "")
            assert "?token=" not in ws
            assert "&token=" not in ws
        finally:
            await runner.cleanup()
