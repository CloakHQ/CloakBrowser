"""Unit tests for the cloakbrowser CLI."""

from unittest.mock import patch

from cloakbrowser.__main__ import cmd_doctor


def test_doctor_prints_environment_without_downloading(capsys):
    with patch("cloakbrowser.download.ensure_binary") as mock_ensure:
        cmd_doctor(None)

    mock_ensure.assert_not_called()
    out = capsys.readouterr().out
    assert "CloakBrowser doctor" in out
    assert "Python:" in out
    assert "Platform:" in out
    assert "Modules:" in out
