"""Tests for the CloakBrowser Pro license module."""

import hashlib
import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cloakbrowser.download import BinaryVerificationError, ensure_binary
from cloakbrowser.license import (
    LicenseInfo,
    build_launch_env,
    get_active_session_count,
    get_pro_latest_version,
    resolve_license_key,
    validate_license,
)


# ── resolve_license_key ───────────────────────────────


class TestResolveLicenseKey:
    def test_explicit_param_wins(self):
        with patch.dict(os.environ, {"CLOAKBROWSER_LICENSE_KEY": "env-key"}):
            assert resolve_license_key("explicit") == "explicit"

    def test_env_var_fallback(self):
        with patch.dict(os.environ, {"CLOAKBROWSER_LICENSE_KEY": "env-key"}):
            assert resolve_license_key() == "env-key"

    def test_returns_none_when_absent(self):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CLOAKBROWSER_LICENSE_KEY", None)
            assert resolve_license_key() is None

    def test_empty_string_param_uses_env(self):
        with patch.dict(os.environ, {"CLOAKBROWSER_LICENSE_KEY": "env-key"}):
            assert resolve_license_key("") == "env-key"

    def test_file_fallback(self, tmp_path):
        key_file = tmp_path / "license.key"
        key_file.write_text("file-key-123\n")
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CLOAKBROWSER_LICENSE_KEY", None)
            with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
                assert resolve_license_key() == "file-key-123"

    def test_env_takes_precedence_over_file(self, tmp_path):
        key_file = tmp_path / "license.key"
        key_file.write_text("file-key")
        with patch.dict(os.environ, {"CLOAKBROWSER_LICENSE_KEY": "env-key"}):
            with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
                assert resolve_license_key() == "env-key"

    def test_no_file_returns_none(self, tmp_path):
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CLOAKBROWSER_LICENSE_KEY", None)
            with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
                assert resolve_license_key() is None


# ── validate_license ──────────────────────────────────


class TestValidateLicense:
    def test_fresh_cache_skips_server(self, tmp_path):
        cache_path = tmp_path / ".license_cache"
        key_sha = hashlib.sha256(b"test-key").hexdigest()
        cache_path.write_text(json.dumps({
            "key_sha256": key_sha,
            "valid": True,
            "plan": "team",
            "expires": "2026-12-01",
            "validated_at": time.time(),
        }))

        with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
            with patch("cloakbrowser.license.httpx.post") as mock_post:
                result = validate_license("test-key")

        mock_post.assert_not_called()
        assert result is not None
        assert result.valid is True
        assert result.plan == "team"

    def test_stale_cache_calls_server(self, tmp_path):
        cache_path = tmp_path / ".license_cache"
        key_sha = hashlib.sha256(b"test-key").hexdigest()
        cache_path.write_text(json.dumps({
            "key_sha256": key_sha,
            "valid": True,
            "plan": "solo",
            "expires": None,
            "validated_at": time.time() - 90000,  # 25 hours ago
        }))

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"valid": True, "plan": "solo", "expires": None}
        mock_resp.raise_for_status = MagicMock()

        with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
            with patch("cloakbrowser.license.httpx.post", return_value=mock_resp) as mock_post:
                result = validate_license("test-key")

        mock_post.assert_called_once()
        assert result is not None
        assert result.valid is True

    def test_server_success(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"valid": True, "plan": "business", "expires": "2026-07-13"}
        mock_resp.raise_for_status = MagicMock()

        with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
            with patch("cloakbrowser.license.httpx.post", return_value=mock_resp):
                result = validate_license("pro-key")

        assert result is not None
        assert result.valid is True
        assert result.plan == "business"
        assert result.expires == "2026-07-13"

    def test_server_rejection(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"valid": False, "plan": "solo", "expires": None}
        mock_resp.raise_for_status = MagicMock()

        with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
            with patch("cloakbrowser.license.httpx.post", return_value=mock_resp):
                result = validate_license("bad-key")

        assert result is not None
        assert result.valid is False

    def test_server_unreachable_uses_stale_cache(self, tmp_path):
        cache_path = tmp_path / ".license_cache"
        key_sha = hashlib.sha256(b"test-key").hexdigest()
        cache_path.write_text(json.dumps({
            "key_sha256": key_sha,
            "valid": True,
            "plan": "solo",
            "expires": "2026-12-01",
            "validated_at": time.time() - 90000,
        }))

        with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
            with patch("cloakbrowser.license.httpx.post", side_effect=Exception("timeout")):
                result = validate_license("test-key")

        assert result is not None
        assert result.valid is True

    def test_server_unreachable_no_cache_returns_none(self, tmp_path):
        with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
            with patch("cloakbrowser.license.httpx.post", side_effect=Exception("timeout")):
                result = validate_license("test-key")

        assert result is None

    def test_cache_stores_hash_not_raw_key(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"valid": True, "plan": "solo", "expires": None}
        mock_resp.raise_for_status = MagicMock()

        with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
            with patch("cloakbrowser.license.httpx.post", return_value=mock_resp):
                validate_license("secret-key-123")

        cache_path = tmp_path / ".license_cache"
        content = cache_path.read_text()
        assert "secret-key-123" not in content
        expected_sha = hashlib.sha256(b"secret-key-123").hexdigest()
        assert expected_sha in content

    def test_expired_license_rejected_from_cache(self, tmp_path):
        cache_path = tmp_path / ".license_cache"
        key_sha = hashlib.sha256(b"test-key").hexdigest()
        cache_path.write_text(json.dumps({
            "key_sha256": key_sha,
            "valid": True,
            "plan": "solo",
            "expires": "2020-01-01T00:00:00+00:00",
            "validated_at": time.time(),
        }))

        with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
            result = validate_license("test-key")

        assert result is not None
        assert result.valid is False

    def test_expired_license_naive_date_rejected(self, tmp_path):
        """Date-only string (naive datetime) should also be detected as expired."""
        cache_path = tmp_path / ".license_cache"
        key_sha = hashlib.sha256(b"test-key").hexdigest()
        cache_path.write_text(json.dumps({
            "key_sha256": key_sha,
            "valid": True,
            "plan": "solo",
            "expires": "2020-01-01",
            "validated_at": time.time(),
        }))

        with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
            result = validate_license("test-key")

        assert result is not None
        assert result.valid is False

    def test_wrong_key_cache_ignored(self, tmp_path):
        cache_path = tmp_path / ".license_cache"
        cache_path.write_text(json.dumps({
            "key_sha256": "other-hash",
            "valid": True,
            "plan": "solo",
            "expires": None,
            "validated_at": time.time(),
        }))

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"valid": True, "plan": "solo", "expires": None}
        mock_resp.raise_for_status = MagicMock()

        with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
            with patch("cloakbrowser.license.httpx.post", return_value=mock_resp) as mock_post:
                validate_license("different-key")

        mock_post.assert_called_once()

    def test_corrupted_validated_at_does_not_crash(self, tmp_path):
        """A non-numeric validated_at must be treated as an absent cache, not crash."""
        cache_path = tmp_path / ".license_cache"
        key_sha = hashlib.sha256(b"test-key").hexdigest()
        cache_path.write_text(json.dumps({
            "key_sha256": key_sha,
            "valid": True,
            "plan": "solo",
            "expires": None,
            "validated_at": "not-a-number",
        }))

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"valid": True, "plan": "solo", "expires": None}
        mock_resp.raise_for_status = MagicMock()

        with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
            with patch("cloakbrowser.license.httpx.post", return_value=mock_resp) as mock_post:
                result = validate_license("test-key")

        mock_post.assert_called_once()  # corrupted cache ignored → server hit
        assert result is not None
        assert result.valid is True


# ── get_pro_latest_version ────────────────────────────


class TestGetProLatestVersion:
    def test_fetches_version(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"version": "147.0.1234.5"}
        mock_resp.raise_for_status = MagicMock()

        with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
            with patch("cloakbrowser.license.httpx.get", return_value=mock_resp):
                version = get_pro_latest_version()

        assert version == "147.0.1234.5"

    def test_sends_platform_header(self, tmp_path):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"version": "147.0.1234.5"}
        mock_resp.raise_for_status = MagicMock()

        with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
            with patch(
                "cloakbrowser.license.get_platform_tag", return_value="darwin-arm64"
            ):
                with patch(
                    "cloakbrowser.license.httpx.get", return_value=mock_resp
                ) as mock_get:
                    get_pro_latest_version()

        _, kwargs = mock_get.call_args
        assert kwargs["headers"]["X-Platform"] == "darwin-arm64"

    def test_rate_limited(self, tmp_path):
        marker = tmp_path / ".last_pro_version_check_darwin-arm64"
        marker.write_text("147.0.1234.5")

        with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
            with patch(
                "cloakbrowser.license.get_platform_tag", return_value="darwin-arm64"
            ):
                with patch("cloakbrowser.license.httpx.get") as mock_get:
                    version = get_pro_latest_version()

        mock_get.assert_not_called()
        assert version == "147.0.1234.5"

    def test_network_error_returns_none(self, tmp_path):
        with patch("cloakbrowser.license.get_cache_dir", return_value=tmp_path):
            with patch("cloakbrowser.license.httpx.get", side_effect=Exception("network")):
                version = get_pro_latest_version()

        assert version is None


# ── get_active_session_count ──────────────────────────


class TestGetActiveSessionCount:
    def _resp(self, payload):
        mock_resp = MagicMock()
        mock_resp.json.return_value = payload
        mock_resp.raise_for_status = MagicMock()
        return mock_resp

    def test_returns_count(self):
        with patch(
            "cloakbrowser.license.httpx.post", return_value=self._resp({"valid": True, "active": 3})
        ):
            assert get_active_session_count("cb_key") == 3

    def test_posts_the_key_in_the_body(self):
        """POST, not GET: the key is a live credential and a query string would
        land in the server's access log."""
        with patch(
            "cloakbrowser.license.httpx.post", return_value=self._resp({"valid": True, "active": 0})
        ) as mock_post:
            get_active_session_count("cb_key")

        args, kwargs = mock_post.call_args
        assert args[0] == "https://cloakbrowser.dev/api/license/session/count"
        assert kwargs["json"] == {"license_key": "cb_key"}

    def test_zero_seats_is_not_confused_with_unknown(self):
        """0 is a real answer ("nothing running"), None means "couldn't tell" —
        they print differently, so the falsy-vs-None distinction must survive."""
        with patch(
            "cloakbrowser.license.httpx.post", return_value=self._resp({"valid": True, "active": 0})
        ):
            assert get_active_session_count("cb_key") == 0

    def test_server_reported_unavailable_returns_none(self):
        """Leaseless mode on the server → {"active": null}, never a false 0."""
        with patch(
            "cloakbrowser.license.httpx.post",
            return_value=self._resp({"valid": True, "active": None}),
        ):
            assert get_active_session_count("cb_key") is None

    def test_network_error_returns_none(self):
        """info is a diagnostic — a network failure degrades to "unavailable",
        it never raises out of the command."""
        with patch("cloakbrowser.license.httpx.post", side_effect=Exception("network")):
            assert get_active_session_count("cb_key") is None

    def test_is_never_cached(self):
        """validate_license caches 24h; a cached seat count would be a wrong seat
        count, so every call must hit the network."""
        with patch(
            "cloakbrowser.license.httpx.post", return_value=self._resp({"valid": True, "active": 2})
        ) as mock_post:
            get_active_session_count("cb_key")
            get_active_session_count("cb_key")

        assert mock_post.call_count == 2


# ── Config pro parameter ──────────────────────────────


class TestConfigPro:
    def test_binary_dir_pro_suffix(self, tmp_path):
        from cloakbrowser.config import get_binary_dir

        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            normal = get_binary_dir("147.0.0.0")
            pro = get_binary_dir("147.0.0.0", pro=True)

        assert str(normal).endswith("chromium-147.0.0.0")
        assert str(pro).endswith("chromium-147.0.0.0-pro")

    def test_binary_dir_default_no_suffix(self, tmp_path):
        from cloakbrowser.config import get_binary_dir

        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            normal = get_binary_dir("147.0.0.0")

        assert not str(normal).endswith("-pro")

    def test_effective_version_pro_marker(self, tmp_path):
        from cloakbrowser.config import get_effective_version, get_platform_tag

        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            tag = get_platform_tag()
            marker = tmp_path / f"latest_pro_version_{tag}"
            marker.write_text("147.0.5555.1")

            # Create the binary so effective version returns it
            from cloakbrowser.config import get_binary_path
            bp = get_binary_path("147.0.5555.1", pro=True)
            bp.parent.mkdir(parents=True, exist_ok=True)
            bp.write_text("fake")
            bp.chmod(0o755)  # get_effective_version(pro) requires an executable binary

            version = get_effective_version(pro=True)

        assert version == "147.0.5555.1"


# ── binary_info tier reporting ────────────────────────


class TestBinaryInfoTier:
    """binary_info() reports tier from the binary actually on disk — NOT from a
    cached license, which can disagree with what's installed or the active key."""

    def test_free_when_no_pro_binary_even_if_license_cached(self, tmp_path):
        from cloakbrowser.download import binary_info

        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}, clear=False):
            # A valid, fresh license is cached...
            (tmp_path / ".license_cache").write_text(json.dumps({
                "key_sha256": hashlib.sha256(b"cb_x").hexdigest(),
                "valid": True, "plan": "solo", "expires": None,
                "validated_at": time.time(),
            }))
            # ...but no Pro binary is on disk → must report free, not pro.
            info = binary_info()

        assert info["tier"] == "free"

    def test_pro_when_pro_binary_installed(self, tmp_path):
        from cloakbrowser.config import get_binary_path, get_platform_tag
        from cloakbrowser.download import binary_info

        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}, clear=False):
            tag = get_platform_tag()
            (tmp_path / f"latest_pro_version_{tag}").write_text("147.0.5555.1")
            bp = get_binary_path("147.0.5555.1", pro=True)
            bp.parent.mkdir(parents=True, exist_ok=True)
            bp.write_text("fake")
            bp.chmod(0o755)
            info = binary_info()

        assert info["tier"] == "pro"
        assert info["version"] == "147.0.5555.1"


# ── ensure_binary Pro routing (fail-closed vs fall-back) ──────────────────────


class TestEnsureBinaryProRouting:
    """A valid-license user is NEVER silently downgraded to the free binary. Both
    a tampering signal (verification failure) and a transient failure
    (network/server) surface a clear error — they differ only in the message:
    tampering is re-raised verbatim (security, no 'retry'); transient is rewrapped
    as an actionable 'Pro binary unavailable, retry' error carrying the cause."""

    def test_verification_failure_propagates_verbatim(self):
        """A BinaryVerificationError must surface verbatim — never reach free."""
        with patch.dict(os.environ, {"CLOAKBROWSER_DOWNLOAD_URL": ""}, clear=False), \
             patch("cloakbrowser.download.get_local_binary_override", return_value=None), \
             patch("cloakbrowser.license.resolve_license_key", return_value="cb_x"), \
             patch("cloakbrowser.license.validate_license",
                   return_value=LicenseInfo(valid=True, plan="solo", expires=None)), \
             patch("cloakbrowser.download._ensure_pro_binary",
                   side_effect=BinaryVerificationError("bad signature")), \
             patch("cloakbrowser.download.check_platform_available",
                   side_effect=AssertionError("MUST NOT reach the free-tier path")):
            with pytest.raises(BinaryVerificationError, match="bad signature"):
                ensure_binary("cb_x")

    def test_transient_failure_hard_errors_not_free(self):
        """A transient Pro failure must surface a clear, actionable error carrying
        the underlying cause — NOT silently download the free binary."""
        with patch.dict(os.environ, {"CLOAKBROWSER_DOWNLOAD_URL": ""}, clear=False), \
             patch("cloakbrowser.download.get_local_binary_override", return_value=None), \
             patch("cloakbrowser.license.resolve_license_key", return_value="cb_x"), \
             patch("cloakbrowser.license.validate_license",
                   return_value=LicenseInfo(valid=True, plan="solo", expires=None)), \
             patch("cloakbrowser.download._ensure_pro_binary",
                   side_effect=RuntimeError("network blip")), \
             patch("cloakbrowser.download.check_platform_available",
                   side_effect=AssertionError("MUST NOT reach the free-tier path")):
            with pytest.raises(RuntimeError, match="Pro binary unavailable: network blip"):
                ensure_binary("cb_x")

    def test_macos_pro_404_hard_errors_not_free(self):
        """macOS now has a Pro binary, so a 404 on the Pro download is a real error
        and must hard-fail like every other platform — NOT silently fall back to the
        free binary (the v0.4.2 darwin-404→free stopgap was reverted in v0.4.3)."""
        import httpx

        req = httpx.Request("GET", "https://example.com/download")
        not_found = httpx.HTTPStatusError(
            "404 Not Found", request=req, response=httpx.Response(404, request=req)
        )
        with patch.dict(os.environ, {"CLOAKBROWSER_DOWNLOAD_URL": ""}, clear=False), \
             patch("cloakbrowser.download.get_local_binary_override", return_value=None), \
             patch("cloakbrowser.download.get_platform_tag", return_value="darwin-x64"), \
             patch("cloakbrowser.license.resolve_license_key", return_value="cb_x"), \
             patch("cloakbrowser.license.validate_license",
                   return_value=LicenseInfo(valid=True, plan="solo", expires=None)), \
             patch("cloakbrowser.download._ensure_pro_binary", side_effect=not_found), \
             patch("cloakbrowser.download.check_platform_available",
                   side_effect=AssertionError("MUST NOT reach the free-tier path on macOS")):
            with pytest.raises(RuntimeError, match="Pro binary unavailable"):
                ensure_binary("cb_x")


# ── build_launch_env ──────────────────────────────────


class TestBuildLaunchEnv:
    """Tests for the build_launch_env helper that decides whether license key
    env injection is needed in the spawned browser process."""

    def test_no_key_no_env_returns_none(self):
        """No key anywhere → None (no env dict to inject)."""
        with patch.dict(os.environ, {}, clear=True), \
             patch("cloakbrowser.license.get_cache_dir") as mock_cache:
            mock_cache.return_value = Path("/tmp/no-such-dir")
            assert build_launch_env() is None
            assert build_launch_env(user_env={"FOO": "bar"}) == {"FOO": "bar"}
            # None values are filtered consistently across all return paths.
            assert build_launch_env(user_env={"FOO": "bar", "BAZ": None}) == {"FOO": "bar"}

    def test_explicit_param_injects_env(self):
        """Explicit license_key param → env dict with key injected."""
        result = build_launch_env(license_key="cb_test_key")
        assert result is not None
        assert result["CLOAKBROWSER_LICENSE_KEY"] == "cb_test_key"
        # Should also preserve the rest of the parent env
        assert "HOME" in result

    def test_env_source_no_user_env_returns_none(self):
        """Key from env var, no custom user_env → None (child inherits parent)."""
        with patch.dict(os.environ, {"CLOAKBROWSER_LICENSE_KEY": "cb_env"}):
            assert build_launch_env() is None

    def test_env_source_with_user_env_preserves_key(self):
        """Key from env var + explicit user_env → merged env with key."""
        with patch.dict(os.environ, {"CLOAKBROWSER_LICENSE_KEY": "cb_env"}):
            result = build_launch_env(user_env={"MY_VAR": "1"})
            assert result is not None
            assert result["CLOAKBROWSER_LICENSE_KEY"] == "cb_env"
            assert result["MY_VAR"] == "1"

    def test_default_file_skips_injection(self, tmp_path):
        """Key from default ~/.cloakbrowser/license.key → no env injection.
        The binary reads that file directly."""
        home_dir = tmp_path / "home"
        default_cache = home_dir / ".cloakbrowser"
        default_cache.mkdir(parents=True)
        (default_cache / "license.key").write_text("cb_file_key\n")

        with patch.dict(os.environ, {}, clear=True), \
             patch("cloakbrowser.license.get_cache_dir", return_value=default_cache), \
             patch("pathlib.Path.home", return_value=home_dir):
            result = build_launch_env()
            assert result is None

            # With a custom user_env, Playwright replaces the child env (which
            # could drop HOME and hide the file), so the key IS injected.
            result2 = build_launch_env(user_env={"KEEP": "me"})
            assert result2 == {"KEEP": "me", "CLOAKBROWSER_LICENSE_KEY": "cb_file_key"}

    def test_custom_cache_dir_injects_env(self, tmp_path):
        """Key from CLOAKBROWSER_CACHE_DIR/license.key → env injection needed
        because the binary looks at ~/.cloakbrowser/license.key, not the custom path."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        custom_cache = tmp_path / "custom-cache"
        custom_cache.mkdir()
        (custom_cache / "license.key").write_text("cb_custom\n")

        with patch.dict(os.environ, {}, clear=True), \
             patch("cloakbrowser.license.get_cache_dir", return_value=custom_cache), \
             patch("pathlib.Path.home", return_value=home_dir):
            result = build_launch_env()
            assert result is not None
            assert result["CLOAKBROWSER_LICENSE_KEY"] == "cb_custom"
            # User env preserved — but os.environ was cleared so only the key exists
            assert len(result) == 1

    def test_explicit_param_merges_user_env(self):
        """Explicit param + user_env → user_env entries preserved alongside key."""
        result = build_launch_env(license_key="cb_mine", user_env={"PATH": "/bin"})
        assert result is not None
        assert result["CLOAKBROWSER_LICENSE_KEY"] == "cb_mine"
        assert result["PATH"] == "/bin"
        # Should NOT contain the full os.environ (user env replaces it)
        assert "HOME" not in result

    def test_empty_license_key_treated_as_missing(self):
        """Empty/whitespace key param treated as absent → None."""
        assert build_launch_env(license_key="") is None
        assert build_launch_env(license_key="   ") is None
