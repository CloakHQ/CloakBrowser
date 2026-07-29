"""Unit tests for config.py — platform detection, paths, stealth args."""

import os
from unittest.mock import patch

import pytest

from cloakbrowser.config import (
    binary_supports_dual_stack_webrtc,
    binary_supports_headless_no_viewport,
    binary_supports_maximized_window,
    get_archive_ext,
    get_archive_name,
    get_binary_path,
    get_cache_dir,
    get_chromium_version,
    get_default_stealth_args,
    get_fallback_download_url,
    get_platform_tag,
    normalize_requested_version,
)


# ---------------------------------------------------------------------------
# Platform-specific binary paths
# ---------------------------------------------------------------------------


class TestGetBinaryPath:
    def test_linux(self):
        with patch("cloakbrowser.config.platform.system", return_value="Linux"):
            path = get_binary_path("145.0.0.0")
            assert str(path).endswith("chromium-145.0.0.0/chrome")

    def test_darwin(self):
        with patch("cloakbrowser.config.platform.system", return_value="Darwin"):
            path = get_binary_path("145.0.0.0")
            assert str(path).endswith(
                "chromium-145.0.0.0/Chromium.app/Contents/MacOS/Chromium"
            )

    def test_windows(self):
        with patch("cloakbrowser.config.platform.system", return_value="Windows"):
            path = get_binary_path("145.0.0.0")
            assert str(path).endswith("chromium-145.0.0.0/chrome.exe")


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
# Version pin
# ---------------------------------------------------------------------------


class TestVersionPin:
    def test_explicit_wins_over_env(self):
        with patch.dict(os.environ, {"CLOAKBROWSER_VERSION": "146.0.0.0"}):
            assert normalize_requested_version("148.0.7778.215.2") == "148.0.7778.215.2"

    def test_reads_env(self):
        with patch.dict(os.environ, {"CLOAKBROWSER_VERSION": "148.0.7778.215.2"}):
            assert normalize_requested_version() == "148.0.7778.215.2"

    def test_rejects_path_traversal(self):
        with pytest.raises(ValueError, match="Invalid browser version pin"):
            normalize_requested_version("../../148.0.7778.215.2")

    def test_rejects_non_ascii_digits(self):
        # Parity with JS (ASCII-only \d). Unicode digits must be rejected so the
        # same input behaves identically across Python / JS / .NET.
        with pytest.raises(ValueError, match="Invalid browser version pin"):
            normalize_requested_version("١٤٦.0.7680.177")


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


# ---------------------------------------------------------------------------
# Headless no_viewport version gate
# ---------------------------------------------------------------------------


class TestHeadlessNoViewportGate:
    """binary_supports_headless_no_viewport() — parity-critical: JS and .NET mirror this.

    Threshold is HEADLESS_NO_VIEWPORT_MIN_VERSION (an unshipped version), so the
    resolved-version path is a no-op today; the declared-version path is what these
    tests pin.
    """

    def test_declared_below_threshold_off(self):
        # Current live Pro version — one build below the threshold => feature OFF.
        assert binary_supports_headless_no_viewport(browser_version="148.0.7778.215.3") is False

    def test_declared_at_threshold_on(self):
        assert binary_supports_headless_no_viewport(browser_version="148.0.7778.215.4") is True

    def test_declared_above_threshold_on(self):
        assert binary_supports_headless_no_viewport(browser_version="149.0.0.0") is True

    def test_declared_wins_over_local_override(self):
        # An explicit version asserts the binary even under CLOAKBROWSER_BINARY_PATH.
        with patch.dict(os.environ, {"CLOAKBROWSER_BINARY_PATH": "/fake/chrome"}):
            assert binary_supports_headless_no_viewport(browser_version="149.0.0.0") is True

    def test_local_override_without_declared_off(self):
        # Unknown-version override => stay on the safe fixed-viewport path.
        with patch.dict(os.environ, {"CLOAKBROWSER_BINARY_PATH": "/fake/chrome"}):
            assert binary_supports_headless_no_viewport() is False

    def test_resolved_free_version_off(self):
        # No key, no override, no declared version => free version, below threshold.
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CLOAKBROWSER_BINARY_PATH", None)
            os.environ.pop("CLOAKBROWSER_LICENSE_KEY", None)
            os.environ.pop("CLOAKBROWSER_VERSION", None)
            assert binary_supports_headless_no_viewport() is False


class TestMaximizedWindowGate:
    """binary_supports_maximized_window() — parity-critical: JS and .NET mirror this.

    Shares HEADLESS_NO_VIEWPORT_MIN_VERSION today, so it tracks the same threshold
    as the no_viewport gate: below it, auto --start-maximized would make headless
    report outerWidth < innerWidth (a bot tell), so the flag must stay off.
    """

    def test_declared_below_threshold_off(self):
        assert binary_supports_maximized_window(browser_version="148.0.7778.215.3") is False

    def test_declared_at_threshold_on(self):
        assert binary_supports_maximized_window(browser_version="148.0.7778.215.4") is True

    def test_declared_above_threshold_on(self):
        assert binary_supports_maximized_window(browser_version="149.0.0.0") is True

    def test_local_override_without_declared_off(self):
        with patch.dict(os.environ, {"CLOAKBROWSER_BINARY_PATH": "/fake/chrome"}):
            assert binary_supports_maximized_window() is False


# ---------------------------------------------------------------------------
# Dual-stack WebRTC exit IP version gate
# ---------------------------------------------------------------------------


class TestDualStackWebrtcGate:
    """binary_supports_dual_stack_webrtc() — parity-critical: JS and .NET mirror this.

    Below the floor the flag takes one address only, so a wrong True here would put
    a two-address value on a binary that reads it as a single opaque address.
    """

    def test_declared_below_threshold_off(self):
        # Current live Linux stable — one build below the floor => single address.
        assert binary_supports_dual_stack_webrtc(browser_version="150.0.7871.114.4") is False

    def test_declared_well_below_threshold_off(self):
        assert binary_supports_dual_stack_webrtc(browser_version="146.0.7680.177.5") is False

    def test_declared_at_threshold_on(self):
        assert binary_supports_dual_stack_webrtc(browser_version="150.0.7871.114.5") is True

    def test_declared_above_threshold_on(self):
        assert binary_supports_dual_stack_webrtc(browser_version="151.0.0.0") is True

    def test_declared_wins_over_local_override(self):
        with patch.dict(os.environ, {"CLOAKBROWSER_BINARY_PATH": "/fake/chrome"}):
            assert binary_supports_dual_stack_webrtc(browser_version="150.0.7871.114.5") is True

    def test_local_override_without_declared_off(self):
        # Unknown-version override => safe single-address path.
        with patch.dict(os.environ, {"CLOAKBROWSER_BINARY_PATH": "/fake/chrome"}):
            assert binary_supports_dual_stack_webrtc() is False

    def test_malformed_version_off(self):
        assert binary_supports_dual_stack_webrtc(browser_version="not-a-version") is False


class TestFormatWebrtcExitIps:
    """format_webrtc_exit_ips() — what actually reaches --fingerprint-webrtc-ip."""

    def test_both_families(self):
        from cloakbrowser.geoip import format_webrtc_exit_ips

        assert format_webrtc_exit_ips("1.2.3.4", "2001:db8::1") == "1.2.3.4,2001:db8::1"

    def test_v4_only_unchanged(self):
        from cloakbrowser.geoip import format_webrtc_exit_ips

        assert format_webrtc_exit_ips("1.2.3.4", None) == "1.2.3.4"

    def test_neither_is_none(self):
        from cloakbrowser.geoip import format_webrtc_exit_ips

        assert format_webrtc_exit_ips(None, None) is None
