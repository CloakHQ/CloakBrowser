"""Playwright-style actionability checks for the humanize layer (async).

Async mirror of actionability.py — same logic, uses asyncio.sleep and await.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, FrozenSet, Optional

logger = logging.getLogger(__name__)

from .actionability import (
    ActionabilityError,
    ElementNotAttachedError,
    ElementNotVisibleError,
    ElementNotStableError,
    ElementNotEnabledError,
    ElementNotEditableError,
    ElementNotReceivingEventsError,
    _BACKOFF_MS,
    _boxes_differ,
    _POINTER_EVENTS_LOCATOR_JS,
    _POINTER_EVENTS_HANDLE_JS,
)
from .stealth_dom import (
    build_actionable_js, build_box_js, build_pointer_js, async_eval_parsed,
    OK, NOT_FOUND, UNSUPPORTED,
)


async def _async_backoff_sleep(attempt: int) -> None:
    idx = min(attempt, len(_BACKOFF_MS) - 1)
    await asyncio.sleep(_BACKOFF_MS[idx] / 1000.0)


# ---------------------------------------------------------------------------
# Pre-scroll actionability
# ---------------------------------------------------------------------------

async def _async_stealth_actionable(page: Any, selector: str, checks: FrozenSet[str]) -> bool:
    """Async mirror of ``_stealth_actionable`` — isolated-world actionability read.

    Returns True when handled (raising on a failed check), False when the
    selector/world is unsupported (caller falls back to Playwright).
    """
    world = getattr(page, "_stealth_world", None)
    if world is None:
        return False
    status, data = await async_eval_parsed(world, build_actionable_js(selector))
    if status == UNSUPPORTED:
        return False
    if status == NOT_FOUND:
        raise ElementNotAttachedError(selector)
    if "visible" in checks and not data.get("visible"):
        raise ElementNotVisibleError(selector)
    if "enabled" in checks and not data.get("enabled"):
        raise ElementNotEnabledError(selector)
    if "editable" in checks and not data.get("editable"):
        raise ElementNotEditableError(selector)
    return True


async def _async_read_box(page: Any, selector: str, remaining_ms: float) -> Optional[dict]:
    """Async mirror of ``_read_box`` — isolated-world box with Playwright fallback."""
    world = getattr(page, "_stealth_world", None)
    if world is not None:
        status, data = await async_eval_parsed(world, build_box_js(selector))
        if status == OK:
            return data["box"]
        if status == NOT_FOUND:
            return None
        # UNSUPPORTED -> Playwright below
    try:
        loc = page.locator(selector).first
        return await loc.bounding_box(timeout=max(1, min(remaining_ms, 1000)))
    except Exception:
        return None


async def async_ensure_actionable(
    page: Any,
    selector: str,
    checks: FrozenSet[str],
    timeout: float = 30000,
    force: bool = False,
) -> None:
    if force:
        return

    deadline = time.monotonic() + timeout / 1000.0
    attempt = 0
    last_error: Optional[ActionabilityError] = None

    while True:
        remaining_ms = max(0, (deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            if last_error is not None:
                raise last_error
            raise ActionabilityError(selector, "timeout", "timeout expired before first check")

        try:
            if not await _async_stealth_actionable(page, selector, checks):
                loc = page.locator(selector).first

                if "attached" in checks:
                    try:
                        await loc.wait_for(state="attached", timeout=max(1, min(remaining_ms, 2000)))
                    except Exception:
                        raise ElementNotAttachedError(selector)

                if "visible" in checks:
                    if not await loc.is_visible():
                        raise ElementNotVisibleError(selector)

                if "enabled" in checks:
                    if not await loc.is_enabled():
                        raise ElementNotEnabledError(selector)

                if "editable" in checks:
                    if not await loc.is_editable():
                        raise ElementNotEditableError(selector)

            return

        except ActionabilityError as e:
            last_error = e
            if time.monotonic() >= deadline:
                raise last_error
            await _async_backoff_sleep(attempt)
            attempt += 1


# ---------------------------------------------------------------------------
# Post-scroll stability check
# ---------------------------------------------------------------------------

async def async_ensure_stable(
    page: Any,
    selector: str,
    timeout: float = 5000,
) -> None:
    deadline = time.monotonic() + timeout / 1000.0
    attempt = 0

    while True:
        remaining_ms = max(0, (deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            raise ElementNotStableError(selector)

        box1 = await _async_read_box(page, selector, remaining_ms)
        if box1 is None:
            raise ElementNotAttachedError(selector)

        await asyncio.sleep(0.1)

        box2 = await _async_read_box(page, selector, remaining_ms)
        if box2 is None:
            raise ElementNotAttachedError(selector)

        if not _boxes_differ(box1, box2):
            return

        if time.monotonic() >= deadline:
            raise ElementNotStableError(selector)

        await _async_backoff_sleep(attempt)
        attempt += 1


# ---------------------------------------------------------------------------
# Pointer-events check
# ---------------------------------------------------------------------------

async def async_check_pointer_events(
    page: Any,
    selector: str,
    x: float,
    y: float,
    stealth: Any = None,
    timeout: float = 5000,
) -> None:
    deadline = time.monotonic() + timeout / 1000.0
    attempt = 0
    last_miss: Optional[str] = None

    while True:
        world = stealth if stealth is not None else getattr(page, "_stealth_world", None)
        result: Optional[dict] = None
        handled = False
        if world is not None:
            status, data = await async_eval_parsed(world, build_pointer_js(selector, x, y))
            if status == OK:
                result = {"hit": data.get("hit", False), "covering": data.get("covering", "unknown")}
                handled = True
            elif status == NOT_FOUND:
                result = None
                handled = True
        if not handled:
            try:
                loc = page.locator(selector).first
                box = await loc.bounding_box(timeout=max(1, min((deadline - time.monotonic()) * 1000, 1000)))
                result = await loc.evaluate(_POINTER_EVENTS_LOCATOR_JS, {"x": x, "y": y, "box": box})
            except Exception as exc:
                logger.debug("pointer_events check failed for %r: %s", selector, exc)
                result = None

        # Proceed if the check confirms a hit, or if it could not be determined
        # (None) — failing closed would block legitimate clicks. But once a miss
        # has actually been *determined*, a later indeterminate attempt must not
        # launder it into a pass: near the deadline the bounding_box timeout is
        # clamped to ~1ms and always throws, which used to turn a proven miss
        # into "unknown" and let the click through silently (#329).
        if result is None:
            if last_miss is not None and time.monotonic() >= deadline:
                raise ElementNotReceivingEventsError(selector, last_miss)
            return
        if result.get("hit", False):
            return

        covering = result.get("covering", "unknown")
        last_miss = covering

        if time.monotonic() >= deadline:
            raise ElementNotReceivingEventsError(selector, covering)

        await _async_backoff_sleep(attempt)
        attempt += 1


# ---------------------------------------------------------------------------
# ElementHandle variant
# ---------------------------------------------------------------------------

async def async_ensure_actionable_handle(
    page: Any,
    el: Any,
    checks: FrozenSet[str],
    timeout: float = 30000,
    force: bool = False,
) -> None:
    if force:
        return

    deadline = time.monotonic() + timeout / 1000.0
    attempt = 0
    last_error: Optional[ActionabilityError] = None
    label = "<ElementHandle>"

    while True:
        remaining_ms = max(0, (deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            if last_error is not None:
                raise last_error
            raise ActionabilityError(label, "timeout", "timeout expired before first check")

        try:
            if "visible" in checks:
                try:
                    await el.wait_for_element_state("visible", timeout=max(1, min(remaining_ms, 2000)))
                except Exception:
                    raise ElementNotVisibleError(label)

            if "enabled" in checks:
                try:
                    await el.wait_for_element_state("enabled", timeout=max(1, min(remaining_ms, 2000)))
                except Exception:
                    raise ElementNotEnabledError(label)

            if "editable" in checks:
                try:
                    await el.wait_for_element_state("editable", timeout=max(1, min(remaining_ms, 2000)))
                except Exception:
                    raise ElementNotEditableError(label)

            return

        except ActionabilityError as e:
            last_error = e
            if time.monotonic() >= deadline:
                raise last_error
            await _async_backoff_sleep(attempt)
            attempt += 1


async def async_check_pointer_events_handle(
    page: Any,
    el: Any,
    x: float,
    y: float,
    timeout: float = 5000,
) -> None:
    deadline = time.monotonic() + timeout / 1000.0
    attempt = 0

    while True:
        try:
            box = await el.bounding_box()
            result = await el.evaluate(_POINTER_EVENTS_HANDLE_JS, {"x": x, "y": y, "box": box})
        except Exception:
            result = None

        # Proceed if the check confirms a hit, or if it could not be determined
        # (None) — failing closed would block legitimate clicks.
        if result is None or result.get("hit", False):
            return

        covering = (result or {}).get("covering", "unknown")

        if time.monotonic() >= deadline:
            raise ElementNotReceivingEventsError("<ElementHandle>", covering)

        await _async_backoff_sleep(attempt)
        attempt += 1
