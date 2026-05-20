"""cloakbrowser doctor — check binary health, version, environment."""

from __future__ import annotations

import argparse
import sys


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("doctor", help="Check binary health and environment")
    p.add_argument("--json", action="store_true", help="Machine-readable JSON output")
    p.set_defaults(func=cmd_doctor)


def cmd_doctor(args: argparse.Namespace) -> None:
    from ..cli import output, fail
    from ..config import get_cache_dir, get_local_binary_override
    from ..download import binary_info, ensure_binary

    info = binary_info()
    override = get_local_binary_override()

    # Try to ensure binary is installed
    error_msg = ""
    try:
        path = ensure_binary()
        ready = True
    except Exception as e:
        path = None
        ready = False
        error_msg = str(e)

    result = {
        "ready": ready,
        "version": info["version"],
        "platform": info["platform"],
        "binary_path": str(path) if path else info["binary_path"],
        "installed": info["installed"],
        "cache_dir": str(info["cache_dir"]),
        "override": override or None,
    }
    if not ready:
        result["error"] = error_msg

    output(result, as_json=args.json)
    sys.exit(0 if ready else 1)
