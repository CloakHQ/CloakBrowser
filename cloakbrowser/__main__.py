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


def _console_glyph(glyph: str, fallback: str) -> str:
    """Return an ASCII stand-in when the console can't encode `glyph`.

    Windows consoles default to cp850/cp1252, which carry none of the marks
    below — printing one there raises UnicodeEncodeError and aborts the report
    partway through. UTF-8 consoles keep the glyph.
    """
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        glyph.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return fallback
    return glyph


MARK_OK = _console_glyph("✓", "OK")
MARK_FAIL = _console_glyph("✗", "x")
ARROW = _console_glyph("→", "->")
DASH = _console_glyph("—", "-")

UPGRADE_HINT = f"For more than one concurrent session {ARROW} https://cloakbrowser.dev"
FREE_LATEST_HINT = (
    f"Get the latest binary free {ARROW} run 'cloakbrowser login' "
    "or https://cloakbrowser.dev/free"
)


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
    """Launch `<binary> --version` to prove it runs. Returns (ok, version, err).

    Chromium only handles --version on POSIX, so on Windows the switch is ignored
    and a browser starts instead of printing — the probe then times out and a
    healthy install looks broken. --no-startup-window makes it exit right away
    without putting a window on screen; a broken binary still exits non-zero, so
    the check keeps its meaning. It just reports no version there, as nothing is
    printed.
    """
    argv = [binary_path, "--version"]
    if platform.system() == "Windows":
        argv.append("--no-startup-window")
    try:
        result = subprocess.run(
            argv,
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
        _version_newer,
        get_binary_dir,
        get_binary_path,
        get_effective_version,
        get_local_binary_override,
        normalize_release_channel,
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
    requested_channel = normalize_release_channel(None)

    # For a Pro license, surface the server's latest separately from the version
    # that will actually launch, so `info` can never silently diverge from launch
    # (the divergence a customer hit: info showed latest, launch ran a stale cache).
    # --quick keeps `info` fully network-free (skip the server latest lookup).
    latest_version = None
    resolved_channel = None
    channel_fallback = False
    if entitled_pro and not quick:
        from .license import get_pro_latest_release

        latest_release = get_pro_latest_release(requested_channel)
        if latest_release:
            latest_version = latest_release.version
            resolved_channel = latest_release.resolved_channel
            channel_fallback = latest_release.fallback

    installed_version = None
    if requested:
        version = requested
    elif entitled_pro:
        # Mirror ensure_binary: Preview/Stable resolution picks what the next
        # launch will run, while AUTO_UPDATE=false keeps an installed channel build.
        installed_version = get_effective_version(
            pro=True, release_channel=requested_channel
        )
        auto_update = os.environ.get("CLOAKBROWSER_AUTO_UPDATE", "true").lower()
        updates_enabled = auto_update != "false"
        if installed_version and not updates_enabled:
            version = installed_version
        elif latest_version and (
            not installed_version or _version_newer(latest_version, installed_version)
        ):
            version = latest_version
        else:
            version = installed_version or latest_version
    else:
        version = get_effective_version()
        installed_version = version

    path = get_binary_path(version, pro=entitled_pro) if version else None
    return {
        "version": version,
        "latest_version": latest_version,
        "requested_channel": requested_channel,
        "resolved_channel": resolved_channel,
        "channel_fallback": channel_fallback,
        "installed_version": installed_version,
        "pinned": bool(requested),
        "tier": "pro" if entitled_pro else "free",
        "bundled_version": CHROMIUM_VERSION,
        "path": str(path) if path else None,
        "installed": bool(path) and path.exists(),
        "cache_dir": str(get_binary_dir(version, pro=entitled_pro)) if version else None,
        "override": None,
    }


def _collect_diagnostics(quick: bool, proxy: str | None = None) -> dict:
    """Gather environment + binary diagnostics.

    Does not trigger a download unless ``proxy`` is given: with a proxy, the
    exit IP + timezone + locale a launch would apply are resolved (which caches
    the GeoIP DB if absent, exactly like a real launch).
    """
    diag: dict = {}

    from ._version import __version__

    diag["environment"] = {
        "wrapper": __version__,
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
        from .license import get_session_seats, resolve_license_key

        key = resolve_license_key(None)
        if key:
            seats = get_session_seats(key)
            license_info["sessions"] = {
                "active": seats.active,
                "limit": seats.limit,
                "state": seats.state,
                "reason": seats.reason,
            }

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

    # Live resolution — only when a proxy is explicitly given. Mirrors launch():
    # resolves the exit IP and, computing tz/locale, caches the DB if absent.
    if proxy:
        try:
            from .geoip import resolve_proxy_geo_with_ip

            tz, locale, exit_ip = resolve_proxy_geo_with_ip(proxy)
            diag["geoip"]["resolved"] = {
                "exit_ip": exit_ip,
                "timezone": tz,
                "locale": locale,
            }
        except ImportError:
            diag["geoip"]["resolved"] = {"error": "geoip2 not installed"}
        except Exception as exc:  # network/proxy failure — never crash `info`
            diag["geoip"]["resolved"] = {"error": str(exc)}

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


# Server error codes → the words a customer can act on. Anything unrecognised is
# printed verbatim rather than swallowed, so a new server code still says something.
_SEAT_DENIAL_REASONS = {
    "invalid_key": "invalid key",
    "license_inactive": "license inactive",
    "rate_limited": "rate limited",
}


def _format_seats(sessions: dict) -> str:
    """Render the seat lookup. Kept identical in the JS and .NET wrappers."""
    state = sessions.get("state", "ok")
    if state == "unreachable":
        return "unavailable (cannot reach cloakbrowser.dev)"
    if state == "denied":
        reason = sessions.get("reason") or "refused"
        return f"unavailable ({_SEAT_DENIAL_REASONS.get(reason, reason)})"
    if state != "ok" or sessions.get("active") is None:
        # The server is up and the key is fine — it just cannot count right now.
        return "unavailable (server cannot report seats right now)"

    active = sessions["active"]
    limit = sessions.get("limit")
    if limit is None:
        # No cap to show (unlimited, unrecognised plan, or a server predating the
        # field). Fall back to the bare count — never print "N/unknown".
        return f"{active} seat{'' if active == 1 else 's'} in use"
    return f"{active}/{limit} in use"


def _print_diagnostics(diag: dict) -> None:
    """Render the diagnostics dict as a human-readable report."""
    env = diag["environment"]
    print("CloakBrowser diagnostics")
    print(f"Wrapper:   {env['wrapper']}")
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
            requested_channel = binary.get("requested_channel", "stable")
            resolved_channel = binary.get("resolved_channel")
            if binary.get("channel_fallback"):
                print(f"Channel:   Preview {ARROW} Stable fallback")
            elif resolved_channel:
                print(f"Channel:   {resolved_channel.capitalize()}")
            else:
                print(f"Channel:   {requested_channel.capitalize()}")
            latest = binary.get("latest_version")
            if latest:
                # Pro: show what launches now AND the server's latest, so the two
                # can never silently diverge.
                print(f"Version:   {binary['version']} ({binary['tier']}) {DASH} next launch")
                if latest == binary["version"] and binary.get("installed"):
                    print(f"Latest:    {latest} (up to date)")
                elif latest == binary["version"]:
                    print(f"Latest:    {latest} (downloads on next launch)")
                elif binary.get("pinned"):
                    print(
                        f"Latest:    {latest} (available {DASH} pinned; unset "
                        "CLOAKBROWSER_VERSION to upgrade)"
                    )
                else:
                    print(f"Latest:    {latest} (server-resolved; installed build retained)")
                installed_version = binary.get("installed_version")
                if installed_version and installed_version != binary["version"]:
                    print(f"Installed: {installed_version}")
            elif binary["version"] is None:
                # Pro with no cached build and no server answer (e.g. offline).
                print(
                    f"Version:   not downloaded yet ({binary['tier']}) "
                    f"{DASH} next launch downloads the latest"
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
        # Windows prints nothing, so say it ran rather than show an empty version.
        print(f"Launch:    {MARK_OK} {launch['version'] or 'runs (no version reported on Windows)'}")
    else:
        print(f"Launch:    {MARK_FAIL} failed {DASH} {launch['error']}")
        for lib in launch.get("missing_libs", []):
            print(f"           missing: {lib}")
        if launch.get("missing_libs"):
            print(f"           {ARROW} install the missing system libraries (e.g. apt-get install)")

    if "fonts" in diag:
        win = diag["fonts"]["windows"]
        if win is None:
            print("Win fonts: unknown (fc-list unavailable)")
        else:
            n, total = win
            verdict = "ok" if n == total else "missing" if n == 0 else "partial"
            print(f"Win fonts: {verdict} ({n}/{total})")
            if n < total:
                print(f"           {ARROW} incomplete Windows font set; copy real Windows fonts (Segoe UI, Calibri, Consolas)")
        office = diag["fonts"].get("office")
        if office is not None:
            n, total = office
            # Office is informational only — no Office pack is a normal Windows
            # persona (~53% of real machines have none), so no install nudge.
            verdict = "ok" if n == total else "absent" if n == 0 else "partial"
            print(f"Office fonts: {verdict} ({n}/{total})")

    lic = diag["license"]
    tier = lic["tier"]
    if tier == "free" and lic.get("valid"):
        # Validated free-tier key (GitHub login): the latest binary, 1 session.
        print("License:   Free (latest binary, 1 concurrent session)")
        print(f"           {UPGRADE_HINT}")
    elif tier == "free":
        # Keyless: running the older free binary — invite the free-latest login.
        print("License:   Free (no key)")
        print(f"           {FREE_LATEST_HINT}")
        print(f"           {UPGRADE_HINT}")
    elif "error" in lic:
        print(f"License:   {tier} ({lic['error']})")
    else:
        print(f"License:   {tier}")

    if "sessions" in lic:
        print(f"Sessions:  {_format_seats(lic['sessions'])}")

    geoip = diag["geoip"]
    db_line = "present" if geoip["db_present"] else "not downloaded (optional)"
    resolved = geoip.get("resolved")
    if resolved is None:
        db_line += "  (pass --proxy <url> to resolve exit IP + timezone/locale)"
    print(f"GeoIP DB:  {db_line}")
    if resolved is not None:
        if resolved.get("error"):
            print(f"Exit IP:   (could not resolve — {resolved['error']})")
        else:
            print(f"Exit IP:   {resolved.get('exit_ip') or '(unknown)'}")
            print(f"Timezone:  {resolved.get('timezone') or '(unknown)'}")
            print(f"Locale:    {resolved.get('locale') or '(unknown)'}")

    print("Modules:")
    for label, available in diag["modules"].items():
        print(f"  {label}: {'ok' if available else 'missing'}")


def cmd_info(args: argparse.Namespace) -> None:
    quick = getattr(args, "quick", False)
    diag = _collect_diagnostics(quick=quick, proxy=getattr(args, "proxy", None))
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

        key = resolve_license_key(None)
        if not key:
            raise RuntimeError("Pro license key disappeared during update")
        new_version = check_for_pro_update(key)
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


FREE_LOGIN_URL = "https://cloakbrowser.dev/api/license/free/github/start"


def _save_license_key(key: str) -> None:
    """Persist a validated key to ~/.cloakbrowser/license.key (0600)."""
    from .config import get_cache_dir

    cache_dir = get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    key_file = cache_dir / "license.key"
    key_file.write_text(key.strip() + "\n")
    try:
        key_file.chmod(0o600)
    except OSError:
        pass


def _prompt_free_github_login() -> str:
    """Open the GitHub free-key page and read back the emailed key."""
    import webbrowser

    print(f"Opening GitHub sign-in: {FREE_LOGIN_URL}")
    try:
        webbrowser.open(FREE_LOGIN_URL)
    except Exception:
        pass
    print("If your browser did not open, visit the URL above and authorize with GitHub.")
    print("We'll email your free CloakBrowser key to your GitHub email.")
    try:
        return input("Paste the key from that email here: ").strip()
    except EOFError:
        return ""


def cmd_login(args: argparse.Namespace) -> None:
    """Activate any key. `login <key>` saves a pasted key; bare `login` prompts
    to paste a key or press ENTER to get a free key via GitHub."""
    from .license import validate_license

    key = (getattr(args, "key", None) or "").strip()

    if not key:
        if not sys.stdin.isatty():
            print(
                "Usage: cloakbrowser login <key>  (or run it interactively for a free key).",
                file=sys.stderr,
            )
            sys.exit(2)
        try:
            entered = input(
                "Paste your license key, or press ENTER to get a free key via GitHub: "
            ).strip()
        except EOFError:
            entered = ""
        key = entered or _prompt_free_github_login()

    if not key:
        print("No key entered. Nothing saved.", file=sys.stderr)
        sys.exit(1)

    info = validate_license(key)
    if info is None:
        print(
            "Could not reach the license server to verify the key. Check your connection and retry.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not info.valid:
        print("That license key is invalid or expired. Nothing was saved.", file=sys.stderr)
        sys.exit(1)

    _save_license_key(key)
    if info.plan == "free":
        print("Saved. Free tier active: latest binary, 1 concurrent session (one browser at a time).")
        print("Need to run more at once? See the plans at https://cloakbrowser.dev")
    else:
        print(f"Saved. {info.plan.capitalize()} key active: latest binary, full plan limits.")


def cmd_logout(args: argparse.Namespace) -> None:
    """Remove the saved license key (revert to the free v146 binary)."""
    from .config import get_cache_dir

    key_file = get_cache_dir() / "license.key"
    if key_file.exists():
        try:
            key_file.unlink()
        except OSError as e:
            print(f"Could not remove {key_file}: {e}", file=sys.stderr)
            sys.exit(1)
        print("Logged out. Removed the saved key; launches revert to the free binary.")
    else:
        print("No saved license key found.")


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
        p.add_argument(
            "--proxy",
            metavar="URL",
            help=(
                "Resolve the exit IP, timezone, and locale a launch would apply "
                "through this proxy (downloads the GeoIP DB if not cached)"
            ),
        )

    _add_info_flags(sub.add_parser("info", help="Environment + binary diagnostics"))
    _add_info_flags(sub.add_parser("doctor", help="Alias for info"))
    sub.add_parser("update", help="Check for and download a newer binary")
    sub.add_parser("clear-cache", help="Remove all cached binaries")

    login_p = sub.add_parser(
        "login", help="Save a license key (or get a free key via GitHub)"
    )
    login_p.add_argument(
        "key", nargs="?", help="License key to save. Omit to enter it interactively."
    )
    sub.add_parser("logout", help="Remove the saved license key (revert to free binary)")

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
        "login": cmd_login,
        "logout": cmd_logout,
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
