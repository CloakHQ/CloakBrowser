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


async def _async_backoff_sleep(attempt: int) -> None:
    idx = min(attempt, len(_BACKOFF_MS) - 1)
    await asyncio.sleep(_BACKOFF_MS[idx] / 1000.0)


# ---------------------------------------------------------------------------
# Pre-scroll actionability
# ---------------------------------------------------------------------------

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

        loc = page.locator(selector).first
        box1 = await loc.bounding_box(timeout=max(1, min(remaining_ms, 1000)))
        if box1 is None:
            raise ElementNotAttachedError(selector)

        await asyncio.sleep(0.1)

        box2 = await loc.bounding_box(timeout=max(1, min(remaining_ms, 1000)))
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
