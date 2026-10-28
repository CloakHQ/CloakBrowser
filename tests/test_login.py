"""Tests for `cloakbrowser login` / `logout` (key activation, no network/binary)."""
import argparse
from unittest import mock

import pytest

import cloakbrowser.__main__ as m
from cloakbrowser.license import LicenseInfo


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CLOAKBROWSER_CACHE_DIR", str(tmp_path))
    return tmp_path


def _validate(**kw):
    return mock.patch("cloakbrowser.license.validate_license", **kw)


def test_login_saves_valid_free_key(cache_dir):
    with _validate(return_value=LicenseInfo(valid=True, plan="free", expires=None)):
        m.cmd_login(argparse.Namespace(key="cb_free"))
    key_file = cache_dir / "license.key"
    assert key_file.read_text().strip() == "cb_free"
    assert oct(key_file.stat().st_mode)[-3:] == "600"


def test_login_saves_valid_paid_key(cache_dir):
    with _validate(return_value=LicenseInfo(valid=True, plan="business", expires=None)):
        m.cmd_login(argparse.Namespace(key="cb_biz"))
    assert (cache_dir / "license.key").read_text().strip() == "cb_biz"


def test_login_rejects_invalid_key(cache_dir):
    with _validate(return_value=LicenseInfo(valid=False, plan="free", expires=None)):
        with pytest.raises(SystemExit) as e:
            m.cmd_login(argparse.Namespace(key="cb_bad"))
    assert e.value.code == 1
    assert not (cache_dir / "license.key").exists()


def test_login_invalid_key_does_not_overwrite(cache_dir):
    with _validate(return_value=LicenseInfo(valid=True, plan="free", expires=None)):
        m.cmd_login(argparse.Namespace(key="cb_good"))
    with _validate(return_value=LicenseInfo(valid=False, plan="free", expires=None)):
        with pytest.raises(SystemExit):
            m.cmd_login(argparse.Namespace(key="cb_bad"))
    assert (cache_dir / "license.key").read_text().strip() == "cb_good"


def test_login_server_unreachable_refuses(cache_dir):
    with _validate(return_value=None):
        with pytest.raises(SystemExit) as e:
            m.cmd_login(argparse.Namespace(key="cb_x"))
    assert e.value.code == 1
    assert not (cache_dir / "license.key").exists()


def test_login_no_key_non_interactive_exits(cache_dir):
    with mock.patch("sys.stdin.isatty", return_value=False):
        with pytest.raises(SystemExit) as e:
            m.cmd_login(argparse.Namespace(key=None))
    assert e.value.code == 2


def test_logout_removes_key(cache_dir):
    with _validate(return_value=LicenseInfo(valid=True, plan="free", expires=None)):
        m.cmd_login(argparse.Namespace(key="cb_free"))
    assert (cache_dir / "license.key").exists()
    m.cmd_logout(argparse.Namespace())
    assert not (cache_dir / "license.key").exists()


def test_logout_idempotent(cache_dir):
    # No saved key -> no crash, no error exit.
    m.cmd_logout(argparse.Namespace())
