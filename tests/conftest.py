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
def _clear_gpu_accel_env(monkeypatch):
    """A host-level CLOAKBROWSER_GPU_ACCEL must not leak into build_args tests."""
    monkeypatch.delenv("CLOAKBROWSER_GPU_ACCEL", raising=False)
