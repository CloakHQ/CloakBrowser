"""Playwright-style actionability checks for the humanize layer (async).

Async mirror of actionability.py — same logic, uses asyncio.sleep and await.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, FrozenSet, Optional

from .actionability import (
    ActionabilityError,
    ElementNotAttachedError,
    ElementNotVisibleError,
    ElementNotStableError,
    ElementNotEnabledError,
    ElementNotEditableError,
    ElementNotReceivingEventsError,
    ElementTargetChangedError,
    _BACKOFF_MS,
    _boxes_differ,
    _POINTER_EVENTS_HANDLE_JS,
)
from .stealth_dom import (
    build_actionable_js, build_box_js, build_validate_js, async_eval_parsed,
    EVALUATION_FAILED, NOT_FOUND, OK, STALE, UNSUPPORTED,
    StealthEvaluationError, StealthWorldUnavailableError,
    UnsupportedHumanizeSelectorError,
)


async def _async_backoff_sleep(attempt: int) -> None:
    idx = min(attempt, len(_BACKOFF_MS) - 1)
    await asyncio.sleep(_BACKOFF_MS[idx] / 1000.0)


# ---------------------------------------------------------------------------
# Pre-scroll actionability
# ---------------------------------------------------------------------------

async def _async_stealth_actionable(page: Any, selector: str, checks: FrozenSet[str]) -> None:
    """Async isolated-world actionability read with no Playwright fallback."""
    world = getattr(page, "_stealth_world", None)
    if world is None:
        raise StealthWorldUnavailableError()
    status, data = await async_eval_parsed(world, build_actionable_js(selector))
    if status == UNSUPPORTED:
        raise UnsupportedHumanizeSelectorError(selector)
    if status == EVALUATION_FAILED:
        raise StealthEvaluationError(selector)
    if status == NOT_FOUND:
        raise ElementNotAttachedError(selector)
    if "visible" in checks and not data.get("visible"):
        raise ElementNotVisibleError(selector)
    if "enabled" in checks and not data.get("enabled"):
        raise ElementNotEnabledError(selector)
    if "editable" in checks and not data.get("editable"):
        raise ElementNotEditableError(selector)


async def _async_read_box(page: Any, selector: str, remaining_ms: float) -> Optional[dict]:
    """Async isolated-world geometry read with no Playwright fallback."""
    world = getattr(page, "_stealth_world", None)
    if world is None:
        raise StealthWorldUnavailableError()
    status, data = await async_eval_parsed(world, build_box_js(selector))
    if status == OK:
        return data["box"]
    if status == NOT_FOUND:
        return None
    if status == UNSUPPORTED:
        raise UnsupportedHumanizeSelectorError(selector)
    raise StealthEvaluationError(selector)


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
            await _async_stealth_actionable(page, selector, checks)
            return

        except (ActionabilityError, StealthEvaluationError) as e:
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

        try:
            box1 = await _async_read_box(page, selector, remaining_ms)
            if box1 is None:
                raise ElementNotAttachedError(selector)

            await asyncio.sleep(0.1)

            box2 = await _async_read_box(page, selector, remaining_ms)
            if box2 is None:
                raise ElementNotAttachedError(selector)
        except StealthEvaluationError:
            if time.monotonic() >= deadline:
                raise
            await _async_backoff_sleep(attempt)
            attempt += 1
            continue

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
    target_id: int,
    gen: int,
    x: float,
    y: float,
    stealth: Any = None,
    timeout: float = 5000,
) -> None:
    deadline = time.monotonic() + timeout / 1000.0
    attempt = 0
    last_miss: Optional[str] = None
    world = stealth if stealth is not None else getattr(page, "_stealth_world", None)
    if world is None:
        raise StealthWorldUnavailableError()
    if not isinstance(target_id, int) or not isinstance(gen, int):
        raise StealthEvaluationError(selector)

    while True:
        status, data = await async_eval_parsed(
            world, build_validate_js(selector, target_id, gen, x, y)
        )
        if status == UNSUPPORTED:
            raise UnsupportedHumanizeSelectorError(selector)
        if status == STALE:
            raise ElementTargetChangedError(selector)
        if status == NOT_FOUND:
            raise ElementNotAttachedError(selector)
        if status == EVALUATION_FAILED:
            if time.monotonic() >= deadline:
                raise StealthEvaluationError(selector)
        elif data.get("hit", False):
            return
        else:
            last_miss = data.get("covering", "unknown")
            if time.monotonic() >= deadline:
                raise ElementNotReceivingEventsError(selector, last_miss)

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
