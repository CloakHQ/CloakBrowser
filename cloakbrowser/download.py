"""Binary download and cache management for cloakbrowser.

Downloads the patched Chromium binary on first use, caches it locally.
Similar to how Playwright downloads its own bundled Chromium.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import stat
import subprocess
import tarfile
import tempfile
import threading
import time
from pathlib import Path

import httpx

from .config import (
    CHROMIUM_VERSION,
    DOWNLOAD_BASE_URL,
    GITHUB_API_URL,
    GITHUB_DOWNLOAD_BASE_URL,
    _version_newer,
    check_platform_available,
    get_binary_dir,
    get_binary_path,
    get_cache_dir,
    get_chromium_version,
    get_download_url,
    get_effective_version,
    get_fallback_download_url,
    get_local_binary_override,
    get_platform_tag,
)

logger = logging.getLogger("cloakbrowser")

# Timeout for download (large binary, allow 10 min)
DOWNLOAD_TIMEOUT = 600.0

# Auto-update check interval (1 hour)
UPDATE_CHECK_INTERVAL = 3600


def ensure_binary() -> str:
    """Ensure the stealth Chromium binary is available. Download if needed.

    Returns the path to the chrome executable as a string.

    Set CLOAKBROWSER_BINARY_PATH to skip download and use a local build.
    """
    # Check for local override first
    local_override = get_local_binary_override()
    if local_override:
        path = Path(local_override)
        if not path.exists():
            raise FileNotFoundError(
                f"CLOAKBROWSER_BINARY_PATH set to '{local_override}' but file does not exist"
            )
        logger.info("Using local binary override: %s", local_override)
        return str(path)

    # Fail fast if no binary available for this platform
    check_platform_available()

    # Check for auto-updated version first, then fall back to hardcoded
    effective = get_effective_version()
    binary_path = get_binary_path(effective)

    if binary_path.exists() and _is_executable(binary_path):
        logger.debug("Binary found in cache: %s (version %s)", binary_path, effective)
        _maybe_trigger_update_check()
        return str(binary_path)

    # Fall back to platform's hardcoded version if effective version binary doesn't exist
    platform_version = get_chromium_version()
    if effective != platform_version:
        fallback_path = get_binary_path()
        if fallback_path.exists() and _is_executable(fallback_path):
            logger.debug("Binary found in cache: %s", fallback_path)
            _maybe_trigger_update_check()
            return str(fallback_path)

    # Download platform's hardcoded version
    logger.info(
        "Stealth Chromium %s not found. Downloading for %s...",
        platform_version,
        get_platform_tag(),
    )
    _download_and_extract()

    binary_path = get_binary_path()
    if not binary_path.exists():
        raise RuntimeError(
            f"Download completed but binary not found at expected path: {binary_path}. "
            f"This may indicate a packaging issue. Please report at "
            f"https://github.com/CloakHQ/cloakbrowser/issues"
        )

    _maybe_trigger_update_check()
    return str(binary_path)


def _download_and_extract(version: str | None = None) -> None:
    """Download the binary archive and extract to cache directory.

    Tries the primary server (cloakbrowser.dev) first, falls back to
    GitHub Releases if the primary is unreachable or returns an error.
    Verifies SHA-256 checksum before extraction when available.
    """
    primary_url = get_download_url(version)
    fallback_url = get_fallback_download_url(version)
    binary_dir = get_binary_dir(version)
    binary_path = get_binary_path(version)

    # Create cache dir
    binary_dir.parent.mkdir(parents=True, exist_ok=True)

    # Download to temp file first (atomic — no partial downloads in cache)
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Try primary, fall back to GitHub Releases (skip fallback if custom URL)
        try:
            _download_file(primary_url, tmp_path)
        except Exception as primary_err:
            if os.environ.get("CLOAKBROWSER_DOWNLOAD_URL"):
                raise
            logger.warning(
                "Primary download failed (%s), trying GitHub Releases...",
                primary_err,
            )
            _download_file(fallback_url, tmp_path)

        # Verify checksum before extraction
        if os.environ.get("CLOAKBROWSER_SKIP_CHECKSUM", "").lower() != "true":
            _verify_download_checksum(tmp_path, version)

        _extract_archive(tmp_path, binary_dir, binary_path)
        logger.info("Visit https://cloakbrowser.dev for docs and release notifications.")
        logger.info("Issues? https://github.com/CloakHQ/CloakBrowser/issues")
        logger.info("Star us if CloakBrowser helps: https://github.com/CloakHQ/CloakBrowser")
    finally:
        # Clean up temp file
        tmp_path.unlink(missing_ok=True)


def _verify_download_checksum(file_path: Path, version: str | None = None) -> None:
    """Fetch SHA256SUMS and verify the downloaded file. Warn if unavailable, fail on mismatch."""
    checksums = _fetch_checksums(version)
    tarball_name = f"cloakbrowser-{get_platform_tag()}.tar.gz"

    if checksums is None:
        logger.warning("SHA256SUMS not available for this release — skipping checksum verification")
        return

    expected = checksums.get(tarball_name)
    if expected is None:
        logger.warning("SHA256SUMS found but no entry for %s — skipping verification", tarball_name)
        return

    _verify_checksum(file_path, expected)


def _fetch_checksums(version: str | None = None) -> dict[str, str] | None:
    """Fetch SHA256SUMS file for a version. Returns {filename: hash} or None."""
    v = version or get_chromium_version()
    has_custom_url = os.environ.get("CLOAKBROWSER_DOWNLOAD_URL")

    # Build URL list — respect custom URL contract (no GitHub fallback)
    urls = [f"{DOWNLOAD_BASE_URL}/chromium-v{v}/SHA256SUMS"]
    if not has_custom_url:
        urls.append(f"{GITHUB_DOWNLOAD_BASE_URL}/chromium-v{v}/SHA256SUMS")

    for url in urls:
        try:
            resp = httpx.get(url, follow_redirects=True, timeout=10.0)
            resp.raise_for_status()
            return _parse_checksums(resp.text)
        except Exception:
            continue
    return None


def _parse_checksums(text: str) -> dict[str, str]:
    """Parse SHA256SUMS format: 'hash  filename' per line."""
    result = {}
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 2:
            hash_val, filename = parts
            filename = filename.lstrip("*")
            result[filename] = hash_val.lower()
    return result


def _verify_checksum(file_path: Path, expected_hash: str) -> None:
    """Verify SHA-256 of a file. Raises RuntimeError on mismatch."""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    actual = sha256.hexdigest().lower()
    if actual != expected_hash:
        raise RuntimeError(
            f"Checksum verification failed!\n"
            f"  Expected: {expected_hash}\n"
            f"  Got:      {actual}\n"
            f"  File may be corrupted or tampered with. "
            f"Please retry or report at https://github.com/CloakHQ/cloakbrowser/issues"
        )
    logger.info("Checksum verified: SHA-256 OK")


def _download_file(url: str, dest: Path) -> None:
    """Download a file with progress logging."""
    logger.info("Downloading from %s", url)

    with httpx.stream("GET", url, follow_redirects=True, timeout=DOWNLOAD_TIMEOUT) as response:
        response.raise_for_status()

        total = int(response.headers.get("content-length", 0))
        downloaded = 0
        last_logged_pct = -1

        with open(dest, "wb") as f:
            for chunk in response.iter_bytes(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)

                if total > 0:
                    pct = int(downloaded / total * 100)
                    # Log every 10%
                    if pct >= last_logged_pct + 10:
                        last_logged_pct = pct
                        logger.info(
                            "Download progress: %d%% (%d/%d MB)",
                            pct,
                            downloaded // (1024 * 1024),
                            total // (1024 * 1024),
                        )

    logger.info("Download complete: %d MB", dest.stat().st_size // (1024 * 1024))


def _extract_archive(
    archive_path: Path, dest_dir: Path, binary_path: Path | None = None
) -> None:
    """Extract tar.gz archive to destination directory."""
    logger.info("Extracting to %s", dest_dir)

    # Clean existing dir if partial download existed
    if dest_dir.exists():
        import shutil
        shutil.rmtree(dest_dir)

    dest_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, "r:gz") as tar:
        # Security: prevent path traversal
        safe_members = []
        for member in tar.getmembers():
            # Allow symlinks — macOS .app bundles require them (Framework layout)
            if member.issym() or member.islnk():
                link_target = member.linkname
                # Reject symlinks that escape the dest dir
                if os.path.isabs(link_target) or ".." in link_target.split("/"):
                    logger.warning("Skipping suspicious symlink: %s -> %s", member.name, link_target)
                    continue
            else:
                member_path = (dest_dir / member.name).resolve()
                if not str(member_path).startswith(str(dest_dir.resolve())):
                    raise RuntimeError(f"Archive contains path traversal: {member.name}")
            safe_members.append(member)

        tar.extractall(dest_dir, members=safe_members)

    # If tar extracted into a single subdirectory, flatten it
    # (e.g. fingerprint-chromium-142-custom-v2/chrome → chrome)
    # But never flatten .app bundles — macOS needs the bundle structure intact
    _flatten_single_subdir(dest_dir)

    # Make binary executable
    bp = binary_path or get_binary_path()
    if bp.exists():
        _make_executable(bp)

    # macOS: remove quarantine/provenance xattrs to prevent Gatekeeper prompts
    if platform.system() == "Darwin":
        _remove_quarantine(dest_dir)

    if bp.exists():
        logger.info("Binary ready: %s", bp)


def _flatten_single_subdir(dest_dir: Path) -> None:
    """If extraction created a single subdirectory, move its contents up.

    Many tar archives wrap files in a top-level directory (e.g.
    fingerprint-chromium-142-custom-v2/chrome). We want chrome at dest_dir/chrome.
    """
    import shutil

    entries = list(dest_dir.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        subdir = entries[0]
        # Never flatten .app bundles — macOS needs the bundle structure
        if subdir.name.endswith(".app"):
            logger.debug("Keeping .app bundle intact: %s", subdir.name)
            return
        logger.debug("Flattening single subdirectory: %s", subdir.name)
        for item in subdir.iterdir():
            shutil.move(str(item), str(dest_dir / item.name))
        subdir.rmdir()


def _is_executable(path: Path) -> bool:
    """Check if a file is executable."""
    return os.access(path, os.X_OK)


def _make_executable(path: Path) -> None:
    """Make a file executable (chmod +x)."""
    current = path.stat().st_mode
    path.chmod(current | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _remove_quarantine(path: Path) -> None:
    """Remove macOS quarantine/provenance xattrs so Gatekeeper doesn't block the binary."""
    try:
        subprocess.run(
            ["xattr", "-cr", str(path)],
            capture_output=True,
            timeout=30,
        )
        logger.debug("Removed quarantine attributes from %s", path)
    except Exception:
        logger.debug("Failed to remove quarantine attributes", exc_info=True)


def clear_cache() -> None:
    """Remove all cached binaries. Forces re-download on next launch."""
    from .config import get_cache_dir
    import shutil

    cache_dir = get_cache_dir()
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
        logger.info("Cache cleared: %s", cache_dir)


def binary_info() -> dict:
    """Return info about the current binary installation."""
    effective = get_effective_version()
    binary_path = get_binary_path(effective)
    return {
        "version": effective,
        "bundled_version": CHROMIUM_VERSION,
        "platform": get_platform_tag(),
        "binary_path": str(binary_path),
        "installed": binary_path.exists(),
        "cache_dir": str(get_binary_dir(effective)),
        "download_url": get_download_url(effective),
    }


# ---------------------------------------------------------------------------
# Auto-update
# ---------------------------------------------------------------------------

def check_for_update() -> str | None:
    """Manually check for a newer Chromium version. Returns new version or None.

    This is the public API for triggering an update check. Unlike the
    background check in ensure_binary(), this blocks until complete.
    """
    latest = _get_latest_chromium_version()
    if latest is None:
        return None
    if not _version_newer(latest, get_chromium_version()):
        return None

    binary_dir = get_binary_dir(latest)
    if binary_dir.exists():
        # Already downloaded
        _write_version_marker(latest)
        return latest

    logger.info("Downloading Chromium %s...", latest)
    _download_and_extract(version=latest)
    _write_version_marker(latest)
    return latest


def _should_check_for_update() -> bool:
    """Check if auto-update is enabled and rate limit hasn't been hit."""
    if os.environ.get("CLOAKBROWSER_AUTO_UPDATE", "").lower() == "false":
        return False
    if get_local_binary_override():
        return False
    if os.environ.get("CLOAKBROWSER_DOWNLOAD_URL"):
        return False

    check_file = get_cache_dir() / ".last_update_check"
    if check_file.exists():
        try:
            last_check = float(check_file.read_text().strip())
            if time.time() - last_check < UPDATE_CHECK_INTERVAL:
                return False
        except (ValueError, OSError):
            pass
    return True


def _get_latest_chromium_version() -> str | None:
    """Hit GitHub Releases API, return latest chromium-v* version for this platform.

    Checks that the release has a binary asset for the current platform,
    so Linux-only releases won't be offered to macOS users.
    """
    try:
        resp = httpx.get(
            GITHUB_API_URL, params={"per_page": 10}, timeout=10.0
        )
        resp.raise_for_status()
        platform_tarball = f"cloakbrowser-{get_platform_tag()}.tar.gz"
        for release in resp.json():
            tag = release.get("tag_name", "")
            if tag.startswith("chromium-v") and not release.get("draft"):
                asset_names = {a["name"] for a in release.get("assets", [])}
                if platform_tarball in asset_names:
                    return tag.removeprefix("chromium-v")
        return None
    except Exception:
        logger.debug("Auto-update check failed", exc_info=True)
        return None


def _write_version_marker(version: str) -> None:
    """Write the latest version marker for this platform to cache dir."""
    cache_dir = get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    marker = cache_dir / f"latest_version_{get_platform_tag()}"
    # Write to temp file then rename for atomicity
    tmp = marker.with_suffix(".tmp")
    tmp.write_text(version)
    tmp.rename(marker)


def _check_and_download_update() -> None:
    """Background task: check for newer binary, download if available."""
    try:
        # Record check timestamp first (rate limiting)
        check_file = get_cache_dir() / ".last_update_check"
        check_file.parent.mkdir(parents=True, exist_ok=True)
        check_file.write_text(str(time.time()))

        platform_version = get_chromium_version()
        latest = _get_latest_chromium_version()
        if latest is None:
            return
        if not _version_newer(latest, platform_version):
            return

        # Already downloaded?
        if get_binary_dir(latest).exists():
            _write_version_marker(latest)
            return

        logger.info(
            "Newer Chromium available: %s (current: %s). Downloading in background...",
            latest,
            platform_version,
        )
        _download_and_extract(version=latest)
        _write_version_marker(latest)
        logger.info(
            "Background update complete: Chromium %s ready. Will use on next launch.",
            latest,
        )
    except Exception:
        logger.debug("Background update failed", exc_info=True)


def _maybe_trigger_update_check() -> None:
    """Fire-and-forget update check in a daemon thread."""
    if not _should_check_for_update():
        return
    t = threading.Thread(target=_check_and_download_update, daemon=True)
    t.start()
