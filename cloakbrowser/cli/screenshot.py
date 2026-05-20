"""cloakbrowser screenshot — take a screenshot of a URL."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("screenshot", help="Take a screenshot of a URL")
    p.add_argument("--url", required=True, help="URL to capture")
    p.add_argument("--out", type=Path, required=True, help="Output file path (.png)")
    p.add_argument("--profile", default=None, help="Profile name for persistent context")
    p.add_argument("--timeout", type=int, default=30, help="Page load timeout in seconds (default: 30)")
    p.add_argument("--full-page", action="store_true", help="Capture full scrollable page")
    p.add_argument("--json", action="store_true", help="Output result as JSON")
    p.set_defaults(func=cmd_screenshot)


def cmd_screenshot(args: argparse.Namespace) -> None:
    from ..cli import output, fail
    from ._launch import launch_for_cli

    try:
        context, page = launch_for_cli(
            profile=args.profile,
            url=args.url,
            timeout=args.timeout,
        )
        page.screenshot(path=str(args.out), full_page=args.full_page)
        context.close()

        result = {
            "url": args.url,
            "output": str(args.out.resolve()),
            "size_bytes": args.out.stat().st_size if args.out.exists() else 0,
        }
        output(result, as_json=args.json)
    except Exception as e:
        fail(str(e))
