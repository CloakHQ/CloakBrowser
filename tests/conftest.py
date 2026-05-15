"""Shared test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure host-level wrapper env vars don't leak into tests."""
    monkeypatch.delenv("CLOAKBROWSER_BACKEND", raising=False)
    monkeypatch.delenv("CLOAKBROWSER_GPU_ACCEL", raising=False)
