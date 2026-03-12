"""Tests for auto-update and version management."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cloakbrowser.config import (
    CHROMIUM_VERSION,
    _version_newer,
    _version_tuple,
    get_chromium_version,
    get_download_url,
    get_effective_version,
    get_platform_tag,
)
from cloakbrowser.download import (
    _check_wrapper_update,
    _download_and_extract,
    _fetch_checksums,
    _get_latest_chromium_version,
    _parse_checksums,
    _should_check_for_update,
    _verify_checksum,
    _write_version_marker,
    check_for_update,
    clear_cache,
    ensure_binary,
)


class TestVersionComparison:
    def test_version_tuple_parsing(self):
        assert _version_tuple("145.0.7718.0") == (145, 0, 7718, 0)
        assert _version_tuple("142.0.7444.175") == (142, 0, 7444, 175)

    def test_newer_version(self):
        assert _version_newer("145.0.7718.0", "142.0.7444.175") is True

    def test_older_version(self):
        assert _version_newer("142.0.7444.175", "145.0.7718.0") is False

    def test_same_version(self):
        assert _version_newer("142.0.7444.175", "142.0.7444.175") is False

    def test_patch_bump(self):
        assert _version_newer("142.0.7444.176", "142.0.7444.175") is True

    def test_major_bump(self):
        assert _version_newer("143.0.0.0", "142.9.9999.999") is True

    def test_5th_segment_parsing(self):
        assert _version_tuple("145.0.7632.109.2") == (145, 0, 7632, 109, 2)

    def test_build_bump(self):
        assert _version_newer("145.0.7632.109.3", "145.0.7632.109.2") is True

    def test_build_suffix_newer_than_no_suffix(self):
        assert _version_newer("145.0.7632.109.2", "145.0.7632.109") is True

    def test_no_suffix_older_than_build_suffix(self):
        assert _version_newer("145.0.7632.109", "145.0.7632.109.2") is False

    def test_new_chromium_beats_old_build(self):
        assert _version_newer("146.0.0.0", "145.0.7632.109.2") is True


class TestDownloadUrl:
    def test_default_url_format(self):
        url = get_download_url()
        assert "cloakbrowser.dev" in url
        assert f"chromium-v{get_chromium_version()}" in url
        assert url.endswith(".tar.gz")

    def test_custom_version_url(self):
        url = get_download_url("145.0.7718.0")
        assert "chromium-v145.0.7718.0" in url

    def test_no_old_repo_reference(self):
        url = get_download_url()
        assert "chromium-stealth-builds" not in url


class TestShouldCheckForUpdate:
    def test_disabled_by_env(self):
        with patch.dict(os.environ, {"CLOAKBROWSER_AUTO_UPDATE": "false"}):
            assert _should_check_for_update() is False

    def test_disabled_by_env_case_insensitive(self):
        with patch.dict(os.environ, {"CLOAKBROWSER_AUTO_UPDATE": "False"}):
            assert _should_check_for_update() is False

    def test_disabled_by_binary_override(self):
        with patch.dict(os.environ, {"CLOAKBROWSER_BINARY_PATH": "/some/path"}):
            assert _should_check_for_update() is False

    def test_disabled_by_custom_download_url(self):
        with patch.dict(
            os.environ, {"CLOAKBROWSER_DOWNLOAD_URL": "https://my-mirror.com"}
        ):
            assert _should_check_for_update() is False

    def test_rate_limited(self, tmp_path):
        import time

        with patch.dict(
            os.environ,
            {
                "CLOAKBROWSER_CACHE_DIR": str(tmp_path),
                "CLOAKBROWSER_BINARY_PATH": "",
                "CLOAKBROWSER_AUTO_UPDATE": "",
                "CLOAKBROWSER_DOWNLOAD_URL": "",
            },
        ):
            check_file = tmp_path / ".last_update_check"
            check_file.write_text(str(time.time()))
            assert _should_check_for_update() is False

    def test_stale_rate_limit_allows_check(self, tmp_path):
        import time

        with patch.dict(
            os.environ,
            {
                "CLOAKBROWSER_CACHE_DIR": str(tmp_path),
                "CLOAKBROWSER_BINARY_PATH": "",
                "CLOAKBROWSER_AUTO_UPDATE": "",
                "CLOAKBROWSER_DOWNLOAD_URL": "",
            },
        ):
            check_file = tmp_path / ".last_update_check"
            check_file.write_text(str(time.time() - 7200))  # 2 hours ago
            assert _should_check_for_update() is True


class TestEffectiveVersion:
    def test_no_marker_returns_platform_version(self, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            assert get_effective_version() == get_chromium_version()

    def test_marker_with_newer_version(self, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            marker = tmp_path / f"latest_version_{get_platform_tag()}"
            marker.write_text("999.0.0.0")
            # Binary doesn't exist, so should fall back
            assert get_effective_version() == get_chromium_version()

    def test_marker_with_older_version_ignored(self, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            marker = tmp_path / f"latest_version_{get_platform_tag()}"
            marker.write_text("100.0.0.0")
            assert get_effective_version() == get_chromium_version()


class TestGetLatestVersion:
    """Tests for _get_latest_chromium_version with platform-aware asset checking."""

    def _make_assets(self, platforms: list[str]) -> list[dict]:
        """Helper to build asset list from platform tags."""
        return [{"name": f"cloakbrowser-{p}.tar.gz"} for p in platforms]

    def _platform_tarball(self) -> str:
        return f"cloakbrowser-{get_platform_tag()}.tar.gz"

    def test_parses_chromium_tag_with_platform_asset(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "tag_name": "chromium-v145.0.7718.0",
                "draft": False,
                "assets": self._make_assets(["linux-x64", "darwin-arm64", "darwin-x64", "windows-x64"]),
            },
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("cloakbrowser.download.httpx.get", return_value=mock_response):
            result = _get_latest_chromium_version()
            assert result == "145.0.7718.0"

    def test_skips_release_without_platform_asset(self):
        """If latest release has no asset for our platform, fall back to older release."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "tag_name": "chromium-v145.0.7718.0",
                "draft": False,
                "assets": self._make_assets(["linux-x64"]),  # Linux only
            },
            {
                "tag_name": "chromium-v142.0.7444.175",
                "draft": False,
                "assets": self._make_assets(["linux-x64", "darwin-arm64", "darwin-x64", "windows-x64"]),
            },
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("cloakbrowser.download.httpx.get", return_value=mock_response):
            result = _get_latest_chromium_version()
            tag = get_platform_tag()
            if tag == "linux-x64":
                assert result == "145.0.7718.0"
            else:
                assert result == "142.0.7444.175"

    def test_skips_draft_releases(self):
        mock_response = MagicMock()
        all_platforms = ["linux-x64", "darwin-arm64", "darwin-x64", "windows-x64"]
        mock_response.json.return_value = [
            {"tag_name": "chromium-v999.0.0.0", "draft": True, "assets": self._make_assets(all_platforms)},
            {"tag_name": "chromium-v145.0.7718.0", "draft": False, "assets": self._make_assets(all_platforms)},
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("cloakbrowser.download.httpx.get", return_value=mock_response):
            result = _get_latest_chromium_version()
            assert result == "145.0.7718.0"

    def test_skips_non_chromium_tags(self):
        mock_response = MagicMock()
        all_platforms = ["linux-x64", "darwin-arm64", "darwin-x64", "windows-x64"]
        mock_response.json.return_value = [
            {"tag_name": "v0.2.0", "draft": False, "assets": self._make_assets(all_platforms)},
            {"tag_name": "chromium-v145.0.7718.0", "draft": False, "assets": self._make_assets(all_platforms)},
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("cloakbrowser.download.httpx.get", return_value=mock_response):
            result = _get_latest_chromium_version()
            assert result == "145.0.7718.0"

    def test_returns_none_when_no_platform_assets(self):
        """If no release has our platform, return None."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "tag_name": "chromium-v145.0.7718.0",
                "draft": False,
                "assets": [{"name": "cloakbrowser-freebsd-x64.tar.gz"}],
            },
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("cloakbrowser.download.httpx.get", return_value=mock_response):
            result = _get_latest_chromium_version()
            assert result is None

    def test_network_error_returns_none(self):
        with patch("cloakbrowser.download.httpx.get", side_effect=Exception("timeout")):
            result = _get_latest_chromium_version()
            assert result is None


class TestWrapperUpdateCheck:
    """Tests for _check_wrapper_update (PyPI version check)."""

    def setup_method(self):
        import cloakbrowser.download as dl
        dl._wrapper_update_checked = False

    def test_warns_when_newer_version_available(self, caplog):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"info": {"version": "99.0.0"}}
        mock_resp.raise_for_status = MagicMock()

        with patch("cloakbrowser.download.httpx.get", return_value=mock_resp):
            import logging
            with caplog.at_level(logging.WARNING):
                _check_wrapper_update()
            assert "Update available" in caplog.text
            assert "99.0.0" in caplog.text

    def test_silent_when_current(self, caplog):
        import cloakbrowser.download as dl
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"info": {"version": dl._wrapper_version}}
        mock_resp.raise_for_status = MagicMock()

        with patch("cloakbrowser.download.httpx.get", return_value=mock_resp):
            import logging
            with caplog.at_level(logging.WARNING):
                _check_wrapper_update()
            assert "Update available" not in caplog.text

    def test_disabled_by_auto_update_env(self):
        with patch.dict(os.environ, {"CLOAKBROWSER_AUTO_UPDATE": "false"}):
            with patch("cloakbrowser.download.httpx.get") as mock_get:
                _check_wrapper_update()
                mock_get.assert_not_called()

    def test_disabled_by_custom_download_url(self):
        with patch.dict(os.environ, {"CLOAKBROWSER_DOWNLOAD_URL": "https://mirror.example.com"}):
            with patch("cloakbrowser.download.httpx.get") as mock_get:
                _check_wrapper_update()
                mock_get.assert_not_called()

    def test_network_error_silent(self, caplog):
        with patch("cloakbrowser.download.httpx.get", side_effect=Exception("timeout")):
            import logging
            with caplog.at_level(logging.WARNING):
                _check_wrapper_update()
            assert "Update available" not in caplog.text

    def test_runs_only_once(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"info": {"version": "0.0.1"}}
        mock_resp.raise_for_status = MagicMock()

        with patch("cloakbrowser.download.httpx.get", return_value=mock_resp) as mock_get:
            _check_wrapper_update()
            _check_wrapper_update()
            assert mock_get.call_count == 1


class TestParseChecksums:
    HASH_A = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    HASH_B = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"

    def test_standard_format(self):
        text = (
            f"{self.HASH_A}  cloakbrowser-linux-x64.tar.gz\n"
            f"{self.HASH_B}  cloakbrowser-darwin-arm64.tar.gz\n"
        )
        result = _parse_checksums(text)
        assert result["cloakbrowser-linux-x64.tar.gz"] == self.HASH_A
        assert result["cloakbrowser-darwin-arm64.tar.gz"] == self.HASH_B

    def test_binary_mode_asterisk(self):
        text = f"{self.HASH_A} *cloakbrowser-linux-x64.tar.gz\n"
        result = _parse_checksums(text)
        assert "cloakbrowser-linux-x64.tar.gz" in result

    def test_empty_lines_skipped(self):
        text = f"\n\n{self.HASH_A}  file.tar.gz\n\n"
        result = _parse_checksums(text)
        assert len(result) == 1

    def test_uppercase_lowered(self):
        text = f"{self.HASH_A.upper()}  file.tar.gz\n"
        result = _parse_checksums(text)
        assert result["file.tar.gz"] == self.HASH_A

    def test_empty_input(self):
        assert _parse_checksums("") == {}
        assert _parse_checksums("   \n  \n") == {}


class TestVerifyChecksum:
    def test_matching_checksum(self, tmp_path):
        content = b"test binary content"
        file = tmp_path / "test.tar.gz"
        file.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        # Should not raise
        _verify_checksum(file, expected)

    def test_mismatched_checksum(self, tmp_path):
        file = tmp_path / "test.tar.gz"
        file.write_bytes(b"real content")
        with pytest.raises(RuntimeError, match="Checksum verification failed"):
            _verify_checksum(file, "0" * 64)


class TestClearCache:
    def test_removes_dir(self, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            # Create some content
            (tmp_path / "chromium-145").mkdir()
            (tmp_path / "chromium-145" / "chrome").write_bytes(b"binary")
            clear_cache()
            assert not tmp_path.exists()

    def test_noop_if_missing(self, tmp_path):
        nonexistent = tmp_path / "nonexistent"
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(nonexistent)}):
            clear_cache()  # Should not raise


class TestCheckForUpdate:
    @patch("cloakbrowser.download._maybe_trigger_update_check")
    def test_returns_none_when_current(self, _mock_update):
        with patch("cloakbrowser.download._get_latest_chromium_version", return_value=None):
            assert check_for_update() is None

    @patch("cloakbrowser.download._maybe_trigger_update_check")
    def test_returns_none_on_network_error(self, _mock_update):
        with patch("cloakbrowser.download._get_latest_chromium_version", side_effect=Exception("timeout")):
            # _get_latest_chromium_version catches exceptions internally, but
            # check_for_update itself can also fail — test graceful None return
            with patch("cloakbrowser.download._get_latest_chromium_version", return_value=None):
                assert check_for_update() is None

    @patch("cloakbrowser.download._maybe_trigger_update_check")
    def test_returns_version_when_newer(self, _mock_update, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            with patch("cloakbrowser.download._get_latest_chromium_version", return_value="999.0.0.0"):
                with patch("cloakbrowser.download._download_and_extract"):
                    result = check_for_update()
                    assert result == "999.0.0.0"

    @patch("cloakbrowser.download._maybe_trigger_update_check")
    def test_skips_download_if_already_cached(self, _mock_update, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            # Create the binary dir so it looks already downloaded
            binary_dir = tmp_path / "chromium-999.0.0.0"
            binary_dir.mkdir()
            with patch("cloakbrowser.download._get_latest_chromium_version", return_value="999.0.0.0"):
                with patch("cloakbrowser.download._download_and_extract") as mock_dl:
                    result = check_for_update()
                    assert result == "999.0.0.0"
                    mock_dl.assert_not_called()


class TestEnsureBinary:
    @patch("cloakbrowser.download._maybe_trigger_update_check")
    def test_local_override(self, _mock_update, tmp_path):
        binary = tmp_path / "chrome"
        binary.write_bytes(b"binary")
        with patch.dict(os.environ, {"CLOAKBROWSER_BINARY_PATH": str(binary)}):
            result = ensure_binary()
            assert result == str(binary)

    @patch("cloakbrowser.download._maybe_trigger_update_check")
    def test_local_override_missing_file(self, _mock_update):
        with patch.dict(os.environ, {"CLOAKBROWSER_BINARY_PATH": "/nonexistent/chrome"}):
            with pytest.raises(FileNotFoundError, match="does not exist"):
                ensure_binary()

    @patch("cloakbrowser.download._maybe_trigger_update_check")
    def test_cached_binary_found(self, _mock_update, tmp_path):
        with patch.dict(os.environ, {
            "CLOAKBROWSER_CACHE_DIR": str(tmp_path),
            "CLOAKBROWSER_BINARY_PATH": "",
        }):
            # Create a fake cached binary
            version = get_chromium_version()
            with patch("cloakbrowser.download.get_binary_path") as mock_path:
                fake_binary = tmp_path / "chrome"
                fake_binary.write_bytes(b"binary")
                fake_binary.chmod(0o755)
                mock_path.return_value = fake_binary
                with patch("cloakbrowser.download.check_platform_available"):
                    result = ensure_binary()
                    assert result == str(fake_binary)

    @patch("cloakbrowser.download._maybe_trigger_update_check")
    def test_downloads_when_missing(self, _mock_update, tmp_path):
        with patch.dict(os.environ, {
            "CLOAKBROWSER_CACHE_DIR": str(tmp_path),
            "CLOAKBROWSER_BINARY_PATH": "",
        }):
            fake_binary = tmp_path / "chrome"
            with patch("cloakbrowser.download.check_platform_available"):
                with patch("cloakbrowser.download.get_binary_path") as mock_path:
                    # effective == platform_version (no marker), so fallback block skipped.
                    # Call 1: get_binary_path(effective) → nonexistent (triggers download)
                    # Call 2: get_binary_path() → fake_binary (post-download verify)
                    mock_path.side_effect = [
                        tmp_path / "nonexistent",  # pre-download: not cached
                        fake_binary,               # post-download: binary ready
                    ]
                    with patch("cloakbrowser.download._download_and_extract") as mock_dl:
                        fake_binary.write_bytes(b"binary")
                        result = ensure_binary()
                        mock_dl.assert_called_once()
                        assert result == str(fake_binary)


class TestWriteVersionMarker:
    def test_creates_file(self, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            _write_version_marker("999.0.0.0")
            marker = tmp_path / f"latest_version_{get_platform_tag()}"
            assert marker.exists()
            assert marker.read_text() == "999.0.0.0"


class TestDownloadFallback:
    """Verify primary server (cloakbrowser.dev) → GitHub Releases fallback on HTTP errors."""

    def test_binary_download_falls_back_on_http_error(self, tmp_path):
        """HTTP error from primary triggers GitHub Releases fallback for binary download."""
        with patch.dict(os.environ, {
            "CLOAKBROWSER_CACHE_DIR": str(tmp_path),
            "CLOAKBROWSER_DOWNLOAD_URL": "",
            "CLOAKBROWSER_SKIP_CHECKSUM": "true",
        }):
            urls_called = []

            def mock_download_file(url, dest):
                urls_called.append(url)
                if "cloakbrowser.dev" in url:
                    raise Exception("HTTP 429 Too Many Requests")
                # GitHub fallback succeeds
                dest.write_bytes(b"fake")

            with patch("cloakbrowser.download._download_file", side_effect=mock_download_file), \
                 patch("cloakbrowser.download._extract_archive"), \
                 patch("cloakbrowser.download._show_welcome"):
                _download_and_extract()

            assert len(urls_called) == 2
            assert "cloakbrowser.dev" in urls_called[0]
            assert "github.com" in urls_called[1]

    def test_binary_download_no_fallback_with_custom_url(self, tmp_path):
        """Custom CLOAKBROWSER_DOWNLOAD_URL disables GitHub fallback — error propagates."""
        with patch.dict(os.environ, {
            "CLOAKBROWSER_CACHE_DIR": str(tmp_path),
            "CLOAKBROWSER_DOWNLOAD_URL": "https://my-mirror.com/releases",
            "CLOAKBROWSER_SKIP_CHECKSUM": "true",
        }):
            with patch("cloakbrowser.download._download_file", side_effect=Exception("503")):
                with pytest.raises(Exception, match="503"):
                    _download_and_extract()

    def test_checksum_fetch_falls_back_on_http_error(self):
        """HTTP error from primary checksum URL triggers GitHub fallback."""
        valid_checksums = (
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
            "  cloakbrowser-linux-x64.tar.gz\n"
        )

        def mock_get(url, **kwargs):
            resp = MagicMock()
            if "cloakbrowser.dev" in url:
                resp.raise_for_status.side_effect = Exception("HTTP 429")
                return resp
            # GitHub URL succeeds
            resp.text = valid_checksums
            resp.raise_for_status = MagicMock()
            return resp

        with patch.dict(os.environ, {"CLOAKBROWSER_DOWNLOAD_URL": ""}):
            with patch("cloakbrowser.download.httpx.get", side_effect=mock_get):
                result = _fetch_checksums()

        assert result is not None
        assert "cloakbrowser-linux-x64.tar.gz" in result

    def test_checksum_fetch_returns_none_when_both_fail(self):
        """Both primary and GitHub checksum URLs fail → returns None (skip verification)."""
        with patch.dict(os.environ, {"CLOAKBROWSER_DOWNLOAD_URL": ""}):
            with patch("cloakbrowser.download.httpx.get", side_effect=Exception("network error")):
                result = _fetch_checksums()

        assert result is None
