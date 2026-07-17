"""Live iFood smoke test for issue #448 PerimeterX auto bypass.

This is intentionally a manual/live example rather than a pytest: PX triggering
is adaptive and depends on IP reputation, address state, and traffic volume.
Set IFOOD_PROXY_URL to use a residential proxy. The script never logs credentials.
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import time

from cloakbrowser import launch
from cloakbrowser.pxbypass import PxConfig, detect_px

IFOOD_URL = "https://www.ifood.com.br/restaurantes"


def _app_ready(page) -> bool:
    """Generic iFood recovery signal used after the PX modal disappears."""
    try:
        return bool(
            page.evaluate(
                """() => location.hostname.endsWith('ifood.com.br') &&
                    !!(self.webpackChunk_N_E && self.webpackChunk_N_E.length)"""
            )
        )
    except Exception:
        return False


def _trigger_activity(page, rounds: int) -> None:
    """Generate normal page activity; PX may or may not challenge the session."""
    for index in range(rounds):
        candidates = []
        try:
            for element in page.query_selector_all(
                "a, button, [role='tab'], [role='button']"
            ):
                try:
                    if element.is_visible():
                        candidates.append(element)
                except Exception:
                    pass
        except Exception:
            pass

        if candidates:
            try:
                random.choice(candidates).click(timeout=5_000)
            except Exception:
                pass
        else:
            try:
                page.mouse.wheel(0, random.randint(250, 600))
            except Exception:
                pass

        time.sleep(random.uniform(0.5, 1.4))
        if detect_px(page):
            logging.warning("PX challenge detected after activity round %d", index + 1)
            return


def main() -> int:
    parser = argparse.ArgumentParser(description="Live iFood PX bypass smoke test")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--rounds", type=int, default=25)
    parser.add_argument("--wait", type=float, default=120.0)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("cloakbrowser.pxbypass").setLevel(logging.DEBUG)

    proxy = os.environ.get("IFOOD_PROXY_URL") or None
    browser = launch(
        headless=args.headless,
        proxy=proxy,
        humanize=True,
        locale="pt-BR",
        bypass_px=True,
        px_config=PxConfig(
            max_attempts=3,
            hold_min=3.8,
            hold_max=6.5,
            post_wait=30.0,
            button_wait_timeout=20.0,
            checker=_app_ready,
        ),
    )
    page = browser.new_page()
    try:
        page.goto(IFOOD_URL, timeout=120_000, wait_until="domcontentloaded")
        _trigger_activity(page, args.rounds)

        # ``page`` methods are monkey-patched by the bypass layer; using normal
        # attribute lookup here can return a stale Playwright wrapper after a
        # navigation. Read the Python instance dictionary so the exact helper
        # installed by ``_patch_methods_for_px_polling`` is invoked.
        wait_for_px_solved = page.__dict__.get("wait_for_px_solved")
        if not callable(wait_for_px_solved):
            logging.error("PX solver helper was not installed on the page")
            return 1
        px_detected = bool(detect_px(page))
        if px_detected and not wait_for_px_solved(timeout=args.wait):
            logging.error("PX remained visible after %.0fs", args.wait)
            return 1

        if detect_px(page):
            logging.error("PX is still detected")
            return 1
        if not _app_ready(page):
            logging.warning(
                "No active PX challenge, but the iFood app is not ready; "
                "the session may be on Cloudflare/address setup"
            )
            return 2

        logging.info("Page is usable; PX is absent or was solved")
        return 0
    finally:
        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())
