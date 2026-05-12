"""Unit tests for config.py — platform detection, paths, stealth args."""

import os
from unittest.mock import patch

import pytest

from cloakbrowser.config import (
    get_archive_ext,
    get_archive_name,
    get_binary_path,
    get_cache_dir,
    get_chromium_version,
    get_default_stealth_args,
    get_fallback_download_url,
    get_platform_tag,
)


# ---------------------------------------------------------------------------
# Platform-specific binary paths
# ---------------------------------------------------------------------------


class TestGetBinaryPath:
    def test_linux(self):
        with patch("cloakbrowser.config.platform.system", return_value="Linux"):
            path = get_binary_path("145.0.0.0")
            assert path.as_posix().endswith("chromium-145.0.0.0/chrome")

    def test_darwin(self):
        with patch("cloakbrowser.config.platform.system", return_value="Darwin"):
            path = get_binary_path("145.0.0.0")
            assert path.as_posix().endswith("chromium-145.0.0.0/Chromium.app/Contents/MacOS/Chromium")

    def test_windows(self):
        with patch("cloakbrowser.config.platform.system", return_value="Windows"):
            path = get_binary_path("145.0.0.0")
            assert path.as_posix().endswith("chromium-145.0.0.0/chrome.exe")


# ---------------------------------------------------------------------------
# Archive extension and name
# ---------------------------------------------------------------------------


class TestArchive:
    def test_ext_windows(self):
        with patch("cloakbrowser.config.platform.system", return_value="Windows"):
            assert get_archive_ext() == ".zip"

    def test_ext_unix(self):
        for system in ("Linux", "Darwin"):
            with patch("cloakbrowser.config.platform.system", return_value=system):
                assert get_archive_ext() == ".tar.gz"

    def test_archive_name(self):
        tag = get_platform_tag()
        ext = get_archive_ext()
        assert get_archive_name() == f"cloakbrowser-{tag}{ext}"

    def test_archive_name_custom_tag(self):
        name = get_archive_name("linux-x64")
        assert "cloakbrowser-linux-x64" in name


# ---------------------------------------------------------------------------
# Download URLs
# ---------------------------------------------------------------------------


class TestFallbackUrl:
    def test_github_releases_format(self):
        url = get_fallback_download_url("145.0.0.0")
        assert "github.com/CloakHQ/cloakbrowser/releases/download" in url
        assert "chromium-v145.0.0.0" in url

    def test_default_version(self):
        url = get_fallback_download_url()
        version = get_chromium_version()
        assert f"chromium-v{version}" in url


# ---------------------------------------------------------------------------
# Cache directory
# ---------------------------------------------------------------------------


class TestCacheDir:
    def test_default_path(self):
        with patch.dict(os.environ, {}, clear=False):
            # Remove override if set
            env = os.environ.copy()
            env.pop("CLOAKBROWSER_CACHE_DIR", None)
            with patch.dict(os.environ, env, clear=True):
                path = get_cache_dir()
                assert str(path).endswith(".cloakbrowser")

    def test_env_override(self, tmp_path):
        with patch.dict(os.environ, {"CLOAKBROWSER_CACHE_DIR": str(tmp_path)}):
            assert get_cache_dir() == tmp_path


# ---------------------------------------------------------------------------
# Platform tag
# ---------------------------------------------------------------------------


class TestPlatformTag:
    def test_unsupported_raises(self):
        with patch("cloakbrowser.config.platform.system", return_value="FreeBSD"):
            with patch("cloakbrowser.config.platform.machine", return_value="x86_64"):
                with pytest.raises(RuntimeError, match="Unsupported platform"):
                    get_platform_tag()


# ---------------------------------------------------------------------------
# Stealth args
# ---------------------------------------------------------------------------


class TestStealthArgs:
    def test_seed_uniqueness(self):
        """Two calls should produce different fingerprint seeds."""
        args1 = get_default_stealth_args()
        args2 = get_default_stealth_args()
        seed1 = [a for a in args1 if a.startswith("--fingerprint=")][0]
        seed2 = [a for a in args2 if a.startswith("--fingerprint=")][0]
        # Seeds are random 10000-99999 — extremely unlikely to collide
        assert seed1 != seed2

    def test_macos_profile(self):
        with patch("cloakbrowser.config.platform.system", return_value="Darwin"):
            args = get_default_stealth_args()
            assert "--fingerprint-platform=macos" in args
            # GPU flags removed — binary auto-generates from seed + platform
            assert not any("fingerprint-gpu-vendor" in a for a in args)
            assert not any("fingerprint-gpu-renderer" in a for a in args)

    def test_linux_windows_profile(self):
        with patch("cloakbrowser.config.platform.system", return_value="Linux"):
            args = get_default_stealth_args()
            assert "--fingerprint-platform=windows" in args
            # GPU flags removed — binary auto-generates from seed + platform
            assert not any("fingerprint-gpu-vendor" in a for a in args)
            assert not any("fingerprint-gpu-renderer" in a for a in args)
