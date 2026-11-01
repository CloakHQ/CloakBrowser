"""Stealth configuration and platform detection for cloakbrowser."""

from __future__ import annotations

import logging
import os
import platform
import random
import re
import time
import uuid
from pathlib import Path

logger = logging.getLogger("cloakbrowser")


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
SEED_MIN, SEED_MAX = 10000, 99999

# Shared with the JS and .NET wrappers: decimal seed + newline, so a profile
# keeps its seed whichever wrapper opens it.
PROFILE_SEED_FILE = ".cloakbrowser-seed"


def _random_seed() -> int:
    return random.randint(SEED_MIN, SEED_MAX)


def _read_profile_seed(path: Path) -> int | None:
    """Stored seed, or None if the file is missing or corrupt (corrupt is removed)."""
    try:
        data = path.read_bytes()
        # Empty = a concurrent launch's exclusive create (no-hard-link fallback)
        # hasn't written yet; give it ~1s before calling the file corrupt.
        for _ in range(20):
            if data:
                break
            time.sleep(0.05)
            data = path.read_bytes()
    except FileNotFoundError:
        return None
    text = data.strip()
    if text.isdigit() and text.isascii() and SEED_MIN <= int(text) <= SEED_MAX:
        return int(text)
    # A corrupt file gets a fresh seed (= new identity), so say so loudly.
    logger.warning("Corrupt fingerprint seed file %s (%r); generating a new seed", path, data[:32])
    try:
        path.unlink()
    except FileNotFoundError:
        pass  # a concurrent launch already removed it
    return None


def _write_synced(path: Path, mode: str, content: str) -> None:
    # newline="\n": same bytes as the JS/.NET wrappers (no \r\n on Windows)
    with open(path, mode, encoding="ascii", newline="\n") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())


def persistent_seed_args(
    user_data_dir: str | os.PathLike, stealth_args: bool, args: list[str] | None
) -> list[str] | None:
    """Pin a persistent profile's fingerprint seed in ``<user_data_dir>/.cloakbrowser-seed``.

    The first launch creates the seed; later launches reuse it. Returned as a
    user arg, so it overrides the random stealth default via build_args dedup.
    An explicit ``--fingerprint`` in ``args`` (including ``=off``) or
    ``stealth_args=False`` leaves the file alone.
    """
    if not stealth_args or not user_data_dir:
        return args
    if any(a.split("=", 1)[0] == "--fingerprint" for a in args or []):
        return args

    profile = Path(os.fspath(user_data_dir))
    path = profile / PROFILE_SEED_FILE
    seed = _read_profile_seed(path)
    if seed is None:
        profile.mkdir(parents=True, exist_ok=True)
        tmp = profile / f"{PROFILE_SEED_FILE}.{uuid.uuid4().hex}.tmp"
        content = f"{_random_seed()}\n"
        try:
            _write_synced(tmp, "w", content)
            # Publish without replacing: concurrent first launches all end up
            # with whichever seed was linked first.
            try:
                os.link(tmp, path)
            except FileExistsError:
                pass
            except OSError as e:
                # No hard links (FAT/exFAT, some network mounts): exclusive create
                # still never overwrites. ponytail: a concurrent reader can catch
                # the file empty here and regenerate; link() avoids that window.
                logger.debug("Hard link unsupported for %s (%s); using exclusive create", path, e)
                try:
                    _write_synced(path, "x", content)
                except FileExistsError:
                    pass
        finally:
            try:
                tmp.unlink()
            except OSError as e:
                logger.warning("Failed to remove temp seed file %s: %s", tmp, e)
        # ponytail: if the winner's file is corrupt here (only via a concurrent
        # corrupt-file race), fail loudly rather than loop.
        seed = _read_profile_seed(path)
        if seed is None:
            raise RuntimeError(f"Could not create fingerprint seed file {path}")
    return [f"--fingerprint={seed}", *(args or [])]


def get_default_stealth_args() -> list[str]:
    """Build stealth args with a random fingerprint seed per launch.

    On macOS, skips platform/GPU spoofing — runs as a native Mac browser.
    Spoofing Windows on Mac creates detectable mismatches (fonts, GPU, etc.).
    """
    seed = _random_seed()
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


def get_binary_dir(version: str) -> Path:
    """Return the cache directory for a Chromium build."""
    return get_cache_dir() / f"chromium-{version}-pro"


def get_binary_path(version: str) -> Path:
    """Return the expected path to the chrome executable."""
    binary_dir = get_binary_dir(version)

    if platform.system() == "Darwin":
        # macOS: Chromium.app bundle
        return binary_dir / "Chromium.app" / "Contents" / "MacOS" / "Chromium"
    elif platform.system() == "Windows":
        return binary_dir / "chrome.exe"
    else:
        # Linux: flat binary
        return binary_dir / "chrome"


def get_effective_version(release_channel: str | None = None) -> str | None:
    """Return the cached build the channel's marker names, or None.

    None means nothing usable is cached: callers resolve the latest build from
    the server instead.
    """
    channel = normalize_release_channel(release_channel)
    marker_prefix = (
        "latest_pro_version_preview" if channel == "preview" else "latest_pro_version"
    )
    marker = get_cache_dir() / f"{marker_prefix}_{get_platform_tag()}"
    try:
        version = marker.read_text().strip()
    except OSError:
        return None
    if version:
        binary = get_binary_path(version)
        # Match launch's _pro_binary_ready (exists AND executable) so
        # `info` never reports a build that launch would reject.
        if binary.exists() and os.access(binary, os.X_OK):
            return version
    return None


def _version_tuple(v: str) -> tuple[int, ...]:
    """Parse '145.0.7718.0' into (145, 0, 7718, 0) for comparison."""
    return tuple(int(x) for x in v.split("."))


def _version_newer(a: str, b: str) -> bool:
    """Return True if version a is strictly newer than version b."""
    return _version_tuple(a) > _version_tuple(b)


# ---------------------------------------------------------------------------
# Download URL
# ---------------------------------------------------------------------------
DOWNLOAD_BASE_URL = "https://cloakbrowser.dev"


def get_archive_ext() -> str:
    """Return the archive extension for the current platform (.zip for Windows, .tar.gz otherwise)."""
    return ".zip" if platform.system() == "Windows" else ".tar.gz"


def get_archive_name(tag: str | None = None) -> str:
    """Return the archive filename for a platform tag (e.g. 'cloakbrowser-linux-x64.tar.gz')."""
    t = tag or get_platform_tag()
    return f"cloakbrowser-{t}{get_archive_ext()}"


# ---------------------------------------------------------------------------
# Local binary override (skip download, use your own build)
# ---------------------------------------------------------------------------
def get_local_binary_override() -> str | None:
    """Check if user has set a local binary path via env var.

    Set CLOAKBROWSER_BINARY_PATH to use a locally built Chromium instead of downloading.
    """
    return os.environ.get("CLOAKBROWSER_BINARY_PATH")
