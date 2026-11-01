"""Binary download and cache management for cloakbrowser.

Downloads the patched Chromium binary on first use, caches it locally.
Similar to how Playwright downloads its own bundled Chromium.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import platform
import stat
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from pathlib import Path

import httpx

from ._version import __version__ as _wrapper_version
from .config import (
    BINARY_SIGNING_PUBKEYS,
    DOWNLOAD_BASE_URL,
    _version_newer,
    get_archive_ext,
    get_archive_name,
    get_binary_dir,
    get_binary_path,
    get_cache_dir,
    get_effective_version,
    get_local_binary_override,
    get_platform_tag,
    normalize_release_channel,
    normalize_requested_version,
)

logger = logging.getLogger("cloakbrowser")


class BinaryVerificationError(RuntimeError):
    """A downloaded binary could not be authenticated (bad/missing signature,
    version mismatch, or checksum failure).

    Distinct from transient download/network errors: a verification failure is
    a tampering signal and MUST surface, never silently fall back to another
    binary. The routing in ensure_binary re-raises this rather than falling
    back to a cached build.
    """


# Timeout for download (large binary, allow 10 min)
DOWNLOAD_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=10.0)

# Free-key welcome banner re-show interval (1 day). Free users see the
# "more sessions" invite again after this gap; Pro users see it only once
# (see _show_welcome).
WELCOME_FREE_INTERVAL = 24 * 3600

# Attempts to rename an extraction into place while concurrent callers are
# replacing the same partial install (see _extract_archive).
INSTALL_RENAME_ATTEMPTS = 5

# Retries for a directory rename that Windows transiently denies (see
# _rename_dir_with_retry): about 2.5 seconds in total.
TRANSIENT_RENAME_ATTEMPTS = 10
TRANSIENT_RENAME_DELAY = 0.25


def _welcome_due(marker: Path, pro: bool) -> bool:
    """Whether the welcome banner should be shown now.

    Pro: once ever (only when the marker is absent). Free: re-show when the
    marker is absent or its timestamp is older than WELCOME_FREE_INTERVAL.
    Unreadable or legacy empty markers count as stale (due).
    """
    if not marker.exists():
        return True
    if pro:
        return False
    try:
        last = int(marker.read_text().strip())
    except (OSError, ValueError):
        return True
    return (time.time() - last) >= WELCOME_FREE_INTERVAL


_preview_fallback_warned = False


def _warn_preview_fallback() -> None:
    """Tell the user, once per process, that a requested Preview build does not
    exist for this platform and the Stable build is being used instead."""
    global _preview_fallback_warned
    if _preview_fallback_warned:
        return
    _preview_fallback_warned = True
    # Write straight to stderr (like the welcome banner) so an app's logging
    # config can't silence it.
    sys.stderr.write(
        "[cloakbrowser] Preview channel requested, but no preview build is "
        f"available for {get_platform_tag()}; using the stable build.\n"
    )


def _emit(text: str) -> None:
    """Write a cosmetic line to stderr, swallowing any error.

    On a legacy Windows console sys.stderr is cp1252/strict; an unencodable
    glyph raises UnicodeEncodeError. Because the welcome banner runs on the
    binary-download path, that would abort the whole launch.
    A banner is decoration - never let it propagate.
    """
    try:
        sys.stderr.write(text)
    except Exception:
        pass


def _show_welcome(tier: str) -> None:
    """Show welcome message on launch. A marker file gates the cadence: a paid
    (Pro) key shows once ever; a free key re-shows every WELCOME_FREE_INTERVAL.

    tier:
      "pro"  — a paid license key (Pro banner + support address)
      "free" — a free key (latest binary, one concurrent session)
    """
    marker = get_cache_dir() / ".welcome_shown"
    if not _welcome_due(marker, pro=(tier == "pro")):
        return
    # ASCII-only banner + a swallow-everything writer: on a legacy Windows
    # console sys.stderr is cp1252/strict, so a non-ASCII glyph (or any IO
    # error) here would raise and abort the whole binary-download path. A
    # cosmetic banner must never be able to kill a launch.
    _emit("\n")
    _emit("  CloakBrowser - stealth Chromium for automation\n")
    if tier == "pro":
        _emit("  CloakBrowser Pro active.\n\n")
        _emit("  Pro support -> support@cloakbrowser.dev\n")
        _emit("  Site -> https://cloakbrowser.dev\n")
    else:
        _emit("  CloakBrowser free: 1 concurrent session.\n\n")
        _emit("  For more than one concurrent session -> https://cloakbrowser.dev\n")
    _emit("  Docs -> https://github.com/CloakHQ/CloakBrowser\n")
    _emit("  Star us if CloakBrowser helps your project!\n")
    _emit("\n")
    _mark_welcome_shown()


def _mark_welcome_shown() -> None:
    marker = get_cache_dir() / ".welcome_shown"
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(str(int(time.time())))
    except OSError:
        pass


def ensure_binary(
    license_key: str | None = None,
    browser_version: str | None = None,
    release_channel: str | None = None,
) -> str:
    """Ensure the stealth Chromium binary is available. Download if needed.

    Returns the path to the chrome executable as a string.

    Args:
        license_key: Pro license key. Also reads from CLOAKBROWSER_LICENSE_KEY env var.
        browser_version: Exact Chromium version pin. Also reads from CLOAKBROWSER_VERSION.
        release_channel: Stable (default) or Preview binary channel.

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

    requested_version = normalize_requested_version(browser_version)

    from .license import CloakBrowserLicenseError, resolve_license_key, validate_license

    # No key anywhere (param, env, license.key) -> get a free one first.
    key = resolve_license_key(license_key) or _claim_free_key()
    info = validate_license(key)
    if info and info.valid:
        _maybe_trigger_update_check()
        # A free key always gets the latest build. Drop any version pin: the
        # server force-serves latest to free keys, so fetching a pinned
        # version's signed manifest would mismatch the served bytes and fail
        # checksum verification. Paid keys keep pinning/rollback.
        if info.plan == "free":
            requested_version = None
        # (A blip during a routine update never reaches the error below:
        # _ensure_pro_binary returns the cached build and retries next launch.)
        try:
            return _ensure_pro_binary(
                key,
                requested_version=requested_version,
                plan=info.plan,
                release_channel=release_channel,
            )
        except BinaryVerificationError:
            # Authenticity could not be confirmed — surface verbatim.
            raise
        except Exception as e:
            raise RuntimeError(
                f"CloakBrowser binary unavailable: {e}. Your license is valid but "
                f"the binary could not be downloaded right now. Retry in a moment."
            ) from e
    if info:
        raise CloakBrowserLicenseError(
            f"CloakBrowser: license key is invalid or expired (plan={info.plan}). "
            f"Check CLOAKBROWSER_LICENSE_KEY or ~/.cloakbrowser/license.key, or get "
            f"a free key with: cloakbrowser login"
        )
    raise CloakBrowserLicenseError(
        "CloakBrowser: license could not be validated (server unreachable and "
        "no cached validation). Retry in a moment."
    )


# How long a background claim poll keeps checking for the key (see _claim_free_key).
CLAIM_POLL_WINDOW = 600
_claim_poll_started = False


def _isatty(stream) -> bool:
    try:
        return stream.isatty()
    except (AttributeError, ValueError, OSError):  # None (pythonw) or closed
        return False


def can_prompt() -> bool:
    """A person is at this terminal and Ctrl+C reaches us (main thread)."""
    return (
        threading.current_thread() is threading.main_thread()
        and _isatty(sys.stdin)
        and _isatty(sys.stderr)
    )


def _ask(prompt: str) -> str:
    # Prompt on stderr: a script's stdout may be its data.
    _emit(prompt)
    return input().strip()


def _emit_welcome() -> None:
    _emit("\n  Welcome to CloakBrowser - stealth Chromium for automation\n")
    _emit("  https://github.com/CloakHQ/CloakBrowser\n\n")
    _emit("  CloakBrowser needs a license key.\n\n")


def prompt_license_key() -> str:
    """Terminal menu shared by a no-key launch and `cloakbrowser login`: get a
    free key by email or paste one. Returns a valid key, already saved.

    Raises EOFError if stdin closes, KeyboardInterrupt on Ctrl+C."""
    _emit_welcome()
    _emit("    1) Get a free key (by email: the latest build, 1 concurrent session)\n")
    _emit("    2) Paste a key I already have\n\n")
    while True:
        choice = _ask("  Choose 1 or 2 [1]: ")
        if choice in ("", "1"):
            key = _get_free_key()
            if key:
                return key
            _emit(f"\n  {HAS_KEY_MSG}\n")
        elif choice != "2":
            _emit("  Please type 1 or 2.\n")
            continue
        key = _paste_key()
        if key:
            return key


HAS_KEY_MSG = (
    "This email already has a free key. It's in the email we sent when you "
    "first got it (search your mail for CloakBrowser)."
)


def _paste_key() -> str | None:
    """Ask until a valid key is pasted (saved, returned) or the answer is empty."""
    from .license import _KEY_RE, save_license_key, validate_license

    while True:
        key = _ask("  Paste your key (empty to go back): ")
        if not key:
            return None
        if not _KEY_RE.fullmatch(key):
            _emit("  That is not a CloakBrowser key (they start with cb_).\n")
            continue
        info = validate_license(key)
        if info is None:
            _emit("  Could not reach the license server. Check your connection and retry.\n")
        elif not info.valid:
            _emit("  That key is invalid or expired.\n")
        else:
            save_license_key(key)
            _emit("  Key saved.\n\n")
            if info.plan == "free":
                _mark_welcome_shown()  # the menu was the welcome; a paid key keeps its Pro banner
            return key


def _get_free_key() -> str | None:
    """Open the claim link and wait for the key (saved, returned). None if the
    email already has a key, which the server never sends to a claim."""
    from .license import FreeKeyAlreadyHeld, claim_link, get_claim_code, poll_claim

    code = get_claim_code()
    link = claim_link(code)
    _emit(f"\n  Open this link and enter your email:\n  {link}\n")
    if _has_display():
        import webbrowser

        try:
            if webbrowser.open(link):
                _emit("  (opened in your browser)\n")
        except (webbrowser.Error, OSError) as e:
            logger.debug("Could not open a browser: %s", e)
    _emit("\n  Waiting for you to confirm your email... (Ctrl+C to stop)\n")
    try:
        key = poll_claim(code, overwrite=True)
    except FreeKeyAlreadyHeld:
        return None
    _emit("  Free key saved.\n\n")
    _mark_welcome_shown()  # the menu was the welcome: no second banner this launch
    return key


def _claim_free_key() -> str:
    """No key anywhere: get one before launching.

    A person at a terminal (main thread) gets the menu (prompt_license_key).
    Anything else (CI, Docker, an MCP server, launch_async's worker thread, where
    Ctrl+C can't reach) raises with the claim link and keeps polling in the
    background, so a long-lived process picks the key up and its next launch works."""
    from .license import (
        CloakBrowserLicenseError,
        FreeKeyAlreadyHeld,
        check_claim,
        claim_link,
        get_claim_code,
        save_license_key,
    )

    code = get_claim_code()
    try:
        key = check_claim(code)
    except FreeKeyAlreadyHeld:
        if not can_prompt():
            raise CloakBrowserLicenseError(
                f"{HAS_KEY_MSG} Set CLOAKBROWSER_LICENSE_KEY or run: cloakbrowser login"
            ) from None
        key = None  # the menu below starts over with a fresh code
    if key:  # confirmed since an earlier launch printed the link
        save_license_key(key, overwrite=False)
        return key
    if can_prompt():
        try:
            return prompt_license_key()
        except EOFError:
            pass  # stdin closed mid-menu: fall through to the link + error
        except KeyboardInterrupt:
            # The person at the menu chose to stop: exit quietly like the JS and
            # .NET wrappers (130 = Ctrl+C), not with a traceback.
            _emit("\n")
            raise SystemExit(130) from None
    code = get_claim_code()  # fresh if the old one was retired
    link = claim_link(code)
    _emit_welcome()
    _emit(f"  Get one free (the latest build, 1 concurrent session):\n  {link}\n"
          "  After you confirm, the key is also emailed to you.\n\n")
    _start_claim_poll(code)
    raise CloakBrowserLicenseError(
        f"No CloakBrowser license key. Get one free: {link} "
        "(or run: cloakbrowser login), then launch again."
    )


def _has_display() -> bool:
    """Whether opening a browser can show a window. On Linux/BSD without a
    display (typically SSH), webbrowser falls back to a text browser (lynx,
    w3m) that takes over this terminal, so skip it: the link is printed anyway.
    The same reason gh and gcloud print the URL instead on remote hosts."""
    if sys.platform in ("darwin", "win32"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


_claim_poll_lock = threading.Lock()


def _start_claim_poll(code: str) -> None:
    """Poll for the claimed key in a daemon thread, once per process."""
    global _claim_poll_started
    with _claim_poll_lock:  # concurrent launch_async calls: one poller only
        if _claim_poll_started:
            return
        _claim_poll_started = True
    from .license import FreeKeyAlreadyHeld, poll_claim

    def run() -> None:
        try:
            if poll_claim(code, deadline=time.time() + CLAIM_POLL_WINDOW):
                _emit("\n  CloakBrowser: free key saved. The next launch uses it.\n")
        except FreeKeyAlreadyHeld:
            _emit(f"\n  CloakBrowser: {HAS_KEY_MSG}\n  Set CLOAKBROWSER_LICENSE_KEY or run: cloakbrowser login\n")
        except (OSError, ValueError) as e:
            logger.warning("Could not save the claimed free key: %s", e)

    threading.Thread(target=run, daemon=True).start()


def _pro_binary_ready(version: str | None) -> bool:
    """True when a cached, executable Pro binary exists for ``version``."""
    if not version:
        return False
    path = get_binary_path(version)
    return path.exists() and _is_executable(path)


def _ensure_pro_binary(
    license_key: str,
    requested_version: str | None = None,
    plan: str | None = None,
    release_channel: str | None = None,
) -> str:
    """Ensure the latest (keyed) binary is downloaded and cached. Returns its path.

    Used for both free keys (plan="free") and paid keys — both fetch the same
    latest build; the server enforces the concurrency cap. If the latest build
    cannot be resolved or downloaded and none is cached, the error is raised.
    """
    from .license import get_pro_latest_release, get_pro_latest_version

    # Banner tier: a free key gets the free banner, paid keys the Pro one.
    welcome_tier = "free" if plan == "free" else "pro"

    # --- Pinned: launch the exact requested version, no server cross-check, no
    # marker write (a rollback pin must not stick future unpinned launches). ---
    if requested_version:
        if _pro_binary_ready(requested_version):
            binary_path = get_binary_path(requested_version)
            logger.debug(
                "Pinned Pro binary found in cache: %s (version %s)",
                binary_path,
                requested_version,
            )
            _show_welcome(welcome_tier)
            return str(binary_path)
        logger.info(
            "Downloading Pro Chromium %s for %s...", requested_version, get_platform_tag()
        )
        _download_pro_binary(requested_version, license_key)
        binary_path = get_binary_path(requested_version)
        if not binary_path.exists():
            raise RuntimeError(
                f"Pro download completed but binary not found at: {binary_path}"
            )
        _show_welcome(welcome_tier)
        return str(binary_path)

    # --- Unpinned: track the server's latest selected channel. ---
    effective = get_effective_version(release_channel)

    # Honor CLOAKBROWSER_AUTO_UPDATE=false: if the user froze updates AND a build
    # is already cached, keep it and skip the server check. With no cached build
    # we must still fetch one. (The `update` CLI ignores this and always acts.)
    frozen = os.environ.get("CLOAKBROWSER_AUTO_UPDATE", "").lower() == "false"
    if frozen and _pro_binary_ready(effective):
        logger.debug("Pro auto-update disabled; using cached %s", effective)
        _show_welcome(welcome_tier)
        return str(get_binary_path(effective))

    # get_pro_latest_version() is rate-limited to one network call per hour and
    # returns a cached string in between, so this foreground check stays cheap on
    # steady-state launches while still landing the selected release after a version gap.
    latest = get_pro_latest_version(release_channel)

    # Tell the user when they asked for Preview but the server has no preview
    # build for this platform, so the Stable build is used instead. The lookup is
    # a cache hit (get_pro_latest_version above already populated it), so this
    # only touches the network on the once-an-hour refresh.
    if normalize_release_channel(release_channel) == "preview":
        release = get_pro_latest_release(release_channel)
        if release is not None and release.fallback:
            _warn_preview_fallback()

    # Prefer the server's latest when it is newer than — or replaces a missing —
    # the cached build. Otherwise stay on the cached Pro binary (fast, offline-ok).
    if latest and (
        effective is None
        or not _pro_binary_ready(effective)
        or _version_newer(latest, effective)
    ):
        version: str | None = latest
    else:
        version = effective

    if version is None:
        # Valid Pro license but nothing resolvable (server unreachable AND no
        # cached build) — fail loudly.
        raise RuntimeError("Could not determine latest Pro version from server")

    if _pro_binary_ready(version):
        binary_path = get_binary_path(version)
        # Advance the marker if this cached build is newer than what the marker names,
        # so `info` (and a later server-outage launch) reflect the build we actually
        # launch — never a stale marker.
        if version != effective:
            try:
                _write_pro_version_marker(version, release_channel)
            except OSError:
                pass
        logger.debug("Pro binary found in cache: %s (version %s)", binary_path, version)
        _show_welcome(welcome_tier)
        return str(binary_path)

    # `version` (the server latest) needs downloading. On failure, fall back to a
    # cached build if we have one.
    try:
        logger.info(
            "Downloading Pro Chromium %s for %s...", version, get_platform_tag()
        )
        _download_pro_binary(version, license_key)
    except BinaryVerificationError:
        # A tampering signal must surface verbatim — never mask it behind the
        # cached-Pro fallback, which is only for transient download failures.
        raise
    except Exception:
        if _pro_binary_ready(effective):
            logger.warning(
                "Pro update to %s failed; launching cached Pro binary %s",
                version,
                effective,
            )
            _show_welcome(welcome_tier)
            return str(get_binary_path(effective))
        raise

    binary_path = get_binary_path(version)
    if not binary_path.exists():
        raise RuntimeError(
            f"Pro download completed but binary not found at: {binary_path}"
        )

    # Advance the marker so future unpinned launches use this build.
    try:
        _write_pro_version_marker(version, release_channel)
    except OSError:
        pass

    _show_welcome(welcome_tier)
    return str(binary_path)


def _download_pro_binary(version: str, license_key: str) -> None:
    """Download a Pro binary from cloakbrowser.dev with license key auth.

    Requests the explicit version so the served archive matches the signed
    manifest verified in _verify_pro_download.
    """
    download_url = f"{DOWNLOAD_BASE_URL}/api/download/{version}"
    binary_dir = get_binary_dir(version)
    binary_path = get_binary_path(version)
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

        # Non-bypassable Ed25519 signature check (M1 defense); no env var skips it.
        _verify_pro_download(tmp_path, version)

        _extract_archive(tmp_path, binary_dir, binary_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _verify_pro_download(file_path: Path, version: str) -> None:
    """Verify a downloaded archive with a non-bypassable Ed25519 signature check.

    A tampered same-origin SHA256SUMS could otherwise certify a tampered
    binary (M1, #308). Fetch the Pro SHA256SUMS + detached
    SHA256SUMS.sig, verify the signature against the pinned keys FIRST, bind the
    manifest to the requested version, then verify the archive's SHA-256.

    An invalid signature, checksum, or version mismatch raises
    BinaryVerificationError (a tampering signal the router surfaces verbatim);
    Nothing can bypass it. A failed manifest FETCH is
    transient — nothing was validated — and raises a plain RuntimeError.
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
        ) from exc

    manifest_bytes = manifest_resp.content
    # _verify_signature / _verify_checksum raise plain RuntimeError; convert to
    # BinaryVerificationError so the router treats them as tampering signals
    # (re-raise) rather than transient failures (fall back to a cached build).
    try:
        _verify_signature(manifest_bytes, sig_resp.content)
    except RuntimeError as exc:
        raise BinaryVerificationError(str(exc)) from exc
    manifest_text = manifest_bytes.decode("utf-8")

    # Version binding: the signature proves "we made this manifest", not "this
    # is the version you asked for" — without this a genuinely-signed older
    # release could be served in place of the requested one (forced downgrade).
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


def _parse_manifest_version(text: str) -> str | None:
    """Read the 'version=<v>' line from a signed manifest. None if absent.

    The line has no internal whitespace so older wrappers' SHA256SUMS parsers
    ignore it (they only accept '<hash>  <filename>' lines).
    """
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("version="):
            return line[len("version=") :].strip()
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
        raise RuntimeError(
            f"Malformed SHA256SUMS.sig (not valid base64): {exc}"
        ) from exc

    for pubkey_b64 in BINARY_SIGNING_PUBKEYS:
        try:
            pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(pubkey_b64))
        except Exception:
            # Skip an unparsable pinned key (e.g. the placeholder) rather than
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
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
    except OSError:
        logger.error("Failed to read downloaded file for checksum: %s", file_path)
        raise
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

    with httpx.stream(
        "GET",
        url,
        follow_redirects=True,
        timeout=DOWNLOAD_TIMEOUT,
        headers=headers or {},
    ) as response:
        response.raise_for_status()

        try:
            total = int(response.headers.get("content-length", 0))
        except (TypeError, ValueError):
            total = 0
        downloaded = 0
        last_logged_pct = -1

        try:
            with open(dest, "wb") as f:
                for chunk in response.iter_bytes(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)

                    if total > 0:
                        pct = downloaded * 100 // total
                        # Log every 10%
                        if pct >= last_logged_pct + 10:
                            last_logged_pct = pct
                            logger.info(
                                "Download progress: %d%% (%d/%d MB)",
                                pct,
                                downloaded // (1024 * 1024),
                                total // (1024 * 1024),
                            )
        except OSError:
            logger.error("Failed to write downloaded file: %s", dest)
            raise

    logger.info("Download complete: %d MB", dest.stat().st_size // (1024 * 1024))


def _extract_archive(archive_path: Path, dest_dir: Path, binary_path: Path) -> None:
    """Extract tar.gz or zip archive to destination directory."""
    logger.info("Extracting to %s", dest_dir)
    bp = binary_path

    # Extract into a private sibling dir, then rename it into place. Concurrent
    # first runs (in this process or others) each get their own staging dir, so
    # none of them can see or delete another's half-written install.
    staging_dir = dest_dir.with_name(f"{dest_dir.name}.partial-{uuid.uuid4().hex}")
    staging_dir.mkdir()
    stale_dirs: list[Path] = []
    try:
        if str(archive_path).endswith(".zip"):
            _extract_zip(archive_path, staging_dir)
        else:
            _extract_tar(archive_path, staging_dir)

        # If extracted into a single subdirectory, flatten it
        # (e.g. fingerprint-chromium-142-custom-v2/chrome → chrome)
        # But never flatten .app bundles: macOS needs the bundle structure intact
        _flatten_single_subdir(staging_dir)

        # Make binary executable
        staged_binary_path = staging_dir / bp.relative_to(dest_dir)
        if staged_binary_path.exists():
            _make_executable(staged_binary_path)

        # macOS: remove quarantine/provenance xattrs to prevent Gatekeeper prompts
        if platform.system() == "Darwin":
            _remove_quarantine(staging_dir)

        for attempt in range(1, INSTALL_RENAME_ATTEMPTS + 1):
            try:
                _rename_dir_with_retry(staging_dir, dest_dir)
                break
            except OSError:
                # dest_dir is in the way. Keep it if another caller finished a complete
                # install; replace it if it is an incomplete leftover, such as an
                # interrupted in-place extraction from an older release.
                if bp.exists() and _is_executable(bp):
                    break
                if attempt == INSTALL_RENAME_ATTEMPTS:
                    raise
            # Rename the leftover aside before deleting it. Deleting it in place races
            # other callers renaming their extraction into dest_dir.
            stale_dir = dest_dir.with_name(f"{dest_dir.name}.stale-{uuid.uuid4().hex}")
            try:
                _rename_dir_with_retry(dest_dir, stale_dir)
            except FileNotFoundError:
                continue  # another caller moved it aside first
            stale_dirs.append(stale_dir)
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        for stale_dir in stale_dirs:
            shutil.rmtree(stale_dir, ignore_errors=True)

    if bp.exists():
        logger.info("Binary ready: %s", bp)


def _rename_dir_with_retry(source: Path, destination: Path) -> None:
    """Rename a directory, retrying while Windows reports it as in use."""
    for attempt in range(1, TRANSIENT_RENAME_ATTEMPTS + 1):
        try:
            source.rename(destination)
            return
        except PermissionError:
            # Windows antivirus briefly holds freshly written files open, which fails the
            # rename with access denied. An existing destination is not transient.
            if (
                platform.system() != "Windows"
                or attempt == TRANSIENT_RENAME_ATTEMPTS
                or destination.exists()
            ):
                raise
            time.sleep(TRANSIENT_RENAME_DELAY)


def _extract_tar(archive_path: Path, dest_dir: Path) -> None:
    """Extract tar.gz. Archive is signature-verified before extraction, so unpack
    as-is. filter="fully_trusted" pins legacy behavior (3.14 defaults to "data",
    which mangles macOS .app symlinks/perms); fallback covers Python < 3.12."""
    with tarfile.open(archive_path, "r:gz") as tar:
        try:
            tar.extractall(dest_dir, filter="fully_trusted")
        except TypeError:
            tar.extractall(dest_dir)


def _extract_zip(archive_path: Path, dest_dir: Path) -> None:
    """Extract zip. Signature-verified before extraction, so unpack as-is."""
    import zipfile

    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(dest_dir)


def _flatten_single_subdir(dest_dir: Path) -> None:
    """If extraction created a single subdirectory, move its contents up.

    Many tar archives wrap files in a top-level directory (e.g.
    fingerprint-chromium-142-custom-v2/chrome). We want chrome at dest_dir/chrome.
    """
    entries = list(dest_dir.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        subdir = entries[0]
        # Never flatten .app bundles — macOS needs the bundle structure
        if subdir.name.endswith(".app"):
            logger.debug("Keeping .app bundle intact: %s", subdir.name)
            return
        logger.debug("Flattening single subdirectory: %s", subdir.name)
        try:
            for item in subdir.iterdir():
                shutil.move(str(item), str(dest_dir / item.name))
            subdir.rmdir()
        except OSError:
            logger.error("Failed to flatten extracted directory: %s", subdir)
            raise


def _is_executable(path: Path) -> bool:
    """Check if a file is executable."""
    try:
        return os.access(path, os.X_OK)
    except OSError:
        logger.error("Failed to check executable permissions: %s", path)
        return False


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

    cache_dir = get_cache_dir()
    if cache_dir.exists():
        try:
            shutil.rmtree(cache_dir)
        except OSError:
            logger.error("Failed to clear cache: %s", cache_dir)
            raise
        logger.info("Cache cleared: %s", cache_dir)


def binary_info(
    browser_version: str | None = None,
    release_channel: str | None = None,
) -> dict:
    """Return info about the cached binary installation.

    browser_version (or CLOAKBROWSER_VERSION) pins the reported version so the
    info matches what a pinned launch actually runs, instead of latest. version
    is None until a build has been downloaded.
    """
    version = normalize_requested_version(browser_version) or get_effective_version(
        release_channel
    )
    download_url = f"{DOWNLOAD_BASE_URL}/api/download/latest"
    if normalize_release_channel(release_channel) == "preview":
        download_url += "?channel=preview"
    return {
        "version": version,
        "platform": get_platform_tag(),
        "binary_path": str(get_binary_path(version)) if version else None,
        "installed": _pro_binary_ready(version),
        "cache_dir": str(get_binary_dir(version)) if version else None,
        "download_url": download_url,
    }


# ---------------------------------------------------------------------------
# Auto-update
# ---------------------------------------------------------------------------


def check_for_pro_update(
    license_key: str, release_channel: str | None = None
) -> str | None:
    """Move a Pro install to the selected channel's latest. Blocks until complete.

    Returns the new version when a newer Pro build is downloaded or an
    already-cached newer build is activated, else None (already up to date or the
    server could not be reached). Requires a valid Pro license key.
    """
    from .license import get_pro_latest_version

    latest = get_pro_latest_version(release_channel)
    if not latest:
        return None

    effective = get_effective_version(release_channel)
    if effective and not _version_newer(latest, effective) and _pro_binary_ready(
        effective
    ):
        # Already on the latest cached Pro build.
        return None

    if not _pro_binary_ready(latest):
        logger.info("Downloading Pro Chromium %s...", latest)
        _download_pro_binary(latest, license_key)
        binary_path = get_binary_path(latest)
        if not binary_path.exists():
            raise RuntimeError(
                f"Pro download completed but binary not found at: {binary_path}"
            )

    _write_pro_version_marker(latest, release_channel)
    return latest


def _write_pro_version_marker(
    version: str, release_channel: str | None = None
) -> None:
    """Atomically write the selected channel's Pro version marker."""
    cache_dir = get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    channel = normalize_release_channel(release_channel)
    marker_prefix = (
        "latest_pro_version_preview"
        if channel == "preview"
        else "latest_pro_version"
    )
    marker = cache_dir / f"{marker_prefix}_{get_platform_tag()}"
    tmp = marker.with_suffix(".tmp")
    tmp.write_text(version)
    os.replace(str(tmp), str(marker))


_wrapper_update_checked = False


def _check_wrapper_update() -> None:
    """Check PyPI for a newer wrapper version. Runs once per process."""
    global _wrapper_update_checked
    if _wrapper_update_checked:
        return
    _wrapper_update_checked = True
    if os.environ.get("CLOAKBROWSER_AUTO_UPDATE", "").lower() == "false":
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
                "Update available: cloakbrowser %s -> %s. "
                "Run: pip install --upgrade cloakbrowser",
                _wrapper_version,
                latest,
            )
    except Exception:
        logger.debug("Wrapper update check failed", exc_info=True)


def _maybe_trigger_update_check() -> None:
    """Fire-and-forget wrapper update check (once per process) in a daemon thread.

    The binary itself updates on the launch path (_ensure_pro_binary)."""
    if not _wrapper_update_checked:
        threading.Thread(target=_check_wrapper_update, daemon=True).start()
