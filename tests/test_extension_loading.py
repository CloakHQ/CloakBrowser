import os
from unittest.mock import MagicMock, patch

from cloakbrowser import launch


@patch("cloakbrowser.browser.ensure_binary")
@patch("cloakbrowser.browser._import_sync_playwright")
def test_extension_loading(mock_playwright_import, mock_ensure_binary):
    mock_ensure_binary.return_value = "/fake/chrome"

    mock_browser = MagicMock()

    mock_pw = MagicMock()
    mock_pw.chromium.launch.return_value = mock_browser

    mock_pw_manager = MagicMock()
    mock_pw_manager.return_value.start.return_value = mock_pw

    mock_playwright_import.return_value = mock_pw_manager

    launch(extension_paths=["./ext"])

    mock_pw.chromium.launch.assert_called_once()

    launch_call = mock_pw.chromium.launch.call_args

    args = launch_call.kwargs["args"]

    abs_path = os.path.abspath("./ext")

    assert f"--load-extension={abs_path}" in args
    assert f"--disable-extensions-except={abs_path}" in args
