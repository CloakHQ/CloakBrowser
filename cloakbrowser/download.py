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
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path

import httpx

from ._version import __version__ as _wrapper_version
from .config import (
    BINARY_SIGNING_PUBKEYS,
    CHROMIUM_VERSION,
    DOWNLOAD_BASE_URL,
    GITHUB_API_URL,
    GITHUB_DOWNLOAD_BASE_URL,
    _version_newer,
    check_platform_available,
    get_archive_ext,
    get_archive_name,
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


class BinaryVerificationError(RuntimeError):
    """A downloaded binary could not be authenticated (bad/missing signature,
    version mismatch, or checksum failure).

    Distinct from transient download/network errors: a verification failure is
    a tampering signal and MUST surface, never silently fall back to another
    binary. The Pro routing in ensure_binary re-raises this rather than
    downgrading to the free tier.
    """

# Timeout for download (large binary, allow 10 min)
DOWNLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)

# Auto-update check interval (1 hour)
UPDATE_CHECK_INTERVAL = 3600

# Pro Chromium major shown in the free-tier welcome banner. Bump at each Pro
# major release (there is no local constant to derive it from — the live Pro
# version comes from the network, which we don't call just to print a banner).
PRO_MAJOR = "148"


def _show_welcome(pro: bool = False) -> None:
    """Show welcome message on first launch. Uses a marker file to show only once.

    The Pro-upsell line is shown to free-tier users only; Pro users get a plain
    banner (no "running free tier" message, which would be false for them).
    """
    marker = get_cache_dir() / ".welcome_shown"
    if marker.exists():
        return
    sys.stderr.write("\n")
    sys.stderr.write("  CloakBrowser — stealth Chromium for automation\n")
    sys.stderr.write("  https://github.com/CloakHQ/CloakBrowser\n")
    sys.stderr.write("\n")
    if pro:
        sys.stderr.write(
            f"  CloakBrowser Pro active (v{PRO_MAJOR}) — latest binary, newest patches.\n"
        )
        sys.stderr.write("  Pro support → support@cloakbrowser.dev\n")
    else:
        free_major = CHROMIUM_VERSION.split(".")[0]
        sys.stderr.write(
            f"  Running free tier (v{free_major}). "
            f"Pro = latest binary (v{PRO_MAJOR}) + newest anti-bot patches.\n"
        )
        sys.stderr.write("  Stay ahead of detection → https://cloakbrowser.dev\n")
    sys.stderr.write("  Star us if CloakBrowser helps your project!\n")
    sys.stderr.write("\n")
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("")
    except OSError:
        pass


def ensure_binary(license_key: str | None = None) -> str:
    """Ensure the stealth Chromium binary is available. Download if needed.

    Returns the path to the chrome executable as a string.

    Args:
        license_key: Pro license key. Also reads from CLOAKBROWSER_LICENSE_KEY env var.

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

    # Pro license key check (custom download URL overrides Pro path)
    from .license import resolve_license_key, validate_license

    key = resolve_license_key(license_key)
    if os.environ.get("CLOAKBROWSER_DOWNLOAD_URL"):
        key = None

    if key:
        info = validate_license(key)
        if info and info.valid:
            # A valid license is entitled to Pro, so Pro failures surface loudly
            # rather than silently substituting the older free binary. (A blip
            # during a routine update never reaches here: _ensure_pro_binary
            # returns the cached Pro binary and updates in the background.)
            try:
                return _ensure_pro_binary(key)
            except BinaryVerificationError:
                # Authenticity could not be confirmed — surface verbatim.
                raise
            except Exception as e:
                # Transient failure with no cached Pro binary to use — surface a
                # clear error rather than silently downloading the free binary.
                raise RuntimeError(
                    f"Pro binary unavailable: {e}. Your license is valid but the "
                    f"Pro binary could not be downloaded right now. Retry in a "
                    f"moment. To use the free binary instead, unset "
                    f"CLOAKBROWSER_LICENSE_KEY."
                ) from e
        elif info:
            logger.warning("License validation failed (plan=%s), using free tier", info.plan)
        else:
            logger.warning("License validation unavailable, using free tier")

    # Fail fast if no binary available for this platform
    check_platform_available()

    # Check for auto-updated version first, then fall back to hardcoded
    effective = get_effective_version()
    binary_path = get_binary_path(effective)

    if binary_path.exists() and _is_executable(binary_path):
        logger.debug("Binary found in cache: %s (version %s)", binary_path, effective)
        _show_welcome()
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
    with tempfile.NamedTemporaryFile(suffix=get_archive_ext(), delete=False) as tmp:
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

        # Verify the download before extraction. On the official path this is a
        # mandatory, non-bypassable Ed25519 signature check (see
        # _verify_download_checksum); the skip flag only applies to custom
        # self-hosted CLOAKBROWSER_DOWNLOAD_URL setups.
        _verify_download_checksum(tmp_path, version)

        _extract_archive(tmp_path, binary_dir, binary_path)
        _show_welcome()
    finally:
        # Clean up temp file
        tmp_path.unlink(missing_ok=True)


def _ensure_pro_binary(license_key: str) -> str:
    """Ensure the Pro binary is downloaded and cached. Returns the binary path."""
    from .license import get_pro_latest_version

    effective = get_effective_version(pro=True)
    binary_path = get_binary_path(effective, pro=True)

    if binary_path.exists() and _is_executable(binary_path):
        logger.debug("Pro binary found in cache: %s (version %s)", binary_path, effective)
        _show_welcome(pro=True)
        _maybe_trigger_pro_update_check(license_key)
        return str(binary_path)

    version = get_pro_latest_version()
    if not version:
        raise RuntimeError("Could not determine latest Pro version from server")

    binary_path = get_binary_path(version, pro=True)
    if binary_path.exists() and _is_executable(binary_path):
        logger.debug("Pro binary found in cache: %s (version %s)", binary_path, version)
        _show_welcome(pro=True)
        return str(binary_path)

    logger.info("Downloading Pro Chromium %s for %s...", version, get_platform_tag())
    _download_pro_binary(version, license_key)

    binary_path = get_binary_path(version, pro=True)
    if not binary_path.exists():
        raise RuntimeError(
            f"Pro download completed but binary not found at: {binary_path}"
        )

    # Write Pro version marker (atomic)
    marker = get_cache_dir() / f"latest_pro_version_{get_platform_tag()}"
    try:
        tmp = marker.with_suffix(".tmp")
        tmp.write_text(version)
        os.replace(str(tmp), str(marker))
    except OSError:
        pass

    _show_welcome(pro=True)
    return str(binary_path)


def _download_pro_binary(version: str, license_key: str) -> None:
    """Download a Pro binary from cloakbrowser.dev with license key auth.

    Requests the explicit version so the served archive matches the signed
    manifest verified in _verify_pro_download.
    """
    download_url = f"{DOWNLOAD_BASE_URL}/api/download/{version}"
    binary_dir = get_binary_dir(version, pro=True)
    binary_path = get_binary_path(version, pro=True)
    platform_tag = get_platform_tag()

    binary_dir.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=get_archive_ext(), delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        _download_file(
            download_url,
            tmp_path,
            headers={
                "Authorization": f"Bearer {license_key}",
                "X-Platform": platform_tag,
            },
        )

        # Pro binaries come from cloakbrowser.dev — the same origin as free
        # downloads — so the M1 attack the Ed25519 signature defends against
        # applies equally. Verify with the same non-bypassable signature check;
        # CLOAKBROWSER_SKIP_CHECKSUM does NOT bypass it (parity with the
        # official free path).
        _verify_pro_download(tmp_path, version)

        _extract_archive(tmp_path, binary_dir, binary_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _verify_pro_download(file_path: Path, version: str) -> None:
    """Verify a Pro archive with the same non-bypassable Ed25519 signature check
    as official free downloads.

    Pro binaries are served from cloakbrowser.dev (same origin as the free
    tier), so a tampered same-origin SHA256SUMS could otherwise certify a
    tampered binary (M1, #308). Fetch the Pro SHA256SUMS + detached
    SHA256SUMS.sig, verify the signature against the pinned keys FIRST, bind the
    manifest to the requested version, then verify the archive's SHA-256.

    An invalid signature, checksum, or version mismatch raises
    BinaryVerificationError (a tampering signal the router surfaces verbatim);
    CLOAKBROWSER_SKIP_CHECKSUM cannot bypass it. A failed manifest FETCH is
    transient — nothing was validated — and raises a plain RuntimeError. A
    valid-license user is never silently downgraded to the free binary.
    """
    base = f"{DOWNLOAD_BASE_URL}/releases/pro/chromium-v{version}"
    try:
        manifest_resp = httpx.get(
            f"{base}/SHA256SUMS", follow_redirects=True, timeout=10.0
        )
        manifest_resp.raise_for_status()
        sig_resp = httpx.get(
            f"{base}/SHA256SUMS.sig", follow_redirects=True, timeout=10.0
        )
        sig_resp.raise_for_status()
    except Exception as exc:
        # Fetch failure is transient, not tampering — raise a plain RuntimeError
        # (the router reports it as "unavailable, retry") rather than a
        # BinaryVerificationError (which it surfaces as a tampering signal).
        raise RuntimeError(
            f"Could not fetch the signed SHA256SUMS for Pro {version} ({exc})"
        )

    manifest_bytes = manifest_resp.content
    # _verify_signature / _verify_checksum raise plain RuntimeError; convert to
    # BinaryVerificationError so the Pro router treats them as tampering signals
    # (re-raise) rather than transient failures (fall back to free).
    try:
        _verify_signature(manifest_bytes, sig_resp.content)
    except RuntimeError as exc:
        raise BinaryVerificationError(str(exc)) from exc
    manifest_text = manifest_bytes.decode("utf-8")

    # Version binding: same forced-downgrade defense as the official path.
    declared = _parse_manifest_version(manifest_text)
    if declared != version:
        raise BinaryVerificationError(
            f"Version mismatch in signed Pro SHA256SUMS: requested {version}, "
            f"manifest declares {declared or 'none'}. Refusing (possible downgrade)."
        )

    tarball_name = get_archive_name()
    expected = _parse_checksums(manifest_text).get(tarball_name)
    if expected is None:
        raise BinaryVerificationError(
            f"Signature-verified Pro SHA256SUMS has no entry for {tarball_name} — "
            f"cannot confirm binary integrity."
        )
    try:
        _verify_checksum(file_path, expected)
    except RuntimeError as exc:
        raise BinaryVerificationError(str(exc)) from exc


def _verify_download_checksum(file_path: Path, version: str | None = None) -> None:
    """Verify the downloaded archive's integrity and authenticity.

    Official path (cloakbrowser.dev / GitHub Releases): fetch SHA256SUMS plus
    its detached Ed25519 signature SHA256SUMS.sig, verify the signature against
    the pinned public keys FIRST, then verify the archive's SHA-256 against the
    now-authenticated manifest. Mandatory and non-bypassable — a same-origin
    manifest can no longer certify a tampered binary (#308).

    Custom self-hosted path (CLOAKBROWSER_DOWNLOAD_URL set): the pinned keys do
    not apply to a third-party server, so fall back to the plain same-origin
    SHA256SUMS check, which CLOAKBROWSER_SKIP_CHECKSUM may bypass.
    """
    tarball_name = get_archive_name()

    if os.environ.get("CLOAKBROWSER_DOWNLOAD_URL"):
        # Self-hosted mirror: signature scheme does not apply. Preserve the
        # legacy same-origin checksum behavior, skippable as before.
        if os.environ.get("CLOAKBROWSER_SKIP_CHECKSUM", "").lower() == "true":
            logger.warning(
                "CLOAKBROWSER_SKIP_CHECKSUM set — skipping verification for custom download URL"
            )
            return
        checksums = _fetch_checksums(version)
        if checksums is None:
            logger.warning(
                "SHA256SUMS not available from custom URL — skipping checksum verification"
            )
            return
        expected = checksums.get(tarball_name)
        if expected is None:
            logger.warning(
                "SHA256SUMS found but no entry for %s — skipping verification", tarball_name
            )
            return
        _verify_checksum(file_path, expected)
        return

    # Official path: signature is the trust root and is non-bypassable.
    manifest = _fetch_signed_manifest(version)
    if manifest is None:
        raise RuntimeError(
            "Could not fetch a signed SHA256SUMS (SHA256SUMS + SHA256SUMS.sig) "
            "for this release — refusing to use an unverified binary. "
            "Retry, or report at https://github.com/CloakHQ/cloakbrowser/issues"
        )
    manifest_bytes, sig_bytes = manifest
    _verify_signature(manifest_bytes, sig_bytes)
    manifest_text = manifest_bytes.decode("utf-8")

    # Version binding: the signed manifest must declare the version we asked for.
    # The signature proves "we made this manifest", not "this is the version you
    # requested" — without this check a mirror could serve a genuinely-signed
    # older release in place of the requested one (forced downgrade).
    requested = version or get_chromium_version()
    declared = _parse_manifest_version(manifest_text)
    if declared != requested:
        raise RuntimeError(
            f"Version mismatch in signed SHA256SUMS: requested {requested}, "
            f"manifest declares {declared or 'none'}. Refusing (possible downgrade)."
        )

    checksums = _parse_checksums(manifest_text)
    expected = checksums.get(tarball_name)
    if expected is None:
        raise RuntimeError(
            f"Signature-verified SHA256SUMS has no entry for {tarball_name} — "
            f"cannot confirm binary integrity."
        )
    _verify_checksum(file_path, expected)


def _parse_manifest_version(text: str) -> str | None:
    """Read the 'version=<v>' line from a signed manifest. None if absent.

    The line has no internal whitespace so older wrappers' SHA256SUMS parsers
    ignore it (they only accept '<hash>  <filename>' lines).
    """
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("version="):
            return line[len("version="):].strip()
    return None


def _fetch_signed_manifest(version: str | None = None) -> tuple[bytes, bytes] | None:
    """Fetch (SHA256SUMS, SHA256SUMS.sig) raw bytes for a version, or None.

    Both files are fetched from the SAME origin so the signature always matches
    the exact manifest bytes it certifies. The primary origin is tried first,
    then the GitHub Releases mirror. follow_redirects mirrors _fetch_checksums:
    cloakbrowser.dev 301-redirects /chromium-v* to GitHub Releases.
    """
    v = version or get_chromium_version()
    bases = [
        f"{DOWNLOAD_BASE_URL}/chromium-v{v}",
        f"{GITHUB_DOWNLOAD_BASE_URL}/chromium-v{v}",
    ]
    for base in bases:
        try:
            manifest_resp = httpx.get(
                f"{base}/SHA256SUMS", follow_redirects=True, timeout=10.0
            )
            manifest_resp.raise_for_status()
            sig_resp = httpx.get(
                f"{base}/SHA256SUMS.sig", follow_redirects=True, timeout=10.0
            )
            sig_resp.raise_for_status()
            return manifest_resp.content, sig_resp.content
        except Exception:
            continue
    return None


def _verify_signature(manifest_bytes: bytes, sig_b64: bytes) -> None:
    """Verify a detached Ed25519 signature over the raw manifest bytes.

    sig_b64 is the base64 of the 64-byte raw signature. Tries each pinned key
    in BINARY_SIGNING_PUBKEYS; succeeds if any validates. Raises RuntimeError
    if the signature is malformed or no pinned key validates it.
    """
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        signature = base64.b64decode(sig_b64.strip(), validate=True)
    except Exception as exc:
        raise RuntimeError(f"Malformed SHA256SUMS.sig (not valid base64): {exc}")

    for pubkey_b64 in BINARY_SIGNING_PUBKEYS:
        try:
            pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pubkey_b64))
        except Exception:
            # Skip an unparseable pinned key (e.g. the placeholder) rather than
            # aborting — another pinned key may still validate.
            continue
        try:
            pub.verify(signature, manifest_bytes)
            logger.info("SHA256SUMS signature verified: Ed25519 OK")
            return
        except Exception:
            # InvalidSignature, or a malformed/wrong-length signature that makes
            # verify raise something else — either way this key didn't match,
            # so try the next pinned key (and ultimately fail closed below).
            continue

    raise RuntimeError(
        "SHA256SUMS signature verification failed — no pinned key validated the "
        "manifest. The binary's authenticity could not be confirmed. "
        "Report at https://github.com/CloakHQ/cloakbrowser/issues"
    )


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
    """Parse SHA256SUMS format: '<64-hex sha256>  filename' per line.

    Only lines whose first token is a 64-character hex digest are accepted
    (matches the JS parser); blank lines, the version= line, and any other
    junk are ignored.
    """
    result = {}
    for line in text.strip().splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        hash_val, filename = parts
        hash_val = hash_val.lower()
        if len(hash_val) != 64 or any(c not in "0123456789abcdef" for c in hash_val):
            continue
        result[filename.lstrip("*")] = hash_val
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


def _download_file(url: str, dest: Path, headers: dict[str, str] | None = None) -> None:
    """Download a file with progress logging."""
    logger.info("Downloading from %s", url)

    with httpx.stream("GET", url, follow_redirects=True, timeout=DOWNLOAD_TIMEOUT, headers=headers or {}) as response:
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
    """Extract tar.gz or zip archive to destination directory."""
    logger.info("Extracting to %s", dest_dir)

    # Clean existing dir if partial download existed
    if dest_dir.exists():
        import shutil
        shutil.rmtree(dest_dir)

    dest_dir.mkdir(parents=True, exist_ok=True)

    if str(archive_path).endswith(".zip"):
        _extract_zip(archive_path, dest_dir)
    else:
        _extract_tar(archive_path, dest_dir)

    # If extracted into a single subdirectory, flatten it
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


def _extract_tar(archive_path: Path, dest_dir: Path) -> None:
    """Extract tar.gz archive with path traversal protection."""
    dest_resolved = dest_dir.resolve()
    with tarfile.open(archive_path, "r:gz") as tar:
        safe_members = []
        for member in tar.getmembers():
            # Allow symlinks — macOS .app bundles require them (Framework layout)
            if member.issym() or member.islnk():
                link_target = member.linkname
                if os.path.isabs(link_target) or ".." in link_target.split("/"):
                    logger.warning("Skipping suspicious symlink: %s -> %s", member.name, link_target)
                    continue
            else:
                member_path = (dest_dir / member.name).resolve()
                if not _path_is_relative_to(member_path, dest_resolved):
                    raise RuntimeError(f"Archive contains path traversal: {member.name}")
            safe_members.append(member)

        tar.extractall(dest_dir, members=safe_members)


def _extract_zip(archive_path: Path, dest_dir: Path) -> None:
    """Extract zip archive with path traversal protection."""
    import zipfile

    dest_resolved = dest_dir.resolve()
    with zipfile.ZipFile(archive_path, "r") as zf:
        for info in zf.infolist():
            member_path = (dest_dir / info.filename).resolve()
            if not _path_is_relative_to(member_path, dest_resolved):
                raise RuntimeError(f"Archive contains path traversal: {info.filename}")
        zf.extractall(dest_dir)


def _path_is_relative_to(path: Path, parent: Path) -> bool:
    """Return True only when path is inside parent."""
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


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
    if not path.is_file():
        return False
    if platform.system() == "Windows":
        pathext = os.environ.get("PATHEXT", ".COM;.EXE;.BAT;.CMD")
        executable_exts = {ext.lower() for ext in pathext.split(";") if ext}
        return path.suffix.lower() in executable_exts
    return os.access(path, os.X_OK)


def _make_executable(path: Path) -> None:
    """Make a file executable (chmod +x). Skipped on Windows (no-op / AV lock risk)."""
    if platform.system() == "Windows":
        return
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
    """Return info about the current binary installation.

    tier reflects what is actually installed on disk, not merely whether a
    license is cached — a cached license with no Pro binary downloaded yet is
    still effectively running the free binary, and the active key may differ
    from the cached one.
    """
    # Prefer Pro only if a Pro binary actually exists on disk.
    pro_version = get_effective_version(pro=True)
    pro_path = get_binary_path(pro_version, pro=True)
    pro = pro_path.exists() and _is_executable(pro_path)

    if pro:
        effective = pro_version
        binary_path = pro_path
    else:
        effective = get_effective_version()
        binary_path = get_binary_path(effective)
    download_url = f"{DOWNLOAD_BASE_URL}/api/download/latest" if pro else get_download_url(effective)
    return {
        "version": effective,
        "tier": "pro" if pro else "free",
        "bundled_version": CHROMIUM_VERSION,
        "platform": get_platform_tag(),
        "binary_path": str(binary_path),
        "installed": binary_path.exists(),
        "cache_dir": str(get_binary_dir(effective, pro=pro)),
        "download_url": download_url,
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
        platform_tarball = get_archive_name()
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


_wrapper_update_checked = False


def _check_wrapper_update() -> None:
    """Check PyPI for a newer wrapper version. Runs once per process."""
    global _wrapper_update_checked
    if _wrapper_update_checked:
        return
    _wrapper_update_checked = True
    if os.environ.get("CLOAKBROWSER_AUTO_UPDATE", "").lower() == "false":
        return
    if os.environ.get("CLOAKBROWSER_DOWNLOAD_URL"):
        return
    try:
        resp = httpx.get(
            "https://pypi.org/pypi/cloakbrowser/json",
            timeout=5.0,
        )
        resp.raise_for_status()
        latest = resp.json()["info"]["version"]
        if _version_newer(latest, _wrapper_version):
            logger.warning(
                "Update available: cloakbrowser %s → %s. "
                "Run: pip install --upgrade cloakbrowser",
                _wrapper_version,
                latest,
            )
    except Exception:
        logger.debug("Wrapper update check failed", exc_info=True)


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
    # Wrapper update: once per process, not rate-limited
    if not _wrapper_update_checked:
        t = threading.Thread(target=_check_wrapper_update, daemon=True)
        t.start()

    # Binary update: rate-limited to once per hour
    if not _should_check_for_update():
        return
    t = threading.Thread(target=_check_and_download_update, daemon=True)
    t.start()


def _maybe_trigger_pro_update_check(license_key: str) -> None:
    """Fire-and-forget Pro binary update check in a daemon thread."""
    check_file = get_cache_dir() / ".last_pro_update_check"
    if check_file.exists():
        try:
            last_check = float(check_file.read_text().strip())
            if time.time() - last_check < UPDATE_CHECK_INTERVAL:
                return
        except (ValueError, OSError):
            pass

    def _check():
        try:
            from .license import get_pro_latest_version

            check_file.parent.mkdir(parents=True, exist_ok=True)
            check_file.write_text(str(time.time()))

            latest = get_pro_latest_version()
            if not latest:
                return

            if get_binary_path(latest, pro=True).exists():
                return

            logger.info("Newer Pro binary available: %s. Downloading in background...", latest)
            _download_pro_binary(latest, license_key)

            marker = get_cache_dir() / f"latest_pro_version_{get_platform_tag()}"
            tmp = marker.with_suffix(".tmp")
            tmp.write_text(latest)
            os.replace(str(tmp), str(marker))
            logger.info("Pro background update complete: %s ready. Will use on next launch.", latest)
        except Exception:
            logger.debug("Pro background update failed", exc_info=True)

    t = threading.Thread(target=_check, daemon=True)
    t.start()
