"""License validation and caching for CloakBrowser Pro.

Handles license key resolution, server validation with local caching,
and Pro version checks.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import get_cache_dir, get_platform_tag, normalize_release_channel

logger = logging.getLogger("cloakbrowser")

VALIDATE_URL = "https://cloakbrowser.dev/api/license/validate"
PRO_VERSION_URL = "https://cloakbrowser.dev/api/download/version"
SESSION_COUNT_URL = "https://cloakbrowser.dev/api/license/session/count"
CLAIM_URL = "https://cloakbrowser.dev/api/license/free/claim"
# Fragment, not query: the claim code is a bearer secret and a fragment never
# reaches the server or CDN logs. The page reads it client-side.
FREE_CLAIM_LINK = "https://cloakbrowser.dev/#claim="

LICENSE_CACHE_TTL = 86400  # 24 hours
PRO_VERSION_CHECK_INTERVAL = 3600  # 1 hour


@dataclass
class SessionSeats:
    """Result of a seat lookup: the count, the cap it counts against, and the reason
    either is missing.

    state:
      "ok"          active is a real number (0 is a real answer, not an error)
      "unreachable" never got an answer — DNS, refused, timeout, TLS
      "denied"      the server refused; `reason` carries its error code
      "unknown"     the server is up and the key is fine, but it cannot count
                    right now (leaseless mode, or its seat store is unreachable)

    limit is None whenever the server declined to state a cap: unlimited, an
    unrecognised plan, or a server too old to send the field. Callers must fall back
    to the bare count, never invent a denominator.
    """

    active: int | None = None
    limit: int | None = None
    state: str = "ok"
    reason: str | None = None


@dataclass
class LicenseInfo:
    valid: bool
    plan: str
    expires: str | None


@dataclass(frozen=True)
class ProReleaseInfo:
    version: str
    requested_channel: str
    resolved_channel: str
    fallback: bool


def _release_from_sidecar(
    data: Mapping[str, object], version: str, channel: str
) -> ProReleaseInfo:
    """Build a ProReleaseInfo from a resolution-sidecar dict (snake_case, with a
    camelCase fallback for sidecars written by an older JS wrapper). A missing
    ``fallback`` defaults to ``requested != resolved`` — mirrors JS and .NET."""
    requested = str(data.get("requested_channel", data.get("requestedChannel", channel)))
    resolved = str(data.get("resolved_channel", data.get("resolvedChannel", "stable")))
    fallback = data.get("fallback")
    return ProReleaseInfo(
        version=version,
        requested_channel=requested,
        resolved_channel=resolved,
        fallback=bool(fallback) if fallback is not None else requested != resolved,
    )


class CloakBrowserLicenseError(RuntimeError):
    """The Pro binary refused to run for a license reason.

    Raised when a launch fails and the browser process exited with one of the
    Pro binary's license exit codes (see ``_LICENSE_EXIT_MESSAGES``). Carries a
    human-readable reason instead of the opaque "target/browser closed" error
    the caller would otherwise see.
    """


# Exit codes the Pro binary uses for honest-user license denials. The binary
# emits only the number (no diagnostic strings, by design); the message text
# lives here in the wrapper.
_LICENSE_EXIT_MESSAGES = {
    76: (
        "CloakBrowser Pro: session limit reached for your plan. Close another "
        "running session or upgrade your plan. Always close with "
        "browser.close() (e.g. in a finally block). A session that crashed or "
        "was killed frees its seat automatically within 4 min (free/trial/solo), "
        "15 min (team) or 30 min (business/scale)."
    ),
    77: (
        "CloakBrowser Pro: license key is invalid, expired, or missing. Check "
        "CLOAKBROWSER_LICENSE_KEY."
    ),
    78: (
        "CloakBrowser Pro: couldn't verify your license (license server "
        "unreachable or a connection problem)."
    ),
    79: (
        "CloakBrowser Pro: local configuration problem. Either ~/.cloakbrowser "
        "is not writable, or the --license-route value is invalid (use auto, "
        "direct, or proxy with a proxy set)."
    ),
}

# Playwright reports a child-process exit in the launch-failure text as
# "<process did exit: exitCode=N, signal=null>". Anchor to that record so an
# unrelated "exitCode=" elsewhere in the error can't false-match.
_EXIT_CODE_RE = re.compile(r"process did exit:\s*exitCode=(\d+)")


def license_error_message(error_text: str) -> str | None:
    """Map a launch-failure message to a license reason, or None.

    Returns the human message when the browser process exited with a known
    license exit code, else None so a genuine crash propagates unchanged.
    """
    match = _EXIT_CODE_RE.search(error_text or "")
    if not match:
        return None
    try:
        exit_code = int(match.group(1))
    except ValueError:
        return None
    return _LICENSE_EXIT_MESSAGES.get(exit_code)


# Env var the wrapper uses to tell the Pro binary where to record a license
# denial. A denial that resolves AFTER the CDP handshake (e.g. an over-cap seat)
# exits the browser once Playwright already holds a live connection, so the exit
# code never reaches the wrapper as a launch failure. The binary writes the code
# to this path just before exiting; the wrapper reads it when the user's next
# call fails. Old binaries ignore the unknown var and never write — so a missing
# file just means "behave as before".
LICENSE_STATUS_FILE_ENV = "CLOAKBROWSER_LICENSE_STATUS_FILE"


def license_error_for_code(code: int) -> CloakBrowserLicenseError | None:
    """Map a raw license exit code (76-79) to a CloakBrowserLicenseError.

    Returns None for any code that is not a known license denial, so a genuine
    crash is never mislabelled. Companion to ``license_error_message`` (which
    parses the code out of a launch-failure string); this takes the integer
    directly, for the post-handshake file-based path.
    """
    msg = _LICENSE_EXIT_MESSAGES.get(code)
    return CloakBrowserLicenseError(msg) if msg is not None else None


# Once a denial has been observed for a per-launch path, remember it. The read
# is destructive, so a second guarded call for the same launch (e.g. concurrent
# new_page + goto on a denied browser) would otherwise find the file already
# gone and miss the denial. Paths are unique per launch (uuid), so entries never
# collide across launches.
_OBSERVED_DENIALS: dict[str, int] = {}


def read_denial_file(path: str) -> int | None:
    """Read and consume a denial file written by the binary, returning its code.

    The file holds a single JSON integer (the license exit code). Reading is
    destructive: the file is unlinked afterwards so a later launch can't see a
    stale code, but the observed code is cached in-process so a concurrent
    second guarded call still surfaces the denial. Any problem — file absent,
    unreadable, or not a valid int — yields None, meaning "no license signal,
    treat as an ordinary error".
    """
    cached = _OBSERVED_DENIALS.get(path)
    if cached is not None:
        return cached
    # Fast path: the guard calls this after *every* browser call to catch a
    # denial that lands while calls still succeed, so the no-denial case (file
    # absent) must be cheap — a single stat, not an open()+except per call.
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            code = int(json.load(fh))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    _OBSERVED_DENIALS[path] = code
    return code


# A denial file is orphaned when the binary writes one but the user never calls
# a guarded method afterwards (e.g. just closes the browser). It is only ever
# consumed on a guarded call, so nothing else would remove it. Sweep leftovers
# older than this at mint time — long enough that a live in-flight denial from a
# concurrent launch is never deleted before its owner reads it.
_DENIAL_FILE_TTL_SECONDS = 3600


def _sweep_stale_denials(denial_dir: Path) -> None:
    """Best-effort removal of denial files older than the TTL. Never raises."""
    try:
        now = time.time()
        for f in denial_dir.glob("*.json"):
            try:
                if now - f.stat().st_mtime > _DENIAL_FILE_TTL_SECONDS:
                    f.unlink()
            except OSError:
                pass
    except OSError:
        pass


def mint_denial_file() -> str | None:
    """Return a fresh, unique path for the binary to write a denial code to.

    Only computes the path (and ensures the parent dir exists) — the file is
    created by the binary, and only on a denial, so a granted launch leaves
    nothing behind. Returns None if the directory can't be created (e.g.
    ``~/.cloakbrowser`` not writable), in which case the caller simply skips the
    feature; the fix must never break a launch.
    """
    try:
        denial_dir = Path.home() / ".cloakbrowser" / "denials"
        denial_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    _sweep_stale_denials(denial_dir)
    return str(denial_dir / f"{uuid.uuid4().hex}.json")


_LICENSE_KEY_SOURCE_PARAM = "param"
_LICENSE_KEY_SOURCE_ENV = "env"
_LICENSE_KEY_SOURCE_DEFAULT_FILE = "default_file"
_LICENSE_KEY_SOURCE_CUSTOM_FILE = "custom_file"
_LICENSE_KEY_SOURCE_NONE = "none"


def _resolve_license_key_with_source(
    license_key: str | None = None,
) -> tuple[str | None, str]:
    """Resolve license key with source tracking for env-injection decisions.

    Returns (key, source) where source is one of the _LICENSE_KEY_SOURCE_*
    constants. The source tells the caller *how* the key was found so they
    can decide whether env injection is needed (e.g. the binary reads the
    default file path directly, so env injection is unnecessary).
    """
    # 1. Explicit param
    if license_key and license_key.strip():
        return (license_key.strip(), _LICENSE_KEY_SOURCE_PARAM)

    # 2. Environment variable
    env_key = os.environ.get("CLOAKBROWSER_LICENSE_KEY", "").strip()
    if env_key:
        return (env_key, _LICENSE_KEY_SOURCE_ENV)

    # 3. File in the wrapper cache dir
    cache_dir = get_cache_dir()
    key_file = cache_dir / "license.key"
    try:
        content = key_file.read_text().strip()
        if content:
            default_cache = Path.home() / ".cloakbrowser"
            if cache_dir.resolve() == default_cache.resolve():
                source = _LICENSE_KEY_SOURCE_DEFAULT_FILE
            else:
                source = _LICENSE_KEY_SOURCE_CUSTOM_FILE
            return (content, source)
    except OSError:
        pass

    return (None, _LICENSE_KEY_SOURCE_NONE)


def resolve_license_key(license_key: str | None = None) -> str | None:
    """Resolve the license key: explicit param > env var > file > None."""
    key, _ = _resolve_license_key_with_source(license_key)
    return key


_KEY_RE = re.compile(r"cb_[A-Za-z0-9_-]+")
CLAIM_CODE_RE = re.compile(r"[A-Za-z0-9_-]{20,128}")  # the server's format
CLAIM_MAX_AGE = 7 * 86400


def _write_private(path: Path, text: str) -> None:
    """Write `text` to `path` readable by the owner only, from the first byte.

    The file is created 0600 before anything is written to it, then swapped into
    place, so neither the key nor the claim code is ever world-readable."""
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def save_license_key(key: str, *, overwrite: bool = True) -> bool:
    """Save a key to <cache>/license.key (0600) and retire the claim code.

    `overwrite=False` (the background claim poll) leaves an existing key alone:
    the user may have run `cloakbrowser login` meanwhile. Returns True if saved."""
    key = key.strip()
    if not _KEY_RE.fullmatch(key):
        raise ValueError("not a CloakBrowser license key")
    cache_dir = get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    key_file = cache_dir / "license.key"
    # The claim code keeps returning the key, so it is retired either way:
    # otherwise a later launch (say after `logout`) would silently re-save it.
    claim = cache_dir / ".free_claim"
    if not overwrite and key_file.exists():
        claim.unlink(missing_ok=True)
        return False
    _write_private(key_file, key + "\n")
    claim.unlink(missing_ok=True)
    return True


def get_claim_code() -> str:
    """This install's claim code, from <cache>/.free_claim (made 0600, 7-day life).

    Workers launching at once must print the same link, so the file is created
    exclusively and a loser of the race reads the winner's code."""
    cache_dir = get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / ".free_claim"
    try:
        if time.time() - path.stat().st_mtime < CLAIM_MAX_AGE:
            code = path.read_text().strip()
            if CLAIM_CODE_RE.fullmatch(code):
                return code
        path.unlink(missing_ok=True)  # expired or garbage: start over
    except OSError:
        pass
    code = secrets.token_urlsafe(32)
    tmp = path.with_name(f"{path.name}.{secrets.token_hex(8)}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(code)
    try:
        # Publish complete, without replacing: the first code wins and a reader
        # never sees a half-written file (same as the profile seed file).
        os.link(tmp, path)
    except FileExistsError:
        code = path.read_text().strip()
    except OSError:
        # ponytail: no hard links (FAT, some network mounts) -> plain replace;
        # a concurrent first launch there may print a different link.
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return code


def claim_link(code: str) -> str:
    return f"{FREE_CLAIM_LINK}{code}"


class FreeKeyAlreadyHeld(Exception):
    """The claim's email already has a free key. The server never sends an
    existing key to a claim (anyone can type anyone's email), so the person
    pastes it from the email they got it in."""


def check_claim(code: str) -> str | None:
    """One poll: the key once the claim's email is confirmed, else None.
    Raises FreeKeyAlreadyHeld (and retires the code) if that email has a key.

    The code goes in the body, never the URL: it is a bearer secret and URLs
    land in server logs."""
    try:
        resp = httpx.post(CLAIM_URL, json={"code": code}, timeout=5.0)
        data = resp.json() if resp.status_code == 200 else {}
    except (httpx.HTTPError, ValueError) as e:
        logger.debug("Free-key claim check failed: %s", e)
        return None
    if not isinstance(data, dict):  # e.g. a captive portal's JSON: just pending
        return None
    if data.get("status") == "has_key":
        # This code will only ever answer has_key: start fresh next time.
        (get_cache_dir() / ".free_claim").unlink(missing_ok=True)
        raise FreeKeyAlreadyHeld
    key = data.get("license_key") if data.get("status") == "ready" else None
    return key if isinstance(key, str) and _KEY_RE.fullmatch(key.strip()) else None


def poll_claim(code: str, *, interval: float = 15.0, deadline: float | None = None,
               overwrite: bool = False) -> str | None:
    """Poll until the key arrives (saved, then returned) or `deadline` passes.
    None if the deadline passed, or the key arrived but an existing key was kept
    (overwrite=False)."""
    while True:
        key = check_claim(code)
        if key:
            return key.strip() if save_license_key(key, overwrite=overwrite) else None
        if deadline is not None and time.time() + interval > deadline:
            return None
        time.sleep(interval)


def build_launch_env(
    license_key: str | None = None,
    user_env: Mapping[str, str | None] | None = None,
    status_file: str | None = None,
) -> dict[str, str] | None:
    """Build child process env dict with any needed license key injection.

    The Pro binary reads ``CLOAKBROWSER_LICENSE_KEY`` from its own process
    environment at startup.  This helper merges the resolved key into the
    child process env dict **only** when injection is necessary:

    * **param** or **custom_file** source -> inject the key into the child env
      (the binary cannot see the wrapper-only key or the custom file path).
    * **env** source -> the key is already in ``os.environ``, so the child
      inherits it naturally.  No injection.
    * **default_file** source -> the binary reads ``~/.cloakbrowser/license.key``
      directly, so injection is unnecessary (and keeps the key out of process
      env for security) — *unless* the caller passes a custom ``user_env``,
      which Playwright uses to replace (not merge) the child env; a replaced
      env can drop ``HOME`` and hide the file, so the key is injected then.
    * **none** -> no key at all, no injection.

    When *user_env* is provided (e.g. the caller passed ``env=`` via
    Playwright kwargs), it is used as the base instead of ``os.environ``,
    and the key is injected only when needed.

    When *status_file* is given, the denial-file path (see
    ``LICENSE_STATUS_FILE_ENV``) is added to the child env on every path — even
    the "inherit parent env" ones, which then have to become a full
    ``os.environ`` copy because Playwright *replaces* rather than merges the env.

    Returns ``None`` when no injection is needed and no custom user_env was
    given — Playwright treats ``env=None`` as "inherit parent env", which
    is correct in those cases.
    """
    key, source = _resolve_license_key_with_source(license_key)

    # Normalize the custom env once so every return path behaves identically:
    # drop None values (Playwright's env is typed str->str).
    base_env = (
        {k: v for k, v in user_env.items() if v is not None}
        if user_env is not None
        else None
    )

    result = _build_key_env(key, source, base_env)

    # Add the denial-status file path last so it rides along even on the
    # inherit-parent-env (result is None) paths. Only set when a caller asked
    # for it, which it only does when a license key is in play.
    if status_file is not None:
        if result is None:
            result = dict(os.environ)
        result[LICENSE_STATUS_FILE_ENV] = status_file

    return result


def _build_key_env(
    key: str | None, source: str, base_env: dict[str, str] | None
) -> dict[str, str] | None:
    """The license-key half of build_launch_env (unchanged behavior)."""
    # Default file: binary reads it directly — no env injection needed,
    # UNLESS the caller passes a custom env. Playwright replaces (not merges)
    # the child env, which can drop HOME and hide the file from the binary,
    # so inject the key too in that case (fall through to the merge below).
    if source == _LICENSE_KEY_SOURCE_DEFAULT_FILE and base_env is None:
        return None

    # No key at all: pass through the custom env or None.
    if source == _LICENSE_KEY_SOURCE_NONE or key is None:
        return base_env

    # Env source, no custom user env: child inherits parent env, which
    # already has CLOAKBROWSER_LICENSE_KEY.
    if source == _LICENSE_KEY_SOURCE_ENV and base_env is None:
        return None

    # Build the merged env dict.
    merged = dict(base_env) if base_env is not None else dict(os.environ)

    # For param/custom_file this is THE injection into the child env.
    # For env source with a custom user_env this ensures the key persists
    # through the user's env override (Playwright replaces, not merges).
    merged["CLOAKBROWSER_LICENSE_KEY"] = key

    return merged


def validate_license(license_key: str) -> LicenseInfo | None:
    """Validate a license key with the CloakBrowser server.

    Checks a local file cache first (24h TTL). Falls back to stale
    cache if the server is unreachable.

    Returns LicenseInfo if validation succeeded, None on total failure.
    """
    cache_path = get_cache_dir() / ".license_cache"
    key_sha = hashlib.sha256(license_key.encode()).hexdigest()

    cached = _read_cache(cache_path, key_sha)
    if cached:
        return cached

    try:
        resp = httpx.post(
            VALIDATE_URL,
            json={"license_key": license_key},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()

        info = LicenseInfo(
            valid=data.get("valid", False),
            plan=data.get("plan", "solo"),
            expires=data.get("expires"),
        )

        if info.valid:
            _write_cache(cache_path, key_sha, info)
        return info

    except Exception as e:
        logger.warning("License validation request failed: %s", e)

        stale = _read_cache(cache_path, key_sha, ignore_ttl=True)
        if stale:
            logger.warning("Using cached license validation (server unreachable)")
            return stale

        return None


def get_pro_latest_release(
    release_channel: str | None = None,
) -> ProReleaseInfo | None:
    """Get the server-resolved Pro release and channel for this platform."""
    channel = normalize_release_channel(release_channel)
    marker_suffix = (
        f"preview_{get_platform_tag()}"
        if channel == "preview"
        else get_platform_tag()
    )
    marker = get_cache_dir() / f".last_pro_version_check_{marker_suffix}"
    resolution_marker = get_cache_dir() / f".last_pro_version_resolution_{marker_suffix}"

    if marker.exists():
        try:
            age = time.time() - marker.stat().st_mtime
            if age < PRO_VERSION_CHECK_INTERVAL and resolution_marker.exists():
                data = json.loads(resolution_marker.read_text())
                version = marker.read_text().strip()
                if version and data.get("version") == version:
                    return _release_from_sidecar(data, version, channel)
        except (OSError, ValueError, TypeError):
            pass

    try:
        version_url = (
            f"{PRO_VERSION_URL}?channel=preview"
            if channel == "preview"
            else PRO_VERSION_URL
        )
        resp = httpx.get(
            version_url,
            headers={"X-Platform": get_platform_tag()},
            timeout=10.0,
        )
        resp.raise_for_status()
        data = resp.json()
        version = data.get("version")
        if not version:
            return None
        resolved_channel = str(data.get("resolved_channel", "stable"))
        release = ProReleaseInfo(
            version=str(version),
            requested_channel=str(data.get("requested_channel", channel)),
            resolved_channel=resolved_channel,
            fallback=bool(
                data.get("fallback", channel != resolved_channel)
            ),
        )

        marker.parent.mkdir(parents=True, exist_ok=True)
        resolution_tmp = resolution_marker.with_suffix(".tmp")
        resolution_tmp.write_text(json.dumps(release.__dict__))
        os.replace(str(resolution_tmp), str(resolution_marker))
        tmp = marker.with_suffix(".tmp")
        tmp.write_text(release.version)
        os.replace(str(tmp), str(marker))
        return release

    except Exception as e:
        logger.debug("Pro version check failed: %s", e)
        try:
            version = marker.read_text().strip()
            if not version:
                return None
            # Prefer the last successful fetch's channel metadata (the resolution
            # sidecar) so an offline preview build is not mislabeled as a stable
            # fallback. Older wrappers left only the version marker, so its channel
            # is unknowable — hardcode a conservative stable fallback then.
            if resolution_marker.exists():
                try:
                    data = json.loads(resolution_marker.read_text())
                    if data.get("version") == version:
                        return _release_from_sidecar(data, version, channel)
                except (OSError, ValueError, TypeError):
                    pass
            return ProReleaseInfo(version, channel, "stable", channel == "preview")
        except OSError:
            pass
        return None


def get_pro_latest_version(release_channel: str | None = None) -> str | None:
    """Get only the version from the server-resolved Pro release."""
    release = get_pro_latest_release(release_channel)
    return release.version if release else None


def get_session_seats(license_key: str) -> SessionSeats:
    """Seats held right now, the cap they count against, and why either is missing.

    Deliberately NOT cached: a cached seat count is a wrong seat count.

    Six different things can stop us answering — no route to the host, a timeout, a
    403 for a dead key, a 429, the server reporting the count as unknown in leaseless
    mode, and its seat store being unreachable. They used to collapse into one bare
    None, so `info` printed the same "unavailable" for "your key is dead" and "our
    backend is degraded, you are fine". `state` keeps them apart.
    """
    try:
        resp = httpx.post(
            SESSION_COUNT_URL,
            json={"license_key": license_key},
            timeout=10.0,
        )
    except Exception as e:
        # Never reached the server: DNS, refused, timed out, TLS.
        logger.debug("Session count lookup unreachable: %s", e)
        return SessionSeats(state="unreachable")

    if resp.status_code >= 400:
        # The server answered, and the answer was a refusal. Its `error` field is the
        # actionable part (invalid_key / license_inactive / rate_limited); fall back to
        # the status when the body is missing or not JSON.
        reason = None
        try:
            reason = resp.json().get("error")
        except Exception:
            pass
        reason = reason or f"HTTP {resp.status_code}"
        logger.debug("Session count denied: %s", reason)
        return SessionSeats(state="denied", reason=reason)

    try:
        body = resp.json()
    except Exception as e:
        logger.debug("Session count body unparseable: %s", e)
        return SessionSeats(state="unknown")

    active = body.get("active")
    if not isinstance(active, int) or isinstance(active, bool):
        # 200 with active=null is the server saying "up, your key is fine, but I
        # genuinely cannot count right now" — deliberate, so it never reports a false 0.
        return SessionSeats(state="unknown")

    limit = body.get("limit")
    if not isinstance(limit, int) or isinstance(limit, bool):
        # Absent (older server) or null (unlimited / unknown plan). Callers fall back
        # to the bare count rather than printing a made-up denominator.
        limit = None
    return SessionSeats(active=active, limit=limit, state="ok")


def get_active_session_count(license_key: str) -> int | None:
    """How many concurrent sessions (seats) this license is holding right now.

    Kept for callers outside `info` that only want the number. Prefer
    get_session_seats(), which also carries the cap and the reason a lookup failed.
    """
    return get_session_seats(license_key).active


def _read_cache(
    cache_path: Path, key_sha: str, ignore_ttl: bool = False
) -> LicenseInfo | None:
    """Read cached license validation if it exists and is fresh."""
    try:
        if not cache_path.exists():
            return None

        data = json.loads(cache_path.read_text())

        if data.get("key_sha256") != key_sha:
            return None

        if not ignore_ttl:
            validated_at = data.get("validated_at", 0)
            if time.time() - validated_at > LICENSE_CACHE_TTL:
                return None

        expires = data.get("expires")
        if expires:
            try:
                from datetime import datetime, timezone
                exp_dt = datetime.fromisoformat(expires)
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if exp_dt < datetime.now(timezone.utc):
                    return LicenseInfo(valid=False, plan=data.get("plan", "solo"), expires=expires)
            except (ValueError, TypeError):
                pass

        return LicenseInfo(
            valid=data.get("valid", False),
            plan=data.get("plan", "solo"),
            expires=expires,
        )
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        # TypeError: a corrupted cache with a non-numeric validated_at. Treat any
        # unreadable cache as absent rather than crashing the caller.
        return None


def _write_cache(cache_path: Path, key_sha: str, info: LicenseInfo) -> None:
    """Write license validation result to local cache (atomic via tmp+rename)."""
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps({
            "key_sha256": key_sha,
            "valid": info.valid,
            "plan": info.plan,
            "expires": info.expires,
            "validated_at": time.time(),
        }))
        os.replace(str(tmp_path), str(cache_path))
    except OSError as e:
        logger.debug("Failed to write license cache: %s", e)
