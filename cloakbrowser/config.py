"""Stealth configuration and platform detection for cloakbrowser."""

from __future__ import annotations

import os
import platform
import random
from pathlib import Path

from ._version import __version__

# ---------------------------------------------------------------------------
# Chromium version shipped with this release
# ---------------------------------------------------------------------------
CHROMIUM_VERSION = "142.0.7444.175"

# ---------------------------------------------------------------------------
# Default stealth arguments passed to the patched Chromium binary.
# These activate source-level fingerprint patches compiled into the binary.
# ---------------------------------------------------------------------------
def get_default_stealth_args() -> list[str]:
    """Build stealth args with a random fingerprint seed per launch."""
    seed = random.randint(10000, 99999)
    return [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        f"--fingerprint={seed}",
        "--fingerprint-platform=windows",
        "--fingerprint-hardware-concurrency=8",
        "--fingerprint-gpu-vendor=NVIDIA Corporation",
        "--fingerprint-gpu-renderer=NVIDIA GeForce RTX 3070",
    ]

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------
SUPPORTED_PLATFORMS: dict[tuple[str, str], str] = {
    ("Linux", "x86_64"): "linux-x64",
    ("Linux", "aarch64"): "linux-arm64",
    ("Darwin", "arm64"): "darwin-arm64",
    ("Darwin", "x86_64"): "darwin-x64",
}


def get_platform_tag() -> str:
    """Return the platform tag for binary download (e.g. 'linux-x64', 'darwin-arm64')."""
    system = platform.system()
    machine = platform.machine()
    tag = SUPPORTED_PLATFORMS.get((system, machine))
    if tag is None:
        raise RuntimeError(
            f"Unsupported platform: {system} {machine}. "
            f"Supported: {', '.join(f'{s}-{m}' for (s, m) in SUPPORTED_PLATFORMS)}"
        )
    return tag


# ---------------------------------------------------------------------------
# Binary cache paths
# ---------------------------------------------------------------------------
def get_cache_dir() -> Path:
    """Return the cache directory for downloaded binaries.

    Override with CLOAKBROWSER_CACHE_DIR env var.
    Default: ~/.cloakbrowser/
    """
    custom = os.environ.get("CLOAKBROWSER_CACHE_DIR")
    if custom:
        return Path(custom)
    return Path.home() / ".cloakbrowser"


def get_binary_dir() -> Path:
    """Return the directory for the current Chromium version binary."""
    return get_cache_dir() / f"chromium-{CHROMIUM_VERSION}"


def get_binary_path() -> Path:
    """Return the expected path to the chrome executable."""
    platform_tag = get_platform_tag()
    binary_dir = get_binary_dir()

    if platform.system() == "Darwin":
        # macOS: Chromium.app bundle
        return binary_dir / "Chromium.app" / "Contents" / "MacOS" / "Chromium"
    else:
        # Linux: flat binary
        return binary_dir / "chrome"


# ---------------------------------------------------------------------------
# Download URL
# ---------------------------------------------------------------------------
DOWNLOAD_BASE_URL = os.environ.get(
    "CLOAKBROWSER_DOWNLOAD_URL",
    "https://github.com/CloakHQ/chromium-stealth-builds/releases/download",
)


def get_download_url() -> str:
    """Return the full download URL for the current platform's binary archive."""
    tag = get_platform_tag()
    return f"{DOWNLOAD_BASE_URL}/v{CHROMIUM_VERSION}/cloakbrowser-{tag}.tar.gz"


# ---------------------------------------------------------------------------
# Local binary override (skip download, use your own build)
# ---------------------------------------------------------------------------
def get_local_binary_override() -> str | None:
    """Check if user has set a local binary path via env var.

    Set CLOAKBROWSER_BINARY_PATH to use a locally built Chromium instead of downloading.
    """
    return os.environ.get("CLOAKBROWSER_BINARY_PATH")
