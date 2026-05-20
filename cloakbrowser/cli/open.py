"""cloakbrowser open — launch a URL in the browser."""

from __future__ import annotations

import argparse
import sys


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("open", help="Open a URL in the stealth browser")
    p.add_argument("--url", required=True, help="URL to open")
    p.add_argument("--profile", default=None, help="Profile name for persistent context")
    p.add_argument("--timeout", type=int, default=30, help="Page load timeout in seconds (default: 30)")
    p.add_argument("--json", action="store_true", help="Output result as JSON")
    p.set_defaults(func=cmd_open)


def cmd_open(args: argparse.Namespace) -> None:
    from ..cli import output, fail
    from ._launch import launch_for_cli

    context = None
    try:
        context, page = launch_for_cli(
            profile=args.profile,
            url=args.url,
            headless=False,  # "open" implies visible browser
            timeout=args.timeout,
        )
        title = page.title()

        result = {
            "url": args.url,
            "title": title,
            "profile": args.profile,
        }
        output(result, as_json=args.json)

        print("\nBrowser is open. Press Ctrl+C to close.", file=sys.stderr)
        try:
            import signal
            signal.pause()
        except AttributeError:
            input()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        fail(str(e))
    finally:
        if context is not None:
            try:
                context.close()
            except Exception:
                pass
