"""Unit tests for cloakserve — parse_connection_params, parse_cli_args, URL rewriting, connection tracking."""

import asyncio
import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
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
_external_host = _mod._external_host
_ws_scheme = _mod._ws_scheme
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


# ---------------------------------------------------------------------------
# parse_cli_args
# ---------------------------------------------------------------------------


class TestParseCliArgs:
    def test_defaults(self):
        config, passthrough = parse_cli_args([])
        assert config["port"] == 9222
        assert config["headless"] is True
        assert config["data_dir"] is not None
        assert config["idle_timeout"] == 0.0
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

    def test_idle_timeout_not_in_passthrough(self):
        config, passthrough = parse_cli_args(["--idle-timeout=30", "--no-sandbox"])
        assert config["idle_timeout"] == 30.0
        assert "--idle-timeout=30" not in passthrough
        assert "--no-sandbox" in passthrough

    @pytest.mark.parametrize("value", ["0", "off", "false", "none", "disabled"])
    def test_idle_timeout_disabled_values(self, value):
        config, _ = parse_cli_args([f"--idle-timeout={value}"])
        assert config["idle_timeout"] == 0.0

    def test_idle_timeout_env_default(self, monkeypatch):
        monkeypatch.setenv("CLOAKSERVE_IDLE_TIMEOUT", "2.5")
        config, _ = parse_cli_args([])
        assert config["idle_timeout"] == 2.5

    def test_idle_timeout_cli_overrides_env(self, monkeypatch):
        monkeypatch.setenv("CLOAKSERVE_IDLE_TIMEOUT", "2.5")
        config, _ = parse_cli_args(["--idle-timeout=9"])
        assert config["idle_timeout"] == 9.0

    def test_idle_timeout_rejects_negative_values(self):
        with pytest.raises(ValueError):
            parse_cli_args(["--idle-timeout=-1"])

    @patch("os.path.exists", return_value=True)
    def test_default_data_dir_docker(self, _mock):
        assert _default_data_dir() == "/tmp/cloakserve"

    @patch("os.path.exists", return_value=False)
    def test_default_data_dir_bare_metal(self, _mock):
        result = _default_data_dir()
        assert result.endswith(".cloakbrowser/cloakserve")


# ---------------------------------------------------------------------------
# External host detection
# ---------------------------------------------------------------------------


class TestExternalHost:
    """Test public host selection for rewritten CDP WebSocket URLs."""

    class _Request:
        def __init__(self, headers, port=9222, scheme="http", query_string=""):
            self.headers = headers
            self.app = {"port": port}
            self.scheme = scheme
            self.query_string = query_string

    def test_forwarded_host_overrides_internal_host(self):
        request = self._Request({
            "Host": "localhost:8080",
            "X-Forwarded-Host": "cdp.example.com:443",
        })
        assert _external_host(request) == "cdp.example.com:443"

    def test_forwarded_host_uses_first_value(self):
        request = self._Request({
            "Host": "internal:9222",
            "X-Forwarded-Host": "public.example.com, internal:9222",
        })
        assert _external_host(request) == "public.example.com"

    def test_blank_forwarded_host_falls_back_to_host_header(self):
        request = self._Request({
            "Host": "internal:9222",
            "X-Forwarded-Host": "   ",
        })
        assert _external_host(request) == "internal:9222"

    def test_falls_back_to_host_header(self):
        request = self._Request({"Host": "localhost:9222"})
        assert _external_host(request) == "localhost:9222"

    def test_falls_back_to_app_port_without_host_header(self):
        request = self._Request({}, port=9333)
        assert _external_host(request) == "localhost:9333"

    def test_forwarded_proto_selects_wss(self):
        request = self._Request({"X-Forwarded-Proto": "https"}, scheme="http")
        assert _ws_scheme(request) == "wss"

    def test_forwarded_proto_uses_first_value(self):
        request = self._Request({"X-Forwarded-Proto": "https, http"}, scheme="http")
        assert _ws_scheme(request) == "wss"


class TestHandlerURLRewriting:
    """Verify handlers rewrite CDP WebSocket URLs to the public cloakserve endpoint."""

    class _Request:
        def __init__(self, headers, query_string="fingerprint=seed1", port=9222, scheme="http"):
            self.headers = headers
            self.query_string = query_string
            self.scheme = scheme
            self.app = {"port": port, "pool": self._Pool()}

        class _Pool:
            async def get_or_launch(self, **_kwargs):
                return SimpleNamespace(cdp_port=5100)

    class _FakeResponse:
        def __init__(self, data):
            self._data = data

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def json(self):
            return self._data

    class _FakeSession:
        def __init__(self, data):
            self._data = data

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        def get(self, *_args, **_kwargs):
            return TestHandlerURLRewriting._FakeResponse(self._data)

    def _patch_session(self, monkeypatch, data):
        monkeypatch.setattr(
            _mod.aiohttp,
            "ClientSession",
            lambda *_args, **_kwargs: self._FakeSession(data),
        )

    def test_json_version_uses_forwarded_host_and_proto(self, monkeypatch):
        self._patch_session(monkeypatch, {
            "webSocketDebuggerUrl": "ws://127.0.0.1:5100/devtools/browser/browser-guid",
        })
        request = self._Request({
            "Host": "internal:9222",
            "X-Forwarded-Host": "cdp.example.com",
            "X-Forwarded-Proto": "https",
        })

        response = asyncio.run(_mod.handle_json_version(request))
        payload = json.loads(response.text)

        assert payload["webSocketDebuggerUrl"] == (
            "wss://cdp.example.com/fingerprint/seed1/devtools/browser/browser-guid"
        )

    def test_json_list_uses_forwarded_host_and_proto(self, monkeypatch):
        self._patch_session(monkeypatch, [{
            "webSocketDebuggerUrl": "ws://127.0.0.1:5100/devtools/page/page-guid",
        }])
        request = self._Request({
            "Host": "internal:9222",
            "X-Forwarded-Host": "cdp.example.com",
            "X-Forwarded-Proto": "https",
        })

        response = asyncio.run(_mod.handle_json_list(request))
        payload = json.loads(response.text)

        assert payload[0]["webSocketDebuggerUrl"] == (
            "wss://cdp.example.com/fingerprint/seed1/devtools/page/page-guid"
        )


# ---------------------------------------------------------------------------
# URL rewriting logic (pure string manipulation, extracted from handlers)
# ---------------------------------------------------------------------------


class TestWebSocketOriginGuard:
    """Verify cloakserve rejects browser-origin CDP WebSocket hijacks."""

    def test_absent_origin_allowed_for_non_browser_cdp_clients(self):
        assert _mod._origin_is_allowed(None, "127.0.0.1:9555")

    def test_matching_origin_host_allowed(self):
        assert _mod._origin_is_allowed("http://127.0.0.1:9555", "127.0.0.1:9555")

    def test_chrome_devtools_origin_allowed(self):
        assert _mod._origin_is_allowed("devtools://devtools", "127.0.0.1:9555")
        assert _mod._origin_is_allowed("chrome-devtools://devtools", "127.0.0.1:9555")

    @pytest.mark.parametrize("origin", [
        "http://attacker.example",
        "https://attacker.example",
        "http://PUBLIC_HOST:9555",
        "http://attacker.example:9555",
        "http://127.0.0.1:9555/",
        "http://127.0.0.1:9555/path",
        "http://127.0.0.1:9555?q=1",
        "http://127.0.0.1:9555#fragment",
        "http://user@127.0.0.1:9555",
        "http://@127.0.0.1:9555",
        "http://:@127.0.0.1:9555",
        "http://127.0.0.1:",
        "null",
        "file://",
    ])
    def test_untrusted_browser_origins_rejected(self, origin):
        assert not _mod._origin_is_allowed(origin, "127.0.0.1:9555")

    def test_public_origin_matching_host_is_still_rejected(self):
        assert not _mod._origin_is_allowed("http://attacker.example:9555", "attacker.example:9555")

    @pytest.mark.parametrize("host", [
        "user@127.0.0.1:9555",
        "127.0.0.1:9555/path",
        "127.0.0.1:9555?x=1",
        "127.0.0.1:9555#fragment",
        "127.0.0.1:9555, attacker.example:9555",
        "@127.0.0.1:9555",
        ":@127.0.0.1:9555",
        "127.0.0.1:",
        "[::1]:",
    ])
    def test_malformed_host_is_rejected_even_when_hostname_is_loopback(self, host):
        assert not _mod._origin_is_allowed("http://127.0.0.1:9555", host)

    def test_request_scheme_controls_host_default_port(self):
        assert _mod._origin_is_allowed("https://localhost", "localhost", request_scheme="https")
        assert not _mod._origin_is_allowed("https://localhost", "localhost", request_scheme="http")

    def test_ws_handler_rejects_untrusted_origin_before_launching_chrome(self):
        class RejectingPool:
            async def get_or_launch(self, **_kwargs):
                raise AssertionError("untrusted origin should be rejected before launching Chrome")

        request = SimpleNamespace(
            headers={"Host": "127.0.0.1:9555", "Origin": "http://attacker.example"},
            app={"pool": RejectingPool()},
            match_info={"path": "browser/browser-guid"},
        )

        response = asyncio.run(_mod.handle_ws_default(request))

        assert response.status == 403
        assert "untrusted" in response.text.lower()

    def test_seed_ws_handler_rejects_untrusted_origin_before_launching_chrome(self):
        class RejectingPool:
            async def get_or_launch(self, **_kwargs):
                raise AssertionError("untrusted origin should be rejected before launching Chrome")

        request = SimpleNamespace(
            headers={"Host": "127.0.0.1:9555", "Origin": "http://attacker.example"},
            app={"pool": RejectingPool()},
            match_info={"seed": "abc123", "path": "page/page-guid"},
        )

        response = asyncio.run(_mod.handle_ws_seed(request))

        assert response.status == 403
        assert "untrusted" in response.text.lower()


class TestHandlerURLRewriting:
    """Verify handlers rewrite CDP WebSocket URLs to the public cloakserve endpoint."""

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

    def _make_pool(self, idle_timeout: float = 0.0):
        return ChromePool(
            binary="/fake/chrome",
            global_args=[],
            headless=True,
            data_dir="/tmp/test-cloakserve",
            idle_timeout=idle_timeout,
        )

    def _track_process(self, pool, seed="seed1"):
        pool._processes[seed] = SimpleNamespace()

    def _track_live_process(self, pool, seed="seed1"):
        pool._processes[seed] = SimpleNamespace(
            process=SimpleNamespace(poll=lambda: None),
            cdp_port=5100,
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

    def test_idle_cleanup_disabled_by_default(self):
        async def run():
            pool = self._make_pool()
            self._track_process(pool)

            pool.connect("seed1")
            pool.disconnect("seed1")

            await asyncio.sleep(0)
            assert pool._idle_tasks == {}

        asyncio.run(run())

    def test_disconnect_to_zero_schedules_idle_cleanup(self):
        async def run():
            pool = self._make_pool(idle_timeout=0.01)
            self._track_process(pool)
            cleaned = []

            async def fake_cleanup(seed):
                cleaned.append(seed)
                pool._processes.pop(seed, None)

            pool._cleanup_process = fake_cleanup
            pool.connect("seed1")
            pool.disconnect("seed1")

            assert "seed1" in pool._idle_tasks
            await asyncio.sleep(0.05)
            assert cleaned == ["seed1"]
            assert "seed1" not in pool._idle_tasks

        asyncio.run(run())

    def test_reconnect_cancels_pending_idle_cleanup(self):
        async def run():
            pool = self._make_pool(idle_timeout=0.03)
            self._track_process(pool)
            cleaned = []

            async def fake_cleanup(seed):
                cleaned.append(seed)
                pool._processes.pop(seed, None)

            pool._cleanup_process = fake_cleanup
            pool.connect("seed1")
            pool.disconnect("seed1")
            assert "seed1" in pool._idle_tasks

            pool.connect("seed1")
            await asyncio.sleep(0.06)

            assert cleaned == []
            assert pool._connections["seed1"] == 1
            assert "seed1" not in pool._idle_tasks

        asyncio.run(run())

    def test_discovery_refreshes_pending_idle_cleanup(self):
        async def run():
            pool = self._make_pool(idle_timeout=1.0)
            self._track_live_process(pool)

            # The reuse fast-path now also probes the CDP port; the tracked
            # process is deliberately live, so keep the probe positive.
            async def _always_alive(_port):
                return True

            pool._cdp_port_alive = _always_alive

            pool.connect("seed1")
            pool.disconnect("seed1")
            first_task = pool._idle_tasks["seed1"]

            await pool.get_or_launch("seed1")
            second_task = pool._idle_tasks["seed1"]

            assert second_task is not first_task
            pool._cancel_idle_cleanup("seed1")
            await asyncio.sleep(0)
            assert "seed1" not in pool._idle_tasks

        asyncio.run(run())


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
# Dead-CDP-port corpse eviction
#
# process.poll() reports a Chrome alive until the OS reaps it, but Chrome drops
# its DevTools/CDP socket seconds before it exits (and a wedged Chrome keeps the
# process alive with a dead port indefinitely). Reusing such a corpse hands back
# a browser whose CDP port refuses connections, so the /json handlers used to
# 502 without evicting it — every retry hit the same corpse. The pool now probes
# the CDP port before reuse, and the handlers evict-and-retry once.
# ---------------------------------------------------------------------------


class TestCdpPortAlive:
    """_cdp_port_alive: a real local TCP probe, not a poll() guess."""

    def _make_pool(self):
        return ChromePool(
            binary="/fake/chrome",
            global_args=[],
            headless=True,
            data_dir="/tmp/test-cloakserve",
        )

    def test_true_for_a_listening_port(self):
        import socket as _socket

        async def run():
            listener = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            listener.setsockopt(_socket.SOL_SOCKET, _socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", 0))
            listener.listen(16)
            port = listener.getsockname()[1]
            try:
                assert await self._make_pool()._cdp_port_alive(port) is True
            finally:
                listener.close()

        asyncio.run(run())

    def test_false_for_a_closed_port(self):
        import socket as _socket

        async def run():
            # Bind then immediately release a port so nothing is listening on it.
            s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
            s.close()

            assert await self._make_pool()._cdp_port_alive(port, timeout=0.2) is False

        asyncio.run(run())


class TestPoolKeyForIdentity:
    """_pool_key_for matches by object identity, never by re-deriving the seed key."""

    def _make_pool(self):
        return ChromePool(
            binary="/fake/chrome",
            global_args=[],
            headless=True,
            data_dir="/tmp/test-cloakserve",
        )

    def test_returns_key_of_the_pooled_object(self):
        pool = self._make_pool()
        cp = SimpleNamespace(cdp_port=5100)
        pool._processes["seed1"] = cp
        assert pool._pool_key_for(cp) == "seed1"

    def test_returns_none_when_not_pooled(self):
        pool = self._make_pool()
        assert pool._pool_key_for(SimpleNamespace(cdp_port=5100)) is None

    def test_ignores_an_equal_but_distinct_process_under_the_same_key(self):
        # A concurrent relaunch on the same seed replaced the entry with a fresh
        # object; the corpse is no longer pooled, so identity lookup finds
        # nothing to evict — re-deriving "seed1" would have killed the fresh one.
        pool = self._make_pool()
        corpse = SimpleNamespace(cdp_port=5100)
        fresh = SimpleNamespace(cdp_port=5101)
        pool._processes["seed1"] = fresh
        assert pool._pool_key_for(corpse) is None
        assert pool._pool_key_for(fresh) == "seed1"


class TestGetOrLaunchReuseGuard:
    """get_or_launch reuses a pooled Chrome only when its CDP port is alive."""

    def _make_pool(self):
        return ChromePool(
            binary="/fake/chrome",
            global_args=[],
            headless=True,
            data_dir="/tmp/test-cloakserve",
        )

    def _stub_launch(self, pool, monkeypatch, cdp_port=6000):
        """Neuter the real Chrome launch so a relaunch is observable, not spawned."""
        state = {"launches": 0}

        def _popen(*_args, **_kwargs):
            state["launches"] += 1
            return SimpleNamespace(poll=lambda: None, pid=4321, kill=lambda: None)

        async def _wait_for_cdp(_port):
            return True

        monkeypatch.setattr(_mod.subprocess, "Popen", _popen)
        monkeypatch.setattr(_mod.os, "makedirs", lambda *a, **k: None)
        monkeypatch.setattr(_mod, "build_args", lambda **k: [])
        monkeypatch.setattr(_mod, "_resolve_webrtc_args", lambda fp_extra, proxy: fp_extra)
        monkeypatch.setattr(pool, "_allocate_port", lambda: cdp_port)
        monkeypatch.setattr(pool, "_wait_for_cdp", _wait_for_cdp)
        return state

    def test_poll_alive_but_dead_port_is_evicted_and_relaunched(self, monkeypatch):
        async def run():
            pool = self._make_pool()
            corpse = SimpleNamespace(
                process=SimpleNamespace(poll=lambda: None),
                cdp_port=5100,
                user_data_dir="/tmp/test-cloakserve/seed1",
            )
            pool._processes["seed1"] = corpse

            # poll() says alive, but the CDP port refuses connections.
            async def _dead(_port):
                return False

            monkeypatch.setattr(pool, "_cdp_port_alive", _dead)

            evicted = []

            async def _cleanup(key):
                evicted.append(key)
                pool._processes.pop(key, None)

            monkeypatch.setattr(pool, "_cleanup_process", _cleanup)
            launch = self._stub_launch(pool, monkeypatch, cdp_port=6000)

            cp = await pool.get_or_launch("seed1")

            assert evicted == ["seed1"], "the corpse must be evicted"
            assert cp is not corpse, "the corpse must not be reused"
            assert cp.cdp_port == 6000, "a fresh browser must be launched"
            assert launch["launches"] == 1
            assert pool._processes["seed1"] is cp

        asyncio.run(run())

    def test_poll_alive_and_port_alive_is_reused_after_exactly_one_probe(self, monkeypatch):
        async def run():
            pool = self._make_pool()
            live = SimpleNamespace(
                process=SimpleNamespace(poll=lambda: None),
                cdp_port=5100,
            )
            pool._processes["seed1"] = live

            probes = []

            async def _alive(port):
                probes.append(port)
                return True

            monkeypatch.setattr(pool, "_cdp_port_alive", _alive)

            def _no_launch(*_args, **_kwargs):
                raise AssertionError("a live browser must be reused, never relaunched")

            monkeypatch.setattr(_mod.subprocess, "Popen", _no_launch)

            cp = await pool.get_or_launch("seed1")

            assert cp is live, "the live browser must be reused"
            assert probes == [5100], "the CDP port must be probed exactly once"

        asyncio.run(run())


class TestHandlerCorpseRecovery:
    """handle_json_version / handle_json_list evict a dead corpse and retry once."""

    def _make_request(self, pool, query_string="fingerprint=seed1"):
        return SimpleNamespace(
            app={"pool": pool, "port": 9222},
            query_string=query_string,
            headers={"Host": "cdp.example.com:9222"},
            scheme="http",
        )

    class _FlakySession:
        """aiohttp.ClientSession stand-in: fails the first ``fail_times`` fetches."""

        def __init__(self, controller):
            self._c = controller

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        def get(self, *_args, **_kwargs):
            return TestHandlerCorpseRecovery._FlakyResponse(self._c)

    class _FlakyResponse:
        def __init__(self, controller):
            self._c = controller

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc):
            return None

        async def json(self):
            self._c["calls"] += 1
            if self._c["calls"] <= self._c["fail_times"]:
                raise ConnectionRefusedError("CDP port refused")
            return self._c["data"]

    def _patch_session(self, monkeypatch, controller):
        monkeypatch.setattr(
            _mod.aiohttp,
            "ClientSession",
            lambda *_a, **_k: self._FlakySession(controller),
        )

    class _RecoveringPool:
        """Hands back a fresh cp each launch; records evictions by identity."""

        def __init__(self):
            self.launches = 0
            self.evicted = []
            self._processes = {}

        async def get_or_launch(self, **_kwargs):
            self.launches += 1
            cp = SimpleNamespace(cdp_port=5100 + self.launches)
            self._processes["seed1"] = cp
            return cp

        def _pool_key_for(self, cp):
            for key, pooled in self._processes.items():
                if pooled is cp:
                    return key
            return None

        async def _cleanup_process(self, key):
            self.evicted.append(key)
            self._processes.pop(key, None)

    def test_json_version_recovers_from_a_dead_port_without_502(self, monkeypatch):
        pool = self._RecoveringPool()
        controller = {
            "calls": 0,
            "fail_times": 1,
            "data": {"webSocketDebuggerUrl": "ws://127.0.0.1:5100/devtools/browser/guid"},
        }
        self._patch_session(monkeypatch, controller)

        response = asyncio.run(_mod.handle_json_version(self._make_request(pool)))
        payload = json.loads(response.text)

        assert response.status == 200
        assert pool.evicted == ["seed1"], "the dead corpse is evicted exactly once"
        assert pool.launches == 2, "a fresh browser is launched for the retry"
        assert payload["webSocketDebuggerUrl"] == (
            "ws://cdp.example.com:9222/fingerprint/seed1/devtools/browser/guid"
        )

    def test_json_version_returns_502_only_after_both_attempts_fail(self, monkeypatch):
        pool = self._RecoveringPool()
        controller = {"calls": 0, "fail_times": 2, "data": {}}
        self._patch_session(monkeypatch, controller)

        response = asyncio.run(_mod.handle_json_version(self._make_request(pool)))

        assert response.status == 502
        assert json.loads(response.text) == {"error": "CDP endpoint unreachable"}
        assert pool.evicted == ["seed1"], "eviction is attempted once, on the first failure"
        assert pool.launches == 2, "both attempts run before giving up"

    def test_json_list_recovers_from_a_dead_port_without_502(self, monkeypatch):
        pool = self._RecoveringPool()
        controller = {
            "calls": 0,
            "fail_times": 1,
            "data": [{"webSocketDebuggerUrl": "ws://127.0.0.1:5100/devtools/page/guid"}],
        }
        self._patch_session(monkeypatch, controller)

        response = asyncio.run(_mod.handle_json_list(self._make_request(pool)))
        payload = json.loads(response.text)

        assert response.status == 200
        assert pool.evicted == ["seed1"]
        assert pool.launches == 2
        assert payload[0]["webSocketDebuggerUrl"] == (
            "ws://cdp.example.com:9222/fingerprint/seed1/devtools/page/guid"
        )

    def test_eviction_by_identity_spares_a_concurrently_relaunched_process(self, monkeypatch):
        # get_or_launch hands back a corpse on attempt 0, but by the time the
        # handler goes to evict, a concurrent same-seed relaunch has already put
        # a fresh process in the pool under "seed1". Identity-based lookup must
        # find nothing to evict, so the fresh process survives and is reused.
        corpse = SimpleNamespace(cdp_port=5100)
        fresh = SimpleNamespace(cdp_port=5101)

        class _RacePool:
            def __init__(self):
                self.launches = 0
                self.evicted = []
                # the concurrent relaunch already swapped the entry
                self._processes = {"seed1": fresh}

            async def get_or_launch(self, **_kwargs):
                self.launches += 1
                return corpse if self.launches == 1 else fresh

            def _pool_key_for(self, cp):
                for key, pooled in self._processes.items():
                    if pooled is cp:
                        return key
                return None

            async def _cleanup_process(self, key):
                self.evicted.append(key)
                self._processes.pop(key, None)

        pool = _RacePool()
        controller = {
            "calls": 0,
            "fail_times": 1,  # the corpse fetch fails, the fresh fetch succeeds
            "data": {"webSocketDebuggerUrl": "ws://127.0.0.1:5101/devtools/browser/guid"},
        }
        self._patch_session(monkeypatch, controller)

        response = asyncio.run(_mod.handle_json_version(self._make_request(pool)))

        assert response.status == 200
        assert pool.evicted == [], "the concurrently-relaunched process must not be evicted"
        assert pool._processes["seed1"] is fresh, "the fresh process survives"
