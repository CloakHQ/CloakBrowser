"""cloakbrowser eval — evaluate JavaScript against a page and return JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("eval", help="Evaluate JavaScript on a page and return JSON")
    p.add_argument("--url", required=True, help="URL to load before evaluating")
    p.add_argument("--js-file", type=Path, default=None, help="JavaScript file to evaluate")
    p.add_argument("--js", default=None, help="Inline JavaScript to evaluate")
    p.add_argument("--profile", default=None, help="Profile name for persistent context")
    p.add_argument("--timeout", type=int, default=30, help="Page load timeout in seconds (default: 30)")
    p.add_argument("--json", action="store_true", help="Output as JSON")
    p.set_defaults(func=cmd_eval)


def cmd_eval(args: argparse.Namespace) -> None:
    from ..cli import output, fail
    from ._launch import launch_for_cli

    if not args.js_file and not args.js:
        fail("Either --js-file or --js is required")

    try:
        if args.js_file:
            script = args.js_file.read_text()
        else:
            script = args.js

        context, page = launch_for_cli(
            profile=args.profile,
            url=args.url,
            timeout=args.timeout,
        )
        result = page.evaluate(script)
        context.close()

        output(result, as_json=args.json)
    except Exception as e:
        fail(str(e))
