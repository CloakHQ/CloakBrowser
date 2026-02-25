"""Tests for auto-update and version management."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cloakbrowser.config import (
    CHROMIUM_VERSION,
    _version_newer,
    _version_tuple,
    get_download_url,
    get_effective_version,
)
from cloakbrowser.download import (
    _get_latest_chromium_version,
    _should_check_for_update,
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


class TestDownloadUrl:
    def test_default_url_format(self):
        url = get_download_url()
        assert "github.com/CloakHQ/cloakbrowser/releases/download" in url
        assert f"chromium-v{CHROMIUM_VERSION}" in url
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
    def test_no_marker_returns_hardcoded(self, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            assert get_effective_version() == CHROMIUM_VERSION

    def test_marker_with_newer_version(self, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            marker = tmp_path / "latest_version"
            marker.write_text("999.0.0.0")
            # Binary doesn't exist, so should fall back
            assert get_effective_version() == CHROMIUM_VERSION

    def test_marker_with_older_version_ignored(self, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            marker = tmp_path / "latest_version"
            marker.write_text("100.0.0.0")
            assert get_effective_version() == CHROMIUM_VERSION


class TestGetLatestVersion:
    def test_parses_chromium_tag(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"tag_name": "chromium-v145.0.7718.0", "draft": False},
            {"tag_name": "chromium-v142.0.7444.175", "draft": False},
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("cloakbrowser.download.httpx.get", return_value=mock_response):
            result = _get_latest_chromium_version()
            assert result == "145.0.7718.0"

    def test_skips_draft_releases(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"tag_name": "chromium-v999.0.0.0", "draft": True},
            {"tag_name": "chromium-v145.0.7718.0", "draft": False},
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("cloakbrowser.download.httpx.get", return_value=mock_response):
            result = _get_latest_chromium_version()
            assert result == "145.0.7718.0"

    def test_skips_non_chromium_tags(self):
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"tag_name": "v0.2.0", "draft": False},
            {"tag_name": "chromium-v145.0.7718.0", "draft": False},
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("cloakbrowser.download.httpx.get", return_value=mock_response):
            result = _get_latest_chromium_version()
            assert result == "145.0.7718.0"

    def test_network_error_returns_none(self):
        with patch("cloakbrowser.download.httpx.get", side_effect=Exception("timeout")):
            result = _get_latest_chromium_version()
            assert result is None
