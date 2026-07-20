"""CLI for cloakbrowser — download and manage the stealth Chromium binary.

Usage:
    python -m cloakbrowser install      # Download binary (with progress)
    python -m cloakbrowser info         # Environment + binary diagnostics
    python -m cloakbrowser doctor       # Alias for `info`
    python -m cloakbrowser update       # Check for and download newer binary
    python -m cloakbrowser clear-cache  # Remove cached binaries
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import os
import platform
import subprocess
import sys

UPGRADE_HINT = "→ Try the latest Pro binary (Chromium 150) free for 7 days: https://cloakbrowser.dev"


def _setup_logging() -> None:
    """Route cloakbrowser logger to stderr with clean output."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        stream=sys.stderr,
        force=True,
    )
    # Suppress noisy HTTP request logs from httpx
    logging.getLogger("httpx").setLevel(logging.WARNING)


def cmd_install(args: argparse.Namespace) -> None:
    from .download import ensure_binary

    path = ensure_binary()
    print(path)


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _binary_version(binary_path: str) -> tuple[bool, str, str]:
    """Launch `<binary> --version` to prove it runs. Returns (ok, version, err)."""
    try:
        result = subprocess.run(
            [binary_path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, "", str(exc)
    if result.returncode != 0:
        return False, "", (result.stderr or result.stdout).strip()
    return True, result.stdout.strip(), ""


def _missing_shared_libs(binary_path: str) -> list[str]:
    """Linux-only: ldd the binary and return missing .so names (empty otherwise)."""
    if platform.system() != "Linux":
        return []
    try:
        result = subprocess.run(
            ["ldd", "--", binary_path],  # -- so a path starting with - isn't read as a flag
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    missing = []
    for line in result.stdout.splitlines():
        if "=> not found" in line:
            missing.append(line.split("=>")[0].strip())
    return missing


def _resolve_license() -> tuple[dict, bool]:
    """Resolve + validate the license the way ensure_binary does.

    Returns (license_section, entitled_to_pro). Network call (validate) only
    happens when a key is actually present.
    """
    from .license import resolve_license_key, validate_license

    key = resolve_license_key(None)
    # ensure_binary disables Pro routing when a custom download URL is set, so the
    # diagnostic must report free too (matches download.py).
    if os.environ.get("CLOAKBROWSER_DOWNLOAD_URL"):
        key = None
    if not key:
        return {"tier": "free"}, False
    try:
        lic = validate_license(key)
    except Exception as exc:
        return {"tier": "unknown", "error": str(exc)}, False
    if lic is None:
        return {"tier": "unknown", "error": "could not validate"}, False
    if lic.valid:
        return {"tier": lic.plan, "valid": True, "expires": lic.expires}, True
    return {"tier": "invalid", "valid": False}, False


def _effective_binary(entitled_pro: bool, quick: bool = False) -> dict:
    """Describe the binary ensure_binary would actually launch (no download).

    Mirrors ensure_binary's resolution (override > version pin > license tier).
    Unlike binary_info(), a Pro binary on disk is only reported when the license
    entitles Pro — so a keyless run correctly shows the free binary even if a
    Pro binary is cached.
    """
    from .config import (
        CHROMIUM_VERSION,
        get_binary_dir,
        get_binary_path,
        get_effective_version,
        get_local_binary_override,
        normalize_requested_version,
    )

    override = get_local_binary_override()
    if override:
        return {
            "version": None,
            "latest_version": None,
            "pinned": False,
            "tier": "override",
            "bundled_version": CHROMIUM_VERSION,
            "path": override,
            "installed": os.path.isfile(override),
            "cache_dir": None,
            "override": override,
        }

    requested = normalize_requested_version(None)

    # For a Pro license, surface the server's latest separately from the version
    # that will actually launch, so `info` can never silently diverge from launch
    # (the divergence a customer hit: info showed latest, launch ran a stale cache).
    # --quick keeps `info` fully network-free (skip the server latest lookup).
    latest_version = None
    if entitled_pro and not quick:
        from .license import get_pro_latest_version

        latest_version = get_pro_latest_version()

    if requested:
        version = requested
    elif entitled_pro:
        # "Will launch now" is the cached Pro build; if none is cached, the next
        # launch downloads latest_version. get_effective_version(pro=True) returns
        # None (never the free base) when nothing is cached.
        version = get_effective_version(pro=True) or latest_version
    else:
        version = get_effective_version()

    path = get_binary_path(version, pro=entitled_pro) if version else None
    return {
        "version": version,
        "latest_version": latest_version,
        "pinned": bool(requested),
        "tier": "pro" if entitled_pro else "free",
        "bundled_version": CHROMIUM_VERSION,
        "path": str(path) if path else None,
        "installed": bool(path) and path.exists(),
        "cache_dir": str(get_binary_dir(version, pro=entitled_pro)) if version else None,
        "override": None,
    }


def _collect_diagnostics(quick: bool) -> dict:
    """Gather environment + binary diagnostics without triggering a download."""
    diag: dict = {}

    diag["environment"] = {
        "python": sys.version.split()[0],
        "os": platform.system(),
        "arch": platform.machine(),
    }

    # Resolve the license up front — it decides which binary actually launches
    # (ensure_binary only uses the Pro binary when a key validates). Computed
    # before the binary section, displayed after it.
    license_info, entitled_pro = _resolve_license()

    # Live seat count — a Pro-only extra lookup, so gated exactly like the server
    # latest-version check below: --quick keeps `info` network-free, and a free
    # tier holds no seats. Never cached (a cached count is a wrong count).
    if entitled_pro and not quick:
        from .license import get_active_session_count, resolve_license_key

        key = resolve_license_key(None)
        if key:
            license_info["sessions"] = {"active": get_active_session_count(key)}

    from .config import get_platform_tag

    try:
        diag["environment"]["platform_tag"] = get_platform_tag()
    except Exception as exc:
        diag["environment"]["platform_tag"] = f"unavailable ({exc})"

    try:
        diag["binary"] = _effective_binary(entitled_pro, quick=quick)
    except Exception as exc:  # platform unsupported, etc.
        diag["binary"] = {"error": str(exc)}

    # Launch test — prove the binary actually executes (skipped by --quick).
    binary = diag["binary"].get("path")
    installed = diag["binary"].get("installed")
    if quick:
        diag["launch"] = {"tested": False, "reason": "skipped (--quick)"}
    elif not binary or not (installed or (binary and os.path.isfile(binary))):
        diag["launch"] = {"tested": False, "reason": "binary not installed"}
    else:
        ok, version, err = _binary_version(binary)
        diag["launch"] = {"tested": True, "ok": ok, "version": version, "error": err}
        if not ok:
            diag["launch"]["missing_libs"] = _missing_shared_libs(binary)

    # Windows-font probe — only meaningful on a Linux host spoofing Windows.
    # Omitted entirely off Linux, where it carries no signal.
    if platform.system() == "Linux":
        from .browser import (
            _OFFICE_FONT_TELLS,
            _WINDOWS_FONT_TELLS,
            _count_fonts_present,
        )

        # Strict count, not "any one present" — real font installs are atomic
        # (you have the whole pack or none), so report how complete the set is.
        win_n = _count_fonts_present(_WINDOWS_FONT_TELLS)
        office_n = _count_fonts_present(_OFFICE_FONT_TELLS)
        diag["fonts"] = {
            "windows": None if win_n is None else [win_n, len(_WINDOWS_FONT_TELLS)],
            "office": None if office_n is None else [office_n, len(_OFFICE_FONT_TELLS)],
        }

    diag["license"] = license_info

    # GeoIP DB — presence only, never downloads.
    from .geoip import GEOIP_DB_FILENAME, _get_geoip_dir

    db_path = _get_geoip_dir() / GEOIP_DB_FILENAME
    diag["geoip"] = {"db_present": db_path.exists(), "path": str(db_path)}

    # Optional Python modules.
    diag["modules"] = {
        label: _module_available(module)
        for label, module in {
            "playwright": "playwright.sync_api",
            "geoip2": "geoip2.database",
            "aiohttp": "aiohttp",
            "websockets": "websockets",
        }.items()
    }

    return diag


def _print_diagnostics(diag: dict) -> None:
    """Render the diagnostics dict as a human-readable report."""
    env = diag["environment"]
    print("CloakBrowser diagnostics")
    print(f"Python:    {env['python']}")
    print(f"OS:        {env['os']} {env['arch']}")
    print(f"Platform:  {env.get('platform_tag', 'unknown')}")

    binary = diag["binary"]
    if "error" in binary:
        print(f"Binary:    unavailable ({binary['error']})")
    else:
        if binary["tier"] == "override":
            print("Version:   set via CLOAKBROWSER_BINARY_PATH (see Launch line)")
        else:
            latest = binary.get("latest_version")
            if latest:
                # Pro: show what launches now AND the server's latest, so the two
                # can never silently diverge.
                print(f"Version:   {binary['version']} ({binary['tier']}) — will launch")
                if latest == binary["version"]:
                    print(f"Latest:    {latest} (up to date)")
                elif binary.get("pinned"):
                    print(
                        f"Latest:    {latest} (available — pinned; unset "
                        "CLOAKBROWSER_VERSION to upgrade)"
                    )
                else:
                    print(f"Latest:    {latest} (available — next launch upgrades)")
            elif binary["version"] is None:
                # Pro with no cached build and no server answer (e.g. offline).
                print(
                    f"Version:   not downloaded yet ({binary['tier']}) "
                    "— next launch downloads the latest"
                )
            else:
                print(f"Version:   {binary['version']} ({binary['tier']})")
        print(f"Binary:    {binary['path']}")
        print(f"Installed: {binary['installed']}")
        if binary.get("cache_dir"):
            print(f"Cache:     {binary['cache_dir']}")
        if binary.get("override"):
            print(f"Override:  {binary['override']} (CLOAKBROWSER_BINARY_PATH)")

    launch = diag["launch"]
    if not launch.get("tested"):
        print(f"Launch:    {launch['reason']}")
    elif launch["ok"]:
        print(f"Launch:    ✓ {launch['version']}")
    else:
        print(f"Launch:    ✗ failed — {launch['error']}")
        for lib in launch.get("missing_libs", []):
            print(f"           missing: {lib}")
        if launch.get("missing_libs"):
            print("           → install the missing system libraries (e.g. apt-get install)")

    if "fonts" in diag:
        win = diag["fonts"]["windows"]
        if win is None:
            print("Win fonts: unknown (fc-list unavailable)")
        else:
            n, total = win
            verdict = "ok" if n == total else "missing" if n == 0 else "partial"
            print(f"Win fonts: {verdict} ({n}/{total})")
            if n < total:
                print("           → incomplete Windows font set; copy real Windows fonts (Segoe UI, Calibri, Consolas)")
        office = diag["fonts"].get("office")
        if office is not None:
            n, total = office
            # Office is informational only — no Office pack is a normal Windows
            # persona (~53% of real machines have none), so no install nudge.
            verdict = "ok" if n == total else "absent" if n == 0 else "partial"
            print(f"Office fonts: {verdict} ({n}/{total})")

    lic = diag["license"]
    tier = lic["tier"]
    if tier == "free":
        print("License:   Free")
        print(f"           {UPGRADE_HINT}")
    elif "error" in lic:
        print(f"License:   {tier} ({lic['error']})")
    else:
        print(f"License:   {tier}")

    if "sessions" in lic:
        active = lic["sessions"]["active"]
        if active is None:
            print("Sessions:  unavailable")
        else:
            print(f"Sessions:  {active} seat{'' if active == 1 else 's'} in use")

    geoip = diag["geoip"]
    print(f"GeoIP DB:  {'present' if geoip['db_present'] else 'not downloaded (optional)'}")

    print("Modules:")
    for label, available in diag["modules"].items():
        print(f"  {label}: {'ok' if available else 'missing'}")


def cmd_info(args: argparse.Namespace) -> None:
    quick = getattr(args, "quick", False)
    diag = _collect_diagnostics(quick=quick)
    if getattr(args, "json", False):
        import json

        print(json.dumps(diag, indent=2))
    else:
        _print_diagnostics(diag)


def cmd_update(args: argparse.Namespace) -> None:
    from .download import check_for_pro_update, check_for_update

    logger = logging.getLogger("cloakbrowser")
    logger.info("Checking for updates...")

    # A valid Pro license updates the Pro binary; everyone else updates free.
    _, entitled_pro = _resolve_license()
    if entitled_pro:
        from .license import resolve_license_key

        new_version = check_for_pro_update(resolve_license_key(None))
        label = "Pro Chromium"
    else:
        new_version = check_for_update()
        label = "Chromium"

    if new_version:
        print(f"Updated to {label} {new_version}")
    else:
        print("Already up to date.")


def cmd_clear_cache(args: argparse.Namespace) -> None:
    from .config import get_cache_dir
    from .download import clear_cache

    if not get_cache_dir().exists():
        print("No cache to clear.")
        return
    clear_cache()
    print("Cache cleared.")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cloakbrowser",
        description="Manage the CloakBrowser stealth Chromium binary.",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("install", help="Download the Chromium binary")

    def _add_info_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--quick",
            "--no-launch",
            action="store_true",
            dest="quick",
            help="Skip the binary launch test (faster; the license is still validated)",
        )
        p.add_argument("--json", action="store_true", help="Emit diagnostics as JSON")

    _add_info_flags(sub.add_parser("info", help="Environment + binary diagnostics"))
    _add_info_flags(sub.add_parser("doctor", help="Alias for info"))
    sub.add_parser("update", help="Check for and download a newer binary")
    sub.add_parser("clear-cache", help="Remove all cached binaries")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(2)

    _setup_logging()

    commands = {
        "install": cmd_install,
        "info": cmd_info,
        "doctor": cmd_info,
        "update": cmd_update,
        "clear-cache": cmd_clear_cache,
    }

    try:
        commands[args.command](args)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
