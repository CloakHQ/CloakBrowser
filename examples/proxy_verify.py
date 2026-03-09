#!/usr/bin/env python3
"""Verify proxy rotation with a real Playwright browser.

This script launches CloakBrowser through real proxies and confirms that
the exit IP changes.  Replace the proxy list with your own servers.

Usage:
    # Single proxy — verify IP changes
    python examples/proxy_verify.py --proxy "http://user:pass@host:port"

    # Two proxies — verify rotation
    python examples/proxy_verify.py \
        --proxy "http://user:pass@proxy1:port" \
        --proxy "http://user:pass@proxy2:port"

    # Bare format (user:pass@host:port) is also supported
    python examples/proxy_verify.py --proxy "user:pass@host:port"

    # SOCKS5
    python examples/proxy_verify.py --proxy "socks5://user:pass@host:port"

    # Playwright dict format (JSON string)
    python examples/proxy_verify.py \
        --proxy '{"server":"http://host:port","username":"u","password":"p"}'

    # With bypass option (Playwright dict only)
    python examples/proxy_verify.py \
        --proxy '{"server":"http://host:port","username":"u","password":"p","bypass":".google.com"}'

Requirements:
    pip install cloakbrowser
    # On first run, CloakBrowser downloads its stealth Chromium binary (~200 MB).
"""

from __future__ import annotations

import argparse
import json
import sys


def parse_proxy(value: str) -> str | dict:
    """Parse a proxy argument — supports strings and JSON dicts."""
    value = value.strip()
    if value.startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            print(f"ERROR: Invalid JSON proxy dict: {value}", file=sys.stderr)
            sys.exit(1)
    return value


def get_exit_ip(page) -> str | None:
    """Navigate to an IP-echo service and return the exit IP."""
    services = [
        ("https://api.ipify.org?format=json", "ip"),
        ("https://checkip.amazonaws.com", None),
        ("https://ifconfig.me/ip", None),
    ]
    for url, json_key in services:
        try:
            page.goto(url, timeout=15000)
            text = page.inner_text("body").strip()
            if json_key:
                return json.loads(text).get(json_key, text)
            return text
        except Exception:
            continue
    return None


def main():
    parser = argparse.ArgumentParser(description="Verify CloakBrowser proxy rotation with real Playwright")
    parser.add_argument(
        "--proxy", action="append", required=True,
        help='Proxy URL or JSON dict. Can be repeated for rotation test.',
    )
    parser.add_argument("--headless", action="store_true", default=True, help="Run headless (default)")
    parser.add_argument("--no-headless", action="store_true", help="Run with visible browser window")
    args = parser.parse_args()

    headless = not args.no_headless
    proxies = [parse_proxy(p) for p in args.proxy]

    from cloakbrowser import ProxyRotator, launch

    # ---- Step 1: Get our real IP (no proxy) ----
    print("Step 1: Detecting real IP (no proxy)...")
    browser = launch(headless=headless)
    page = browser.new_page()
    real_ip = get_exit_ip(page)
    browser.close()
    print(f"  Real IP: {real_ip}")

    if len(proxies) == 1:
        # ---- Single proxy: verify IP changes ----
        proxy = proxies[0]
        proxy_display = proxy if isinstance(proxy, str) else proxy.get("server", str(proxy))
        print(f"\nStep 2: Launching with proxy: {proxy_display}")

        browser = launch(proxy=proxy, headless=headless)
        page = browser.new_page()
        proxy_ip = get_exit_ip(page)
        browser.close()
        print(f"  Proxy IP: {proxy_ip}")

        if proxy_ip and proxy_ip != real_ip:
            print(f"\n  SUCCESS: IP changed from {real_ip} to {proxy_ip}")
        elif proxy_ip == real_ip:
            print(f"\n  WARNING: IP did NOT change — proxy may not be working")
        else:
            print(f"\n  ERROR: Could not detect IP through proxy")

    else:
        # ---- Multiple proxies: verify rotation ----
        rotator = ProxyRotator(proxies, strategy="round_robin")
        print(f"\nStep 2: Testing rotation with {len(proxies)} proxies...")
        print(f"  Pool: {rotator}")

        seen_ips = set()
        for i in range(len(proxies)):
            with rotator.session() as proxy:
                proxy_display = proxy if isinstance(proxy, str) else proxy.get("server", str(proxy))
                print(f"\n  Request {i + 1}: Using {proxy_display}")

                browser = launch(proxy=proxy, headless=headless)
                page = browser.new_page()
                ip = get_exit_ip(page)
                browser.close()

                print(f"    Exit IP: {ip}")
                if ip:
                    seen_ips.add(ip)

        print(f"\n  Summary:")
        print(f"    Real IP:    {real_ip}")
        print(f"    Proxy IPs:  {seen_ips}")
        print(f"    Unique IPs: {len(seen_ips)}")

        if real_ip not in seen_ips and len(seen_ips) > 0:
            print(f"    SUCCESS: All traffic went through proxies")
        elif len(seen_ips) > 1:
            print(f"    PARTIAL: Multiple proxy IPs detected")
        else:
            print(f"    WARNING: Check proxy configuration")

        # ---- Show stats ----
        print(f"\n  Health stats:")
        for s in rotator.stats():
            print(f"    {s['proxy']}: uses={s['use_count']}, fails={s['fail_count']}, ok={s['available']}")

    print("\nDone!")


if __name__ == "__main__":
    main()
