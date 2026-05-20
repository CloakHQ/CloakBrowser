"""CLI for cloakbrowser — download and manage the stealth Chromium binary.

Usage:
    python -m cloakbrowser install      # Download binary (with progress)
    python -m cloakbrowser info         # Show binary version, path, platform
    python -m cloakbrowser update       # Check for and download newer binary
    python -m cloakbrowser clear-cache  # Remove cached binaries
"""

from __future__ import annotations

import argparse
import logging
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

    # Agent-friendly subcommands
    from .cli.doctor import add_subparser as _add_doctor
    from .cli.profile import add_subparser as _add_profile
    from .cli.screenshot import add_subparser as _add_screenshot
    from .cli.dump import add_subparser as _add_dump
    from .cli.eval import add_subparser as _add_eval
    from .cli.open import add_subparser as _add_open

    _add_doctor(sub)
    _add_profile(sub)
    _add_screenshot(sub)
    _add_dump(sub)
    _add_eval(sub)
    _add_open(sub)

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
    }

    try:
        if args.command in commands:
            commands[args.command](args)
        elif hasattr(args, "func"):
            args.func(args)
        else:
            print(f"Unknown command: {args.command}", file=sys.stderr)
            sys.exit(2)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
