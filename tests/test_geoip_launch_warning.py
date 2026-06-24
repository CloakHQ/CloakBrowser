"""Tests for geoip launch-time proxy warnings."""

import logging
from unittest.mock import MagicMock, patch

from cloakbrowser import launch


def _mock_sync_playwright():
    browser = MagicMock()
    pw = MagicMock()
    pw.chromium.launch.return_value = browser
    pw_cm = MagicMock()
    pw_cm.start.return_value = pw
    return pw_cm


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.maybe_resolve_geoip", return_value=(None, None, None))
@patch("cloakbrowser.browser._import_sync_playwright")
def test_warns_when_geoip_true_and_no_proxy(mock_import, _mock_geoip, _mock_bin, caplog):
    caplog.set_level(logging.WARNING, logger="cloakbrowser")
    pw_cm = _mock_sync_playwright()
    mock_import.return_value = MagicMock(return_value=pw_cm)

    launch(geoip=True)

    assert "timezone/locale will default" in caplog.text


@patch("cloakbrowser.browser.ensure_binary", return_value="/fake/chrome")
@patch("cloakbrowser.browser.maybe_resolve_geoip", return_value=(None, None, None))
@patch("cloakbrowser.browser._import_sync_playwright")
def test_does_not_warn_when_proxy_set(mock_import, _mock_geoip, _mock_bin, caplog):
    caplog.set_level(logging.WARNING, logger="cloakbrowser")
    pw_cm = _mock_sync_playwright()
    mock_import.return_value = MagicMock(return_value=pw_cm)

    launch(geoip=True, proxy="http://example.com:8080")

    assert "timezone/locale will default" not in caplog.text
