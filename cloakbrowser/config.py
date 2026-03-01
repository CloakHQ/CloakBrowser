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
CHROMIUM_VERSION = "145.0.7632.109"

# ---------------------------------------------------------------------------
# Default stealth arguments passed to the patched Chromium binary.
# These activate source-level fingerprint patches compiled into the binary.
# ---------------------------------------------------------------------------
def get_default_stealth_args() -> list[str]:
    """Build stealth args with a random fingerprint seed per launch.

    On macOS, skips platform/GPU spoofing — runs as a native Mac browser.
    Spoofing Windows on Mac creates detectable mismatches (fonts, GPU, etc.).
    """
    seed = random.randint(10000, 99999)
    system = platform.system()

    base = [
        "--no-sandbox",
        "--disable-blink-features=AutomationControlled",
        f"--fingerprint={seed}",
    ]

    if system == "Darwin":
        # Tell the fingerprint patches we're on macOS so GPU/UA match natively
        return base + [
            "--fingerprint-platform=macos",
        ]

    # Linux: spoof as Windows
    return base + [
        "--fingerprint-platform=windows",
        "--fingerprint-hardware-concurrency=8",
        "--fingerprint-device-memory=8",
        "--fingerprint-gpu-vendor=NVIDIA Corporation",
        "--fingerprint-gpu-renderer=NVIDIA GeForce RTX 3070",
        "--fingerprint-taskbar-height=40",
        "--fingerprint-screen-width=1920",
        "--fingerprint-screen-height=1080",
        "--window-size=1920,1080",
    ]


# ---------------------------------------------------------------------------
# Default viewport — realistic maximized Chrome on 1080p Windows
# screen=1920x1080, availHeight=1040 (minus 40px taskbar),
# innerHeight=955 (minus ~85px Chrome UI: tabs + address bar + bookmarks)
# ---------------------------------------------------------------------------
DEFAULT_VIEWPORT = {"width": 1920, "height": 955}

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------
SUPPORTED_PLATFORMS: dict[tuple[str, str], str] = {
    ("Linux", "x86_64"): "linux-x64",
    ("Linux", "aarch64"): "linux-arm64",
    ("Darwin", "arm64"): "darwin-arm64",
    ("Darwin", "x86_64"): "darwin-x64",
}

# Platforms with pre-built binaries available for download.
# Update this set as new platform builds are released.
AVAILABLE_PLATFORMS: set[str] = {"linux-x64", "darwin-arm64", "darwin-x64"}


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


def get_binary_dir(version: str | None = None) -> Path:
    """Return the directory for a Chromium version binary."""
    v = version or CHROMIUM_VERSION
    return get_cache_dir() / f"chromium-{v}"


def get_binary_path(version: str | None = None) -> Path:
    """Return the expected path to the chrome executable."""
    binary_dir = get_binary_dir(version)

    if platform.system() == "Darwin":
        # macOS: Chromium.app bundle
        return binary_dir / "Chromium.app" / "Contents" / "MacOS" / "Chromium"
    else:
        # Linux: flat binary
        return binary_dir / "chrome"


def check_platform_available() -> None:
    """Raise a clear error if no pre-built binary exists for this platform.

    Skipped when CLOAKBROWSER_BINARY_PATH is set (user has their own build).
    """
    if get_local_binary_override():
        return

    tag = get_platform_tag()  # raises if platform unsupported entirely
    if tag not in AVAILABLE_PLATFORMS:
        available = ", ".join(sorted(AVAILABLE_PLATFORMS))
        import sys
        sys.exit(
            f"\n\033[1mCloakBrowser\033[0m — Pre-built binaries are currently only available for: {available}.\n"
            f"Windows builds are coming soon.\n\n"
            f"To use CloakBrowser now, run in Docker (see README) or set CLOAKBROWSER_BINARY_PATH."
        )


def get_effective_version() -> str:
    """Return the best available version: auto-updated if available, else hardcoded.

    Reads the latest_version marker file from the cache directory.
    Returns CHROMIUM_VERSION if no update has been downloaded.
    """
    marker = get_cache_dir() / "latest_version"
    if marker.exists():
        try:
            version = marker.read_text().strip()
            if version and _version_newer(version, CHROMIUM_VERSION):
                # Verify the binary actually exists
                binary = get_binary_path(version)
                if binary.exists():
                    return version
        except (ValueError, OSError):
            pass
    return CHROMIUM_VERSION


def _version_tuple(v: str) -> tuple[int, ...]:
    """Parse '145.0.7718.0' into (145, 0, 7718, 0) for comparison."""
    return tuple(int(x) for x in v.split("."))


def _version_newer(a: str, b: str) -> bool:
    """Return True if version a is strictly newer than version b."""
    return _version_tuple(a) > _version_tuple(b)


# ---------------------------------------------------------------------------
# Download URL
# ---------------------------------------------------------------------------
DOWNLOAD_BASE_URL = os.environ.get(
    "CLOAKBROWSER_DOWNLOAD_URL",
    "https://cloakbrowser.dev",
)

GITHUB_API_URL = "https://api.github.com/repos/CloakHQ/cloakbrowser/releases"

GITHUB_DOWNLOAD_BASE_URL = (
    "https://github.com/CloakHQ/cloakbrowser/releases/download"
)


def get_download_url(version: str | None = None) -> str:
    """Return the full download URL for the current platform's binary archive."""
    v = version or CHROMIUM_VERSION
    tag = get_platform_tag()
    return f"{DOWNLOAD_BASE_URL}/chromium-v{v}/cloakbrowser-{tag}.tar.gz"


def get_fallback_download_url(version: str | None = None) -> str:
    """Return the GitHub Releases fallback URL for the binary archive."""
    v = version or CHROMIUM_VERSION
    tag = get_platform_tag()
    return f"{GITHUB_DOWNLOAD_BASE_URL}/chromium-v{v}/cloakbrowser-{tag}.tar.gz"


# ---------------------------------------------------------------------------
# Local binary override (skip download, use your own build)
# ---------------------------------------------------------------------------
def get_local_binary_override() -> str | None:
    """Check if user has set a local binary path via env var.

    Set CLOAKBROWSER_BINARY_PATH to use a locally built Chromium instead of downloading.
    """
    return os.environ.get("CLOAKBROWSER_BINARY_PATH")
