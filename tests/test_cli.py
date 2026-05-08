"""Unit tests for the cloakbrowser CLI."""

from argparse import Namespace
from unittest.mock import MagicMock, patch

import pytest

from cloakbrowser import __main__ as cli


def test_setup_logging_suppresses_httpx_logs():
    with patch("cloakbrowser.__main__.logging.basicConfig") as basic_config:
        cli._setup_logging()

    basic_config.assert_called_once()
    assert cli.logging.getLogger("httpx").level == cli.logging.WARNING


def test_package_lazy_human_exports():
    import cloakbrowser
    from cloakbrowser.human.config import HumanConfig, resolve_config

    assert cloakbrowser.HumanConfig is HumanConfig
    assert cloakbrowser.resolve_human_config is resolve_config


def test_package_getattr_unknown_raises_attribute_error():
    import cloakbrowser

    with pytest.raises(AttributeError, match="does_not_exist"):
        cloakbrowser.__getattr__("does_not_exist")


def test_cmd_install_prints_binary_path(capsys):
    with patch("cloakbrowser.download.ensure_binary", return_value="/tmp/chrome"):
        cli.cmd_install(Namespace())

    assert capsys.readouterr().out == "/tmp/chrome\n"


def test_cmd_info_prints_binary_info_and_override(capsys):
    info = {
        "version": "1.2.3.4",
        "platform": "linux-x64",
        "binary_path": "/tmp/chrome",
        "installed": True,
        "cache_dir": "/tmp/cache",
    }
    with patch("cloakbrowser.download.binary_info", return_value=info):
        with patch("cloakbrowser.config.get_local_binary_override", return_value="/custom/chrome"):
            cli.cmd_info(Namespace())

    out = capsys.readouterr().out
    assert "Version:   1.2.3.4" in out
    assert "Override:  /custom/chrome (CLOAKBROWSER_BINARY_PATH)" in out


def test_cmd_info_omits_override_when_unset(capsys):
    info = {
        "version": "1.2.3.4",
        "platform": "linux-x64",
        "binary_path": "/tmp/chrome",
        "installed": False,
        "cache_dir": "/tmp/cache",
    }
    with patch("cloakbrowser.download.binary_info", return_value=info):
        with patch("cloakbrowser.config.get_local_binary_override", return_value=None):
            cli.cmd_info(Namespace())

    assert "Override:" not in capsys.readouterr().out


def test_cmd_update_reports_new_version(capsys):
    with patch("cloakbrowser.download.check_for_update", return_value="2.0.0.0"):
        cli.cmd_update(Namespace())

    assert capsys.readouterr().out == "Updated to Chromium 2.0.0.0\n"


def test_cmd_update_reports_up_to_date(capsys):
    with patch("cloakbrowser.download.check_for_update", return_value=None):
        cli.cmd_update(Namespace())

    assert capsys.readouterr().out == "Already up to date.\n"


def test_cmd_clear_cache_no_cache(capsys, tmp_path):
    with patch("cloakbrowser.config.get_cache_dir", return_value=tmp_path / "missing"):
        with patch("cloakbrowser.download.clear_cache") as clear_cache:
            cli.cmd_clear_cache(Namespace())

    clear_cache.assert_not_called()
    assert capsys.readouterr().out == "No cache to clear.\n"


def test_cmd_clear_cache_existing_cache(capsys, tmp_path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    with patch("cloakbrowser.config.get_cache_dir", return_value=cache_dir):
        with patch("cloakbrowser.download.clear_cache") as clear_cache:
            cli.cmd_clear_cache(Namespace())

    clear_cache.assert_called_once()
    assert capsys.readouterr().out == "Cache cleared.\n"


def test_main_without_command_prints_help(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["cloakbrowser"])

    with pytest.raises(SystemExit) as exc:
        cli.main()

    assert exc.value.code == 2
    assert "Manage the CloakBrowser stealth Chromium binary." in capsys.readouterr().out


def test_main_dispatches_command(monkeypatch):
    monkeypatch.setattr("sys.argv", ["cloakbrowser", "install"])
    command = MagicMock()
    with patch("cloakbrowser.__main__._setup_logging"):
        with patch.dict(cli.main.__globals__, {"cmd_install": command}):
            cli.main()

    command.assert_called_once()


def test_main_keyboard_interrupt_exits_130(monkeypatch):
    monkeypatch.setattr("sys.argv", ["cloakbrowser", "install"])
    with patch("cloakbrowser.__main__._setup_logging"):
        with patch.dict(cli.main.__globals__, {"cmd_install": MagicMock(side_effect=KeyboardInterrupt)}):
            with pytest.raises(SystemExit) as exc:
                cli.main()

    assert exc.value.code == 130


def test_main_command_error_exits_1(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["cloakbrowser", "install"])
    with patch("cloakbrowser.__main__._setup_logging"):
        with patch.dict(cli.main.__globals__, {"cmd_install": MagicMock(side_effect=RuntimeError("boom"))}):
            with pytest.raises(SystemExit) as exc:
                cli.main()

    assert exc.value.code == 1
    assert "Error: boom" in capsys.readouterr().err
