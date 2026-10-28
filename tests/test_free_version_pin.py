"""A free key must never pin a version (server force-serves latest; a pinned
manifest would fail checksum). Paid keys keep pinning."""
from unittest import mock

import cloakbrowser.download as dl
from cloakbrowser.license import LicenseInfo


def _run(monkeypatch, plan):
    monkeypatch.delenv("CLOAKBROWSER_DOWNLOAD_URL", raising=False)
    monkeypatch.setattr(dl, "get_local_binary_override", lambda: None)
    monkeypatch.setattr(dl, "normalize_requested_version", lambda v: v)
    captured = {}

    def fake_pro(key, requested_version=None, plan=None, release_channel=None):
        captured["rv"] = requested_version
        captured["plan"] = plan
        captured["release_channel"] = release_channel
        return "/tmp/chrome"

    monkeypatch.setattr(dl, "_ensure_pro_binary", fake_pro)
    with mock.patch("cloakbrowser.license.resolve_license_key", return_value="cb_x"), \
         mock.patch(
             "cloakbrowser.license.validate_license",
             return_value=LicenseInfo(valid=True, plan=plan, expires=None),
         ):
        dl.ensure_binary(browser_version="150.0.7871.114.3")
    return captured


def test_free_key_drops_version_pin(monkeypatch):
    c = _run(monkeypatch, "free")
    assert c["plan"] == "free"
    assert c["rv"] is None                      # pin dropped -> serves latest


def test_paid_key_keeps_version_pin(monkeypatch):
    c = _run(monkeypatch, "business")
    assert c["plan"] == "business"
    assert c["rv"] == "150.0.7871.114.3"        # paid keeps the pin
