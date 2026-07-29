"""Stealth configuration and platform detection for cloakbrowser."""

from __future__ import annotations

import os
import platform
import random
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Chromium version shipped with this release.
# Different platforms may ship different versions during transition periods.
# CHROMIUM_VERSION is the latest across all platforms (for display/reference).
# Use get_chromium_version() for the current platform's actual version.
# ---------------------------------------------------------------------------
CHROMIUM_VERSION = "146.0.7680.177.5"

PLATFORM_CHROMIUM_VERSIONS: dict[str, str] = {
    "linux-x64": "146.0.7680.177.5",
    "linux-arm64": "146.0.7680.177.3",
    "darwin-arm64": "145.0.7632.109.2",
    "darwin-x64": "145.0.7632.109.2",
    "windows-x64": "146.0.7680.177.5",
}

# ---------------------------------------------------------------------------
# Ed25519 public keys for verifying downloaded binaries.
#
# Each release publishes SHA256SUMS and a detached signature SHA256SUMS.sig.
# The wrapper verifies that signature against the keys below before trusting
# any hash in the manifest, so the download origin alone cannot certify a
# tampered binary. Values are base64 of the 32-byte raw public key. Multiple
# entries are accepted to allow key rotation.
# ---------------------------------------------------------------------------
BINARY_SIGNING_PUBKEYS: list[str] = [
    "MKFKwIhUcKWq5xTuNA0Ovg99njcDEcEJvmWYYhApvaU=",
]

# ---------------------------------------------------------------------------
# Playwright default args to suppress — these leak automation signals.
# --enable-automation: exposes navigator.webdriver = true
# --enable-unsafe-swiftshader: forces software WebGL rendering via SwiftShader,
#   producing a distinctive renderer string that no real user browser has
# ---------------------------------------------------------------------------
IGNORE_DEFAULT_ARGS = ["--enable-automation", "--enable-unsafe-swiftshader"]


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
        f"--fingerprint={seed}",
    ]

    if system == "Darwin":
        # Tell the fingerprint patches we're on macOS so GPU/UA match natively
        return base + ["--fingerprint-platform=macos"]

    # Linux/Windows: Windows fingerprint profile.
    # Screen and window size come from the real display, not this flag (verified:
    # identical across seeds), so the wrapper must not emulate a viewport on top in
    # headed mode — that would break outerWidth >= innerWidth coherence.
    return base + ["--fingerprint-platform=windows"]


# ---------------------------------------------------------------------------
# Default viewport — used for HEADLESS only (headed launches use no_viewport so
# the page tracks the real window). Headless has no window chrome, so a fixed
# viewport stays coherent (outer == inner) and gives deterministic dimensions.
# Models a maximized Chrome on 1080p Windows: screen=1920x1080,
# innerHeight=947 (minus ~85px Chrome UI: tabs + address bar + bookmarks).
# ---------------------------------------------------------------------------
DEFAULT_VIEWPORT = {"width": 1920, "height": 947}

# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------
SUPPORTED_PLATFORMS: dict[tuple[str, str], str] = {
    ("Linux", "x86_64"): "linux-x64",
    ("Linux", "aarch64"): "linux-arm64",
    ("Darwin", "arm64"): "darwin-arm64",
    ("Darwin", "x86_64"): "darwin-x64",
    ("Windows", "AMD64"): "windows-x64",
    ("Windows", "x86_64"): "windows-x64",
}

# Platforms with pre-built binaries available for download (derived from version map).
AVAILABLE_PLATFORMS: set[str] = set(PLATFORM_CHROMIUM_VERSIONS.keys())


_VERSION_PIN_RE = re.compile(r"^[0-9]+(?:\.[0-9]+){3,4}$")


def normalize_release_channel(release_channel: str | None = None) -> str:
    """Return the requested release channel, defaulting to Stable."""
    raw = (
        release_channel
        if release_channel is not None
        else os.environ.get("CLOAKBROWSER_RELEASE_CHANNEL", "stable")
    )
    return "preview" if raw.strip().lower() == "preview" else "stable"


def normalize_requested_version(version: str | None = None) -> str | None:
    """Return an explicit Chromium version pin from arg/env, or None.

    The explicit argument wins over CLOAKBROWSER_VERSION. Only numeric dotted
    versions are accepted because the value is interpolated into cache paths and
    download URLs.
    """
    raw = version if version is not None else os.environ.get("CLOAKBROWSER_VERSION")
    if raw is None:
        return None
    normalized = raw.strip()
    if not normalized:
        return None
    if not _VERSION_PIN_RE.fullmatch(normalized):
        raise ValueError(
            "Invalid browser version pin. Use a full numeric Chromium version, "
            "e.g. '148.0.7778.215.2'."
        )
    return normalized


def get_chromium_version() -> str:
    """Return the Chromium version for the current platform."""
    tag = get_platform_tag()
    return PLATFORM_CHROMIUM_VERSIONS.get(tag, CHROMIUM_VERSION)


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


def get_binary_dir(version: str | None = None, pro: bool = False) -> Path:
    """Return the directory for a Chromium version binary."""
    v = version or get_chromium_version()
    suffix = "-pro" if pro else ""
    return get_cache_dir() / f"chromium-{v}{suffix}"


def get_binary_path(version: str | None = None, pro: bool = False) -> Path:
    """Return the expected path to the chrome executable."""
    binary_dir = get_binary_dir(version, pro=pro)

    if platform.system() == "Darwin":
        # macOS: Chromium.app bundle
        return binary_dir / "Chromium.app" / "Contents" / "MacOS" / "Chromium"
    elif platform.system() == "Windows":
        return binary_dir / "chrome.exe"
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
            f"\n\033[1mCloakBrowser\033[0m — Pre-built binaries are currently only available for: {available}.\n\n"
            f"To use CloakBrowser now, set CLOAKBROWSER_BINARY_PATH to a local Chromium binary."
        )


def get_effective_version(
    pro: bool = False, release_channel: str | None = None
) -> str | None:
    """Return the best available version: auto-updated if available, else platform default.

    Reads a platform-scoped marker file from the cache directory.
    Returns the platform's hardcoded version if no update has been downloaded.

    When ``pro=True``, reads from the Pro-specific marker and returns ``None`` when
    no cached Pro binary matches it. A valid Pro license must NEVER fall back to the
    free binary, so there is deliberately no free-version fallback here — callers
    treat ``None`` as "resolve the latest Pro version from the server" instead.
    """
    base = get_chromium_version()
    cache = get_cache_dir()

    if pro:
        channel = normalize_release_channel(release_channel)
        marker_prefix = (
            "latest_pro_version_preview"
            if channel == "preview"
            else "latest_pro_version"
        )
        marker = cache / f"{marker_prefix}_{get_platform_tag()}"
        if marker.exists():
            try:
                version = marker.read_text().strip()
                if version:
                    binary = get_binary_path(version, pro=True)
                    # Match launch's _pro_binary_ready (exists AND executable) so
                    # `info` never reports a build that launch would reject.
                    if binary.exists() and os.access(binary, os.X_OK):
                        return version
            except (ValueError, OSError):
                pass
        return None

    # Free tier: try platform-scoped marker first, fall back to legacy marker
    for name in (f"latest_version_{get_platform_tag()}", "latest_version"):
        marker = cache / name
        if marker.exists():
            try:
                version = marker.read_text().strip()
                if version and _version_newer(version, base):
                    binary = get_binary_path(version)
                    if binary.exists():
                        return version
            except (ValueError, OSError):
                pass
    return base


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

GITHUB_DOWNLOAD_BASE_URL = "https://github.com/CloakHQ/cloakbrowser/releases/download"


def get_archive_ext() -> str:
    """Return the archive extension for the current platform (.zip for Windows, .tar.gz otherwise)."""
    return ".zip" if platform.system() == "Windows" else ".tar.gz"


def get_archive_name(tag: str | None = None) -> str:
    """Return the archive filename for a platform tag (e.g. 'cloakbrowser-linux-x64.tar.gz')."""
    t = tag or get_platform_tag()
    return f"cloakbrowser-{t}{get_archive_ext()}"


def get_download_url(version: str | None = None) -> str:
    """Return the full download URL for the current platform's binary archive."""
    v = version or get_chromium_version()
    return f"{DOWNLOAD_BASE_URL}/chromium-v{v}/{get_archive_name()}"


def get_fallback_download_url(version: str | None = None) -> str:
    """Return the GitHub Releases fallback URL for the binary archive."""
    v = version or get_chromium_version()
    return f"{GITHUB_DOWNLOAD_BASE_URL}/chromium-v{v}/{get_archive_name()}"


# ---------------------------------------------------------------------------
# Local binary override (skip download, use your own build)
# ---------------------------------------------------------------------------
def get_local_binary_override() -> str | None:
    """Check if user has set a local binary path via env var.

    Set CLOAKBROWSER_BINARY_PATH to use a locally built Chromium instead of downloading.
    """
    return os.environ.get("CLOAKBROWSER_BINARY_PATH")


# ---------------------------------------------------------------------------
# Headless viewport handling by binary version
# ---------------------------------------------------------------------------
# First Chromium build that reports coherent headless dimensions without an
# emulated viewport. On these binaries the wrapper launches headless with
# no_viewport; older binaries need a fixed DEFAULT_VIEWPORT to stay coherent.
# None => not shipped yet; feature off, behavior byte-identical to today.
# TODO: set to the chromium version string that first ships it.
HEADLESS_NO_VIEWPORT_MIN_VERSION: str | None = "148.0.7778.215.4"


def binary_supports_headless_no_viewport(
    license_key: str | None = None,
    browser_version: str | None = None,
    release_channel: str | None = None,
) -> bool:
    """Whether headless can launch with ``no_viewport`` on the resolved binary.

    Only binaries at or above ``HEADLESS_NO_VIEWPORT_MIN_VERSION`` qualify; older
    ones keep ``DEFAULT_VIEWPORT``. A local override binary
    (``CLOAKBROWSER_BINARY_PATH``) is unknown-version, so stay on the safe path.
    """
    if HEADLESS_NO_VIEWPORT_MIN_VERSION is None:
        return False
    # A declared version (browser_version arg OR CLOAKBROWSER_VERSION env) wins even
    # under a local override — the caller is asserting the version (also how internal
    # builds opt in). Only an override with no declared version stays on the safe path.
    try:
        declared = normalize_requested_version(browser_version)
    except ValueError:
        declared = None
    if declared:
        version = declared
    elif get_local_binary_override():
        return False
    else:
        from .license import resolve_license_key

        pro = bool(resolve_license_key(license_key))
        version = get_effective_version(pro=pro, release_channel=release_channel)
    if version is None:
        return False
    try:
        return not _version_newer(HEADLESS_NO_VIEWPORT_MIN_VERSION, version)
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Dual-stack WebRTC exit IP by binary version
# ---------------------------------------------------------------------------
# First build whose ``--fingerprint-webrtc-ip`` accepts a second address for the
# other address family. Below this floor the flag takes a single address only, so
# the wrapper MUST pass one, as it always has.
WEBRTC_DUAL_STACK_MIN_VERSION: str | None = "150.0.7871.114.5"


def binary_supports_dual_stack_webrtc(
    license_key: str | None = None,
    browser_version: str | None = None,
    release_channel: str | None = None,
) -> bool:
    """Whether the resolved binary understands a "<v4>,<v6>" WebRTC exit IP.

    Same resolution rules as :func:`binary_supports_headless_no_viewport`: a
    declared version wins, an unknown-version local override stays on the safe
    (IPv4-only) path.
    """
    if WEBRTC_DUAL_STACK_MIN_VERSION is None:
        return False
    try:
        declared = normalize_requested_version(browser_version)
    except ValueError:
        declared = None
    if declared:
        version = declared
    elif get_local_binary_override():
        return False
    else:
        from .license import resolve_license_key

        pro = bool(resolve_license_key(license_key))
        version = get_effective_version(pro=pro, release_channel=release_channel)
    if version is None:
        return False
    try:
        return not _version_newer(WEBRTC_DUAL_STACK_MIN_VERSION, version)
    except (ValueError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# Inline HTTP proxy authentication by binary version
# ---------------------------------------------------------------------------
# First Chromium build, per platform, whose binary can take inline HTTP proxy
# credentials (Chromium-native ``--proxy-server=http://user:pass@host``). Below
# the floor the wrapper MUST route credentialed HTTP/HTTPS proxies through
# Playwright's proxy dict instead — an older binary treats the ``user:pass@``
# authority as an invalid proxy host and drops proxy auth (#182).
#
# A single global threshold (like HEADLESS_NO_VIEWPORT_MIN_VERSION) can't model
# this: the capability landed in different build lineages at different points —
# linux-x64/windows-x64 have it at 146.0.7680.177.5, but the free macOS (145.x)
# and linux-arm64 (146.0.7680.177.3) floors predate it, so those only qualify
# once they resolve to a Pro/newer build (148+). Platforms absent from this map
# are treated as never-inline (unknown capability => safe fallback).
HTTP_PROXY_INLINE_AUTH_MIN_VERSION: dict[str, str] = {
    "linux-x64": "146.0.7680.177.5",
    "windows-x64": "146.0.7680.177.5",
    "linux-arm64": "148.0.7778.215.3",
    "darwin-arm64": "148.0.7778.215.3",
    "darwin-x64": "148.0.7778.215.3",
}


def binary_supports_http_proxy_inline_auth(
    license_key: str | None = None,
    browser_version: str | None = None,
    release_channel: str | None = None,
) -> bool:
    """Whether the resolved binary accepts inline HTTP proxy credentials.

    The capability is a function of the binary version; ``license_key`` only
    resolves *which* version launches (Pro build vs free default), exactly like
    ``binary_supports_headless_no_viewport``. A declared pin wins, else a valid
    Pro license resolves to the Pro build (which ships the patch), else the free
    per-platform default — then it compares to this platform's floor. Below the
    floor, credentialed HTTP proxies fall back to Playwright's proxy dict. A
    local override with no declared version is unknown-version, so stay on the
    safe fallback. Python, JS and .NET mirror this gate.
    """
    floor = HTTP_PROXY_INLINE_AUTH_MIN_VERSION.get(get_platform_tag())
    if floor is None:
        return False
    try:
        declared = normalize_requested_version(browser_version)
    except ValueError:
        declared = None
    if declared:
        version = declared
    elif get_local_binary_override():
        return False
    else:
        from .license import resolve_license_key

        pro = bool(resolve_license_key(license_key))
        version = get_effective_version(pro=pro, release_channel=release_channel)
    if version is None:
        # Pro with no cached marker => resolve latest Pro from the server, which
        # is >= the floor by construction and always ships the patch.
        return True
    try:
        return not _version_newer(floor, version)
    except (ValueError, AttributeError):
        return False


def binary_supports_maximized_window(
    license_key: str | None = None,
    browser_version: str | None = None,
    release_channel: str | None = None,
) -> bool:
    """Whether the wrapper may auto-add ``--start-maximized``.

    Gated on the same threshold as the no_viewport shim: only binaries whose
    headless surface-fix + headed screen-clamp make a maximized window coherent
    (``outer == screen``). Below it, maximizing headless while the CDP viewport
    stays at 1280x720 yields ``outerWidth < innerWidth`` — an impossible-window
    bot tell — so the flag must NOT be added. Shares
    ``HEADLESS_NO_VIEWPORT_MIN_VERSION``; kept as its own name so the two can
    diverge later. Python, JS and .NET mirror this gate.
    """
    return binary_supports_headless_no_viewport(
        license_key, browser_version, release_channel
    )
