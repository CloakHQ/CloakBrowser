"""Playwright-style actionability checks for the humanize layer (sync).

Checks: attached, visible, stable, enabled, editable, receives pointer events.
Retry loop with backoff matching Playwright internals: [100, 250, 500, 1000]ms.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, FrozenSet, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error hierarchy — all subclass RuntimeError for backward compat
# ---------------------------------------------------------------------------

class ActionabilityError(RuntimeError):
    """Base for all actionability failures."""

    def __init__(self, selector: str, check: str, message: str):
        self.selector = selector
        self.check = check
        super().__init__(f"Element {selector!r} failed {check} check: {message}")


class ElementNotAttachedError(ActionabilityError):
    def __init__(self, selector: str):
        super().__init__(selector, "attached", "element not found in DOM")


class ElementNotVisibleError(ActionabilityError):
    def __init__(self, selector: str):
        super().__init__(selector, "visible", "element is not visible")


class ElementNotStableError(ActionabilityError):
    def __init__(self, selector: str):
        super().__init__(selector, "stable", "element position is still changing")


class ElementNotEnabledError(ActionabilityError):
    def __init__(self, selector: str):
        super().__init__(selector, "enabled", "element is disabled")


class ElementNotEditableError(ActionabilityError):
    def __init__(self, selector: str):
        super().__init__(selector, "editable", "element is not editable")


class ElementNotReceivingEventsError(ActionabilityError):
    def __init__(self, selector: str, covering_tag: str = "unknown"):
        super().__init__(
            selector,
            "pointer_events",
            f"element is covered by <{covering_tag}>",
        )


# ---------------------------------------------------------------------------
# Check-set constants
# ---------------------------------------------------------------------------

CHECKS_CLICK: FrozenSet[str] = frozenset({"attached", "visible", "enabled", "pointer_events"})
CHECKS_HOVER: FrozenSet[str] = frozenset({"attached", "visible", "pointer_events"})
CHECKS_INPUT: FrozenSet[str] = frozenset({"attached", "visible", "enabled", "editable", "pointer_events"})
CHECKS_FOCUS: FrozenSet[str] = frozenset({"attached", "visible", "enabled"})
CHECKS_CHECK: FrozenSet[str] = frozenset({"attached", "visible", "enabled", "pointer_events"})

_BACKOFF_MS = [100, 250, 500, 1000]


def _backoff_sleep(attempt: int) -> None:
    idx = min(attempt, len(_BACKOFF_MS) - 1)
    time.sleep(_BACKOFF_MS[idx] / 1000.0)


# ---------------------------------------------------------------------------
# Pre-scroll actionability: attached, visible, enabled, editable
# ---------------------------------------------------------------------------

def ensure_actionable(
    page: Any,
    selector: str,
    checks: FrozenSet[str],
    timeout: float = 30000,
    force: bool = False,
) -> None:
    """Wait for element to pass actionability checks (pre-scroll).

    Retries with backoff until *timeout* ms elapsed.
    Raises a specific ``ActionabilityError`` subclass on failure.
    If *force* is True, returns immediately.
    """
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
                    loc.wait_for(state="attached", timeout=max(1, min(remaining_ms, 2000)))
                except Exception:
                    raise ElementNotAttachedError(selector)

            if "visible" in checks:
                if not loc.is_visible():
                    raise ElementNotVisibleError(selector)

            if "enabled" in checks:
                if not loc.is_enabled():
                    raise ElementNotEnabledError(selector)

            if "editable" in checks:
                if not loc.is_editable():
                    raise ElementNotEditableError(selector)

            return

        except ActionabilityError as e:
            last_error = e
            if time.monotonic() >= deadline:
                raise last_error
            _backoff_sleep(attempt)
            attempt += 1


# ---------------------------------------------------------------------------
# Post-scroll stability check
# ---------------------------------------------------------------------------

def _boxes_differ(a: dict, b: dict) -> bool:
    return (
        abs(a["x"] - b["x"]) > 1
        or abs(a["y"] - b["y"]) > 1
        or abs(a["width"] - b["width"]) > 1
        or abs(a["height"] - b["height"]) > 1
    )


def ensure_stable(
    page: Any,
    selector: str,
    timeout: float = 5000,
) -> None:
    """Wait for element position to stabilize (two samples 100ms apart).

    Only call after scroll — skip if element was already in viewport.
    """
    deadline = time.monotonic() + timeout / 1000.0
    attempt = 0

    while True:
        remaining_ms = max(0, (deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            raise ElementNotStableError(selector)

        loc = page.locator(selector).first
        box1 = loc.bounding_box(timeout=max(1, min(remaining_ms, 1000)))
        if box1 is None:
            raise ElementNotAttachedError(selector)

        time.sleep(0.1)

        box2 = loc.bounding_box(timeout=max(1, min(remaining_ms, 1000)))
        if box2 is None:
            raise ElementNotAttachedError(selector)

        if not _boxes_differ(box1, box2):
            return

        if time.monotonic() >= deadline:
            raise ElementNotStableError(selector)

        _backoff_sleep(attempt)
        attempt += 1


# ---------------------------------------------------------------------------
# Pointer-events check (post-scroll, at actual click coordinates)
# ---------------------------------------------------------------------------

_POINTER_EVENTS_LOCATOR_JS = """(expected, coords) => {
    const target = document.elementFromPoint(coords.x, coords.y);
    if (!target) return { hit: false, reason: 'no_element_at_point', covering: 'none' };
    let node = target;
    while (node) { if (node === expected) return { hit: true }; node = node.parentNode; }
    if (expected.contains(target)) return { hit: true };
    return { hit: false, reason: 'covered', covering: target.tagName || 'unknown' };
}"""

_POINTER_EVENTS_HANDLE_JS = """(expected, coords) => {
    const target = document.elementFromPoint(coords.x, coords.y);
    if (!target) return { hit: false, reason: 'no_element_at_point', covering: 'none' };
    let node = target;
    while (node) { if (node === expected) return { hit: true }; node = node.parentNode; }
    if (expected.contains(target)) return { hit: true };
    return { hit: false, reason: 'covered', covering: target.tagName || 'unknown' };
}"""


def check_pointer_events(
    page: Any,
    selector: str,
    x: float,
    y: float,
    stealth: Any = None,
    timeout: float = 5000,
) -> None:
    """Check that elementFromPoint(x, y) hits the expected element.

    Uses locator.evaluate() so all Playwright selector types work
    (text=, role=, XPath, CSS, etc.). Retries with backoff for transient overlays.
    """
    deadline = time.monotonic() + timeout / 1000.0
    attempt = 0
    coords = {"x": x, "y": y}

    while True:
        try:
            loc = page.locator(selector).first
            result = loc.evaluate(_POINTER_EVENTS_LOCATOR_JS, coords)
        except Exception as exc:
            logger.debug("pointer_events check failed for %r: %s", selector, exc)
            result = None

        if result and result.get("hit", False):
            return

        covering = (result or {}).get("covering", "unknown")

        if time.monotonic() >= deadline:
            raise ElementNotReceivingEventsError(selector, covering)

        _backoff_sleep(attempt)
        attempt += 1


# ---------------------------------------------------------------------------
# ElementHandle variant
# ---------------------------------------------------------------------------

def ensure_actionable_handle(
    page: Any,
    el: Any,
    checks: FrozenSet[str],
    timeout: float = 30000,
    force: bool = False,
) -> None:
    """Actionability checks for ElementHandle (no selector needed).

    Uses Playwright's wait_for_element_state where available.
    """
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
                    el.wait_for_element_state("visible", timeout=max(1, min(remaining_ms, 2000)))
                except Exception:
                    raise ElementNotVisibleError(label)

            if "enabled" in checks:
                try:
                    el.wait_for_element_state("enabled", timeout=max(1, min(remaining_ms, 2000)))
                except Exception:
                    raise ElementNotEnabledError(label)

            if "editable" in checks:
                try:
                    el.wait_for_element_state("editable", timeout=max(1, min(remaining_ms, 2000)))
                except Exception:
                    raise ElementNotEditableError(label)

            return

        except ActionabilityError as e:
            last_error = e
            if time.monotonic() >= deadline:
                raise last_error
            _backoff_sleep(attempt)
            attempt += 1


def check_pointer_events_handle(
    page: Any,
    el: Any,
    x: float,
    y: float,
    timeout: float = 5000,
) -> None:
    """Pointer-events check for ElementHandle."""
    deadline = time.monotonic() + timeout / 1000.0
    attempt = 0

    coords = {"x": x, "y": y}

    while True:
        try:
            result = el.evaluate(_POINTER_EVENTS_HANDLE_JS, coords)
        except Exception:
            result = None

        if result and result.get("hit", False):
            return

        covering = (result or {}).get("covering", "unknown")

        if time.monotonic() >= deadline:
            raise ElementNotReceivingEventsError("<ElementHandle>", covering)

        _backoff_sleep(attempt)
        attempt += 1
