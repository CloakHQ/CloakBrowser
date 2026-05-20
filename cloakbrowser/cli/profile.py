"""cloakbrowser profile — list and resolve persistent browser profiles."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("profile", help="Manage browser profiles")
    sub = p.add_subparsers(dest="profile_command")

    lst = sub.add_parser("list", help="List saved profiles")
    lst.add_argument("--json", action="store_true")
    lst.add_argument("--dir", type=Path, default=None, help="Profiles directory (default: ~/.cloakbrowser/profiles)")
    lst.set_defaults(func=cmd_profile_list)

    path = sub.add_parser("path", help="Resolve profile path")
    path.add_argument("name", help="Profile name")
    path.add_argument("--json", action="store_true")
    path.add_argument("--dir", type=Path, default=None, help="Profiles directory (default: ~/.cloakbrowser/profiles)")
    path.set_defaults(func=cmd_profile_path)


def _profiles_dir(dir_override: Path | None = None) -> Path:
    if dir_override:
        return dir_override.expanduser().resolve()
    return Path.home() / ".cloakbrowser" / "profiles"


def cmd_profile_list(args: argparse.Namespace) -> None:
    from ..cli import output

    d = _profiles_dir(args.dir)
    if not d.exists():
        output([], as_json=args.json)
        return

    profiles = sorted(
        [p.name for p in d.iterdir() if p.is_dir()],
        key=str.lower,
    )
    output(profiles, as_json=args.json)


def cmd_profile_path(args: argparse.Namespace) -> None:
    from ..cli import output, fail

    d = _profiles_dir(args.dir)
    profile_path = d / args.name

    result = {
        "name": args.name,
        "path": str(profile_path.resolve()),
        "exists": profile_path.is_dir(),
    }
    if profile_path.is_dir():
        entries = sorted(
            [p.name for p in profile_path.iterdir()],
            key=str.lower,
        )
        result["entries"] = entries[:20]  # don't dump thousands of files
    output(result, as_json=args.json)
    sys.exit(0 if result["exists"] else 1)
