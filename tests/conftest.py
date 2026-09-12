"""Shared pytest fixtures."""

import os
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


def pytest_collection_modifyitems(config, items):
    """Skip tests marked 'slow' by default unless CLOAKBROWSER_RUN_SLOW=1.

    Many stealth tests hit live detection services and are slow/flaky in local
    environments (network/proxy differences). Running them locally is opt-in
    via the CLOAKBROWSER_RUN_SLOW env var so the default developer run stays
    fast and deterministic.
    """
    run_slow = os.getenv("CLOAKBROWSER_RUN_SLOW") == "1"
    if run_slow:
        return
    skip_slow = pytest.mark.skip(reason="skipping slow live tests (set CLOAKBROWSER_RUN_SLOW=1 to run)")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)
