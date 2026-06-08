"""Widevine CDM hint-file seeding for persistent contexts.

CloakBrowser's binary is built with Widevine support but ships no CDM (the CDM
is a proprietary Google binary we can't redistribute). Users sideload it by
copying a ``WidevineCdm/`` directory from a real Chrome install next to the
binary (see issue #96).

Chromium discovers a sideloaded CDM in two phases: an early-startup pass that
reads a "hint file" from the user-data-dir, and a later async component-updater
pass that writes that hint file. On a fresh profile the hint file doesn't exist
on the first launch, and Playwright passes ``--disable-component-update``, so the
updater never writes it — Widevine only works after a manual two-launch dance.

This module pre-seeds the hint file before launch so a sideloaded CDM works on
the very first launch. It never bundles, downloads, or copies the CDM itself —
it only writes the hint when a CDM the user provided is already present.

Linux only: Chromium's hint-file mechanism is Linux/ChromeOS-specific. On Windows
the CDM can't initialise (DRM host verification), and macOS uses a different CDM
layout, so seeding is a no-op there.
"""

from __future__ import annotations

import json
import logging
import os
import platform
from pathlib import Path

logger = logging.getLogger("cloakbrowser")

# Chromium reads this file from <user-data-dir>/WidevineCdm/ at early startup.
_HINT_FILENAME = "latest-component-updated-widevine-cdm"


def _seeding_disabled() -> bool:
    """True if CLOAKBROWSER_WIDEVINE is set to a falsey value (kill switch)."""
    val = os.environ.get("CLOAKBROWSER_WIDEVINE", "").strip().lower()
    return val in ("0", "false", "off", "no")


def resolve_widevine_cdm_dir(binary_path: str | os.PathLike) -> Path | None:
    """Locate a sideloaded Widevine CDM directory, or None if absent.

    Resolution:
      - If CLOAKBROWSER_WIDEVINE_CDM is set, it is used **exclusively** (overrides
        auto-detection). An invalid value (no ``manifest.json``) skips seeding.
      - Otherwise, ``<dir of the chrome binary>/WidevineCdm`` — where a user
        naturally drops it, and where it ends up for both downloaded and
        CLOAKBROWSER_BINARY_PATH (local build / Docker mount) binaries.

    A directory counts only if it contains ``manifest.json`` (so we don't seed a
    hint pointing at a bogus path). The returned path is absolute and
    symlink-resolved (``Path.resolve()``).
    """
    custom = os.environ.get("CLOAKBROWSER_WIDEVINE_CDM")
    # `is not None` (not truthiness): a present-but-empty env var is "set" and
    # used exclusively — it resolves to an invalid path and skips seeding.
    cdm_dir = Path(custom) if custom is not None else Path(os.fspath(binary_path)).parent / "WidevineCdm"
    return cdm_dir.resolve() if (cdm_dir / "manifest.json").is_file() else None


def seed_widevine_hint(user_data_dir: str | os.PathLike, binary_path: str | os.PathLike) -> None:
    """Write the Widevine CDM hint file into a persistent profile before launch.

    ``binary_path`` is the resolved chrome executable; the CDM is looked for next
    to it. No-op on non-Linux platforms, when seeding is disabled via
    CLOAKBROWSER_WIDEVINE, or when no sideloaded CDM is present. Never raises —
    a failure here must not break the browser launch.
    """
    if platform.system() != "Linux":
        return
    if _seeding_disabled():
        logger.debug("Widevine hint seeding disabled via CLOAKBROWSER_WIDEVINE")
        return
    if not user_data_dir:
        # Empty user_data_dir = Playwright's ephemeral profile (its own temp dir);
        # a persistent hint can't be placed there, and "" would pollute the CWD.
        return

    # Everything below is best-effort and must never break the browser launch,
    # so the whole body (resolution + write) is guarded.
    try:
        cdm_dir = resolve_widevine_cdm_dir(binary_path)
        if cdm_dir is None:
            if os.environ.get("CLOAKBROWSER_WIDEVINE_CDM") is not None:
                logger.warning(
                    "CLOAKBROWSER_WIDEVINE_CDM is set but has no manifest.json; "
                    "skipping Widevine hint seeding"
                )
            else:
                logger.debug("No sideloaded Widevine CDM found; skipping hint seeding")
            return

        hint_dir = Path(os.fspath(user_data_dir)) / "WidevineCdm"
        hint_dir.mkdir(parents=True, exist_ok=True)
        hint_file = hint_dir / _HINT_FILENAME
        # cdm_dir is already absolute/resolved. Compact separators + ensure_ascii=False
        # byte-match the JS wrapper's JSON.stringify (UTF-8) output.
        content = json.dumps({"Path": str(cdm_dir)}, separators=(",", ":"), ensure_ascii=False)

        try:
            if hint_file.is_file() and hint_file.read_text(encoding="utf-8") == content:
                return  # already seeded correctly
        except Exception:
            logger.warning("Existing Widevine hint unreadable; rewriting")

        hint_file.write_text(content, encoding="utf-8")
        logger.info("Seeded Widevine CDM hint -> %s", cdm_dir)
    except Exception as e:
        logger.warning("Failed to seed Widevine CDM hint file: %s", e)
