"""Shared pytest fixtures."""

import pytest


@pytest.fixture(autouse=True)
def isolated_cache_dir(tmp_path_factory, monkeypatch):
    """Keep the suite away from the developer's real ``~/.cloakbrowser``.

    A ``license.key`` (or a cached Pro version marker) in the real cache dir
    resolves the machine as Pro, which flips version-gated defaults such as the
    headless ``no_viewport`` shim and inline proxy auth — tests then assert
    against whatever the developer happens to have installed. ``monkeypatch``
    means a test setting its own ``CLOAKBROWSER_CACHE_DIR`` still wins.
    """
    monkeypatch.setenv(
        "CLOAKBROWSER_CACHE_DIR",
        str(tmp_path_factory.mktemp("cloakbrowser-cache")),
    )


@pytest.fixture(autouse=True)
def no_geoip_egress(request, monkeypatch):
    """Keep GeoIP off the network for the whole suite.

    ``geoip`` defaults to True, so any test that launches without mocking the
    resolver would hit the IP echo services and, on a cold cache dir, block on
    the ~70 MB GeoLite2 download.  Both seams are stubbed rather than the
    ``geoip`` param itself, so resolution still runs and returns "nothing
    resolved" — the same shape a firewalled environment produces.

    Tests that patch ``resolve_proxy_geo_with_ip`` or ``_resolve_exit_ip``
    themselves still win: their patch is applied inside this one.  Tests that
    exercise these two seams *directly* must opt out with ``@pytest.mark.
    real_geoip`` — stubbing them out would make the test vacuous.
    """
    if request.node.get_closest_marker("real_geoip"):
        return
    monkeypatch.setattr(
        "cloakbrowser.geoip._resolve_exit_ip", lambda *a, **kw: None
    )
    monkeypatch.setattr(
        "cloakbrowser.geoip._ensure_geoip_db", lambda *a, **kw: None
    )
