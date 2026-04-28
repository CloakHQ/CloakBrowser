"""AWS Lambda handler for one-off stealth-browser invocations.

Always runs **headed** via the Xvfb display started by `lambda-entrypoint.sh`.

Event schema (all fields except `url` are optional):

    Launch options (passed to cloakbrowser.launch_context_async):
        url                 str              required, the page to scrape
        proxy               str|dict         http://user:pass@host:port  or  Playwright proxy dict
        humanize            bool             False — enable human-like mouse/keyboard/scroll
        human_preset        str              "default" | "careful"
        geoip               bool             False — auto timezone+locale from proxy IP
        timezone            str              IANA tz, e.g. "America/New_York"
        locale              str              BCP-47, e.g. "en-US"
        viewport            {width,height}   defaults to 1920x947 (cloakbrowser DEFAULT_VIEWPORT)
        user_agent          str              custom UA (rare — cloakbrowser sets one already)
        extra_args          list[str]        additional Chromium CLI flags

    Navigation options (passed to page.goto):
        wait_until          str              "load"|"domcontentloaded"|"networkidle"|"commit"
                                              default "domcontentloaded"
        goto_timeout_ms     int              30000

    Post-navigation waits (run in this order if specified):
        smart_wait                       bool ON by default if no other wait is set.
                                              Polls document.outerHTML.length and bails when it
                                              hasn't changed for `dom_stable_ms`. Handles lazy
                                              hydration, async chunks, and lazy images, and is
                                              immune to analytics beacons / long-poll that keep
                                              the network busy without mutating the DOM.
        dom_stable_ms                    int  1500   — how long DOM must be quiet
        max_settle_ms                    int  15000  — hard cap on smart_wait
        wait_for_load_state              str  "load"|"domcontentloaded"|"networkidle"
        wait_for_load_state_timeout_ms   int  30000
        wait_for_selector                str  CSS or XPath selector
        wait_for_selector_state          str  "attached"|"detached"|"visible"|"hidden", default "visible"
        wait_for_selector_timeout_ms     int  30000
        wait_for_function                str  JS expression that returns truthy when ready
        wait_for_function_timeout_ms     int  30000
        wait_ms                          int  fixed pause in ms (page.wait_for_timeout)

    Capture options:
        screenshot              bool         True
        full_page_screenshot    bool         False — capture entire scrollable page

    Retry orchestration:
        retries     int  default 1. Number of retry attempts after the first
                          failure. Set to 0 to disable retries entirely (the
                          handler will fail fast on the first error).
                          Retried errors:
                            ERR_CERT_*                -> retry with --ignore-certificate-errors
                            Timeout exceeded          -> retry with goto_timeout_ms=90000, max_settle_ms=25000
                            ERR_CONNECTION_TIMED_OUT  -> same as Timeout
                          Not retried (unrecoverable): ERR_NAME_NOT_RESOLVED,
                          ERR_SSL_PROTOCOL_ERROR, generic ERR_CONNECTION_REFUSED.
                          On final failure, the error message includes a
                          retry_history block with strategy + error per attempt.

Returns:
    {"title": ..., "url": ..., "html": ..., "screenshot_b64"?: ...}
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from cloakbrowser import launch_context_async

logger = logging.getLogger("cloakbrowser.lambda")
logger.setLevel(logging.INFO)


def _diag_snapshot() -> str:
    """Capture Xvfb status, Xvfb log, X11 socket state, and env for error reports."""
    import os
    parts = []
    try:
        r = subprocess.run(["pgrep", "-fa", "Xvfb"], capture_output=True, text=True)
        parts.append(f"pgrep Xvfb: rc={r.returncode} stdout={r.stdout.strip()!r}")
    except Exception as e:
        parts.append(f"pgrep failed: {e}")
    try:
        r = subprocess.run(["ls", "-la", "/tmp/.X11-unix"], capture_output=True, text=True)
        parts.append(f"ls /tmp/.X11-unix:\n{r.stdout}{r.stderr}")
    except Exception as e:
        parts.append(f"ls /tmp/.X11-unix failed: {e}")
    try:
        log = Path("/tmp/Xvfb.log").read_text()
        parts.append(f"/tmp/Xvfb.log:\n{log}")
    except Exception as e:
        parts.append(f"Xvfb log unreadable: {e}")
    parts.append(f"env: DISPLAY={os.environ.get('DISPLAY')!r} HOME={os.environ.get('HOME')!r}")
    return "\n".join(parts)


def handler(event: dict, context: Any) -> dict:
    return asyncio.run(_run(event))


def _build_launch_kwargs(event: dict) -> dict:
    """Translate the event dict into kwargs for launch_context_async.

    Only includes keys explicitly set in the event so cloakbrowser's defaults
    (DEFAULT_VIEWPORT etc.) kick in when fields are absent — passing
    viewport=None would *disable* viewport emulation, which we don't want.
    """
    kwargs: dict = {
        "headless": False,  # always headed via Xvfb
        "args": [
            # Lambda /dev/shm is ~64 MB — Chromium crashes mid-render without this.
            "--disable-dev-shm-usage",
            # Lambda's restricted process model can't fork from Chromium's zygote
            # — without this, child renderer processes fail to spawn.
            "--no-zygote",
            *event.get("extra_args", []),
        ],
    }
    for key in ("proxy", "humanize", "human_preset", "geoip",
                "timezone", "locale", "viewport", "user_agent"):
        if key in event:
            kwargs[key] = event[key]
    return kwargs


async def _smart_wait(page, dom_stable_ms: int = 1500, max_settle_ms: int = 15000) -> None:
    """Wait until the document HTML hasn't changed for `dom_stable_ms`.

    Generic stopping condition for at-scale scraping when you can't tune
    selectors per site. More robust than `networkidle` because it ignores
    network activity that doesn't mutate the DOM (analytics beacons,
    long-poll, websockets, web vitals streams).
    """
    js = f"""
    (() => {{
        if (!window.__cb_settle) {{
            window.__cb_settle = {{ len: -1, since: Date.now() }};
        }}
        const cur = document.documentElement.outerHTML.length;
        const s = window.__cb_settle;
        if (cur !== s.len) {{
            s.len = cur;
            s.since = Date.now();
            return false;
        }}
        return (Date.now() - s.since) >= {int(dom_stable_ms)};
    }})()
    """
    try:
        await page.wait_for_function(js, timeout=max_settle_ms, polling=200)
    except Exception:
        # Hit max_settle_ms cap — return what we have rather than fail the whole invoke
        logger.warning("smart_wait hit max_settle_ms=%d cap", max_settle_ms)


_EXPLICIT_WAIT_KEYS = (
    "wait_for_load_state", "wait_for_selector", "wait_for_function", "wait_ms",
)


async def _post_nav_waits(page, event: dict) -> None:
    """Run waits in priority order. smart_wait is the default unless the
    caller asked for a more specific stopping condition."""
    explicit = any(k in event for k in _EXPLICIT_WAIT_KEYS)
    if event.get("smart_wait", not explicit):
        await _smart_wait(
            page,
            dom_stable_ms=event.get("dom_stable_ms", 1500),
            max_settle_ms=event.get("max_settle_ms", 15000),
        )
    if "wait_for_load_state" in event:
        await page.wait_for_load_state(
            event["wait_for_load_state"],
            timeout=event.get("wait_for_load_state_timeout_ms", 30000),
        )
    if "wait_for_selector" in event:
        await page.wait_for_selector(
            event["wait_for_selector"],
            state=event.get("wait_for_selector_state", "visible"),
            timeout=event.get("wait_for_selector_timeout_ms", 30000),
        )
    if "wait_for_function" in event:
        await page.wait_for_function(
            event["wait_for_function"],
            timeout=event.get("wait_for_function_timeout_ms", 30000),
        )
    if "wait_ms" in event:
        await page.wait_for_timeout(event["wait_ms"])


async def _launch_with_retry(event: dict, attempts: int = 3, backoff_s: float = 0.3):
    """Retry launch_context_async up to `attempts` times with linear backoff.

    Lambda cold-start storms occasionally race Xvfb readiness or hit transient
    Chromium spawn failures — both surface as "Target page, context or browser
    has been closed" at launch. The failure is fast (~0.5s) so retries are
    cheap, and a retry on a now-warm container almost always succeeds.

    Pairs with the lock-cleanup + socket-poll in lambda-entrypoint.sh: the
    entrypoint catches the common case at container init; this catches the
    residual race when the first invocation hits before Xvfb is fully ready.
    """
    last_err: Exception | None = None
    for i in range(attempts):
        try:
            return await launch_context_async(**_build_launch_kwargs(event))
        except Exception as e:
            last_err = e
            logger.warning("launch attempt %d/%d failed: %s",
                           i + 1, attempts, str(e)[:200])
            if i + 1 < attempts:
                await asyncio.sleep(backoff_s * (i + 1))  # 0.3s, 0.6s
    raise last_err  # type: ignore[misc]


def _classify_error(err: Exception) -> dict | None:
    """Map a Playwright error to a retry-strategy override dict, or None
    if the error is unrecoverable.

    Match on str(e) because Playwright errors carry their codes inside the
    message (Error.__str__ includes ERR_CERT_AUTHORITY_INVALID etc.); there
    is no stable structured `.error_code` attribute to rely on.

    Strategies (priority order — first match wins):
      ERR_CERT_*                  -> --ignore-certificate-errors + 60s goto budget
      Timeout exceeded            -> 90s goto budget + 25s smart_wait cap
      ERR_CONNECTION_TIMED_OUT    -> same as Timeout
    Returns None for unrecoverable site issues (DNS, SSL, refused, HTTP 4xx/5xx).
    """
    msg = str(err)
    if "ERR_CERT" in msg:
        return {
            "extra_args": ["--ignore-certificate-errors"],
            "goto_timeout_ms": 60000,
        }
    if ("Timeout" in msg and "exceeded" in msg) or "ERR_CONNECTION_TIMED_OUT" in msg:
        return {
            "goto_timeout_ms": 90000,
            "max_settle_ms": 25000,
        }
    return None


async def _attempt_scrape(url: str, event: dict) -> dict:
    """One self-contained scrape attempt: launch, navigate, wait, capture, close.

    Extracted from `_run` so the retry loop can call it repeatedly with an
    overridden event dict. Each attempt relaunches the browser — uniform
    behavior across strategies (the cert-bypass strategy *requires* a relaunch
    because `--ignore-certificate-errors` is a Chromium CLI arg, not a per-
    context switch), and the ~3-5s relaunch cost is fine on the slow path.
    """
    ctx = await _launch_with_retry(event)
    try:
        page = await ctx.new_page()
        await page.goto(
            url,
            wait_until=event.get("wait_until", "domcontentloaded"),
            timeout=event.get("goto_timeout_ms", 30000),
        )

        await _post_nav_waits(page, event)

        result: dict = {
            "title": await page.title(),
            "url": page.url,
            "html": await page.content(),
        }

        if event.get("screenshot", True):
            png = await page.screenshot(
                full_page=event.get("full_page_screenshot", False),
            )
            result["screenshot_b64"] = base64.b64encode(png).decode()

        return result
    finally:
        try:
            await ctx.close()
        except Exception:
            pass


def _raise_with_history(err: Exception, history: list[dict]) -> None:
    """Surface a final failure with a retry_history block embedded in the
    error message, so callers see what was tried before bailing."""
    diag = _diag_snapshot()
    if history:
        diag = "retry_history: " + json.dumps(history, default=str) + "\n\n" + diag
    logger.error("scrape failed (after %d retries): %s\nDIAG:\n%s",
                 len(history), err, diag)
    raise RuntimeError(f"scrape failed: {err}\n--- DIAG ---\n{diag}") from err


async def _run(event: dict) -> dict:
    """Top-level scrape with strategy-based retry orchestration.

    First attempt uses the event verbatim. If it fails with a classifiable
    error (cert / timeout), retry with that strategy's overrides merged into
    the event. `retries` bounds the number of strategy retries (default 1;
    set to 0 to disable retry entirely).
    """
    url = event["url"]
    retries_left = max(0, int(event.get("retries", 1)))
    history: list[dict] = []
    current_event = event

    while True:
        try:
            return await _attempt_scrape(url, current_event)
        except Exception as e:
            if retries_left <= 0:
                _raise_with_history(e, history)
            strategy = _classify_error(e)
            if strategy is None:
                _raise_with_history(e, history)
            history.append({
                "attempt": len(history) + 1,
                "error": str(e)[:300],
                "strategy": strategy,
            })
            logger.warning("attempt %d failed (%s); retrying with strategy=%s",
                           len(history), str(e)[:120], strategy)
            merged_args = list(current_event.get("extra_args", [])) + list(strategy.get("extra_args", []))
            current_event = {**current_event, **strategy, "extra_args": merged_args}
            retries_left -= 1
            # No backoff: strategy overrides change goto budget directly;
            # the prior failure was either fast (cert reject) or already
            # waited its full timeout. Container is warm.


