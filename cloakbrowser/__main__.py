"""CLI for cloakbrowser — download and manage the stealth Chromium binary.

Usage:
    python -m cloakbrowser install      # Download binary (with progress)
    python -m cloakbrowser info         # Show binary version, path, platform
    python -m cloakbrowser update       # Check for and download newer binary
    python -m cloakbrowser clear-cache  # Remove cached binaries
"""

from __future__ import annotations

import argparse
import importlib.util
import logging
import platform
import sys


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


def cmd_info(args: argparse.Namespace) -> None:
    from .config import get_local_binary_override
    from .download import binary_info

    info = binary_info()
    override = get_local_binary_override()

    print(f"Version:   {info['version']}")
    print(f"Platform:  {info['platform']}")
    print(f"Binary:    {info['binary_path']}")
    print(f"Installed: {info['installed']}")
    print(f"Cache:     {info['cache_dir']}")
    if override:
        print(f"Override:  {override} (CLOAKBROWSER_BINARY_PATH)")


def cmd_update(args: argparse.Namespace) -> None:
    from .download import check_for_update

    logger = logging.getLogger("cloakbrowser")
    logger.info("Checking for updates...")
    new_version = check_for_update()
    if new_version:
        print(f"Updated to Chromium {new_version}")
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


def _module_available(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        return False


def cmd_doctor(args: argparse.Namespace) -> None:
    """Print environment diagnostics without downloading Chromium."""
    from .config import get_binary_path, get_cache_dir, get_platform_tag
    from .download import binary_info

    print("CloakBrowser doctor")
    print(f"Python:    {sys.version.split()[0]}")
    print(f"OS:        {platform.system()} {platform.machine()}")

    try:
        print(f"Platform:  {get_platform_tag()}")
    except RuntimeError as exc:
        print(f"Platform:  unsupported ({exc})")

    print(f"Cache:     {get_cache_dir()}")

    try:
        info = binary_info()
        binary_path = get_binary_path(info["version"])
        print(f"Version:   {info['version']} (bundled: {info['bundled_version']})")
        print(f"Binary:    {info['binary_path']}")
        print(f"Installed: {info['installed']}")
        print(f"Usable:    {binary_path.exists() and binary_path.is_file()}")
    except Exception as exc:
        print(f"Binary:    unavailable ({exc})")

    checks = {
        "playwright": "playwright.sync_api",
        "patchright": "patchright.sync_api",
        "geoip2": "geoip2.database",
        "aiohttp": "aiohttp",
        "websockets": "websockets",
    }
    print("Modules:")
    for label, module in checks.items():
        status = "ok" if _module_available(module) else "missing"
        print(f"  {label}: {status}")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cloakbrowser",
        description="Manage the CloakBrowser stealth Chromium binary.",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("install", help="Download the Chromium binary")
    sub.add_parser("info", help="Show binary version, path, and platform")
    sub.add_parser("update", help="Check for and download a newer binary")
    sub.add_parser("clear-cache", help="Remove all cached binaries")
    sub.add_parser("doctor", help="Show environment diagnostics")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(2)

    _setup_logging()

    commands = {
        "install": cmd_install,
        "info": cmd_info,
        "update": cmd_update,
        "clear-cache": cmd_clear_cache,
        "doctor": cmd_doctor,
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
