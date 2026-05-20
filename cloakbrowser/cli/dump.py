"""cloakbrowser dump — extract structured data from a page."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("dump", help="Dump page elements as structured data")
    p.add_argument("mode", choices=["inputs", "buttons", "text", "links", "all"], help="What to dump")
    p.add_argument("--url", required=True, help="URL to analyze")
    p.add_argument("--profile", default=None, help="Profile name for persistent context")
    p.add_argument("--timeout", type=int, default=30, help="Page load timeout in seconds (default: 30)")
    p.add_argument("--json", action="store_true", help="Output as JSON (default for agent use)")
    p.add_argument("--selector", default=None, help="CSS selector to scope the dump")
    p.set_defaults(func=cmd_dump)


_DUMP_JS = """
(mode, scope) => {
    const results = [];
    const root = scope ? document.querySelector(scope) : document;

    const visible = (el) => {
        if (!el) return false;
        const style = window.getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden' && style.opacity !== '0';
    };

    if (mode === 'inputs' || mode === 'all') {
        const inputs = (root || document).querySelectorAll('input, textarea, select, [contenteditable="true"]');
        for (const el of inputs) {
            if (!visible(el)) continue;
            results.push({
                type: 'input',
                tag: el.tagName.toLowerCase(),
                name: el.name || el.id || el.getAttribute('aria-label') || '',
                placeholder: el.placeholder || '',
                value: el.value ? el.value.substring(0, 200) : '',
                selector: el.id ? '#' + el.id : (el.name ? `[name="${el.name}"]` : ''),
                visible: true
            });
        }
    }
    if (mode === 'buttons' || mode === 'all') {
        const buttons = (root || document).querySelectorAll('button, a[href], [role="button"], input[type="submit"], input[type="button"]');
        for (const el of buttons) {
            if (!visible(el)) continue;
            const text = (el.textContent || el.value || '').trim().substring(0, 100);
            if (!text) continue;
            results.push({
                type: 'button',
                tag: el.tagName.toLowerCase(),
                text: text,
                href: el.href || '',
                selector: el.id ? '#' + el.id : '',
                visible: true
            });
        }
    }
    if (mode === 'links' || mode === 'all') {
        const links = (root || document).querySelectorAll('a[href]');
        for (const el of links) {
            if (!visible(el)) continue;
            const text = (el.textContent || '').trim().substring(0, 150);
            if (!text || el.href.startsWith('javascript:')) continue;
            results.push({
                type: 'link',
                text: text,
                href: el.href,
                selector: el.id ? '#' + el.id : '',
                visible: true
            });
        }
    }
    if (mode === 'text' || mode === 'all') {
        const body = (root || document).body;
        if (body) {
            const text = body.innerText.trim().substring(0, 10000);
            results.push({ type: 'text', content: text });
        }
    }
    return results;
}
"""


def cmd_dump(args: argparse.Namespace) -> None:
    from ..cli import output, fail
    from ._launch import launch_for_cli

    try:
        context, page = launch_for_cli(
            profile=args.profile,
            url=args.url,
            timeout=args.timeout,
        )
        data = page.evaluate(_DUMP_JS, args.mode, args.selector)
        context.close()

        result: dict[str, Any] = {
            "url": args.url,
            "mode": args.mode,
            "count": len(data) if isinstance(data, list) else 1,
            "elements": data,
        }
        output(result, as_json=True if args.json else False)  # JSON default for agents
    except Exception as e:
        fail(str(e))
