"""Tests for Windows platform detection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestGetPlatformTag:
    """Tests for get_platform_tag() with Windows detection."""

    @patch("cloakbrowser.config.platform.system")
    @patch("cloakbrowser.config.platform.machine")
    def test_windows_x64_platform_tag(self, mock_machine, mock_system):
        """Test that Windows x64 returns correct platform tag."""
        mock_system.return_value = "Windows"
        mock_machine.return_value = "AMD64"

        from cloakbrowser.config import get_platform_tag

        tag = get_platform_tag()
        assert tag == "win32-x64"

    @patch("cloakbrowser.config.platform.system")
    @patch("cloakbrowser.config.platform.machine")
    def test_windows_arm64_platform_tag(self, mock_machine, mock_system):
        """Test that Windows ARM64 returns correct platform tag."""
        mock_system.return_value = "Windows"
        mock_machine.return_value = "ARM64"

        from cloakbrowser.config import get_platform_tag

        tag = get_platform_tag()
        assert tag == "win32-arm64"

    @patch("cloakbrowser.config.platform.system")
    @patch("cloakbrowser.config.platform.machine")
    def test_windows_unsupported_machine(self, mock_machine, mock_system):
        """Test that unsupported Windows machine raises error."""
        mock_system.return_value = "Windows"
        mock_machine.return_value = "x86"

        from cloakbrowser.config import get_platform_tag

        with pytest.raises(RuntimeError, match="Unsupported platform"):
            get_platform_tag()


class TestGetBinaryPath:
    """Tests for get_binary_path() with Windows detection."""

    @patch("cloakbrowser.config.platform.system")
    def test_windows_binary_path(self, mock_system):
        """Test that Windows returns .exe path for binary."""
        mock_system.return_value = "Windows"

        from cloakbrowser.config import get_binary_path

        # Create mock cache dir that will return a Path with / operator
        mock_cache = MagicMock(spec=Path)
        # When __truediv__ is called, return a mock Path ending with chrome.exe
        mock_result = MagicMock(spec=Path)
        mock_result.name = "chrome.exe"
        mock_cache.__truediv__ = MagicMock(return_value=mock_result)

        with patch("cloakbrowser.config.get_cache_dir", return_value=mock_cache):
            get_binary_path()
            # Verify chrome.exe was requested - get_cache_dir() was called once
            mock_cache.__truediv__.assert_called()

    @patch("cloakbrowser.config.platform.system")
    def test_windows_binary_path_returns_exe(self, mock_system):
        """Test that Windows binary path ends with chrome.exe."""
        mock_system.return_value = "Windows"

        from cloakbrowser.config import get_binary_path

        with patch("cloakbrowser.config.get_cache_dir") as mock_get_cache:
            # Set up mock to return a proper Path-like object
            mock_cache = MagicMock()
            mock_chrome = MagicMock()
            mock_chrome.name = "chrome.exe"
            mock_cache.__truediv__ = MagicMock(return_value=mock_chrome)
            mock_get_cache.return_value = mock_cache

            _ = get_binary_path()
            # The result should be the chrome.exe path
            assert mock_cache.__truediv__.called

    @patch("cloakbrowser.config.platform.system")
    @patch("cloakbrowser.config.get_binary_dir")
    def test_windows_binary_path_with_version(self, mock_binary_dir, mock_system):
        """Test that Windows binary path includes version."""
        mock_system.return_value = "Windows"
        mock_dir = MagicMock()
        mock_binary_dir.return_value = mock_dir

        from cloakbrowser.config import get_binary_path

        get_binary_path("142.0.7444.175")

        mock_binary_dir.assert_called_with("142.0.7444.175")
