"""Playwright-style actionability checks for the humanize layer (sync).

Checks: attached, visible, stable, enabled, editable, receives pointer events.
Retry loop with backoff matching Playwright internals: [100, 250, 500, 1000]ms.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, FrozenSet, Optional, Tuple

from .stealth_dom import (
    build_actionable_js, build_box_js, build_pointer_js, eval_parsed,
    OK, NOT_FOUND, UNSUPPORTED,
)

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

def _stealth_actionable(page: Any, selector: str, checks: FrozenSet[str]) -> bool:
    """Run the actionability checks through the isolated world.

    Returns True when handled (raising the specific ``ActionabilityError`` on a
    failed check), or False when the selector/world is unsupported so the caller
    falls back to the regular Playwright read.
    """
    world = getattr(page, "_stealth_world", None)
    if world is None:
        return False
    status, data = eval_parsed(world, build_actionable_js(selector))
    if status == UNSUPPORTED:
        return False
    if status == NOT_FOUND:
        # Every check-set includes 'attached'; not present yet -> raise so the
        # retry loop backs off and re-reads in-world (mirrors wait_for(attached)).
        raise ElementNotAttachedError(selector)
    if "visible" in checks and not data.get("visible"):
        raise ElementNotVisibleError(selector)
    if "enabled" in checks and not data.get("enabled"):
        raise ElementNotEnabledError(selector)
    if "editable" in checks and not data.get("editable"):
        raise ElementNotEditableError(selector)
    return True


def _read_box(page: Any, selector: str, remaining_ms: float) -> Optional[dict]:
    """Bounding box via the isolated world, falling back to Playwright.

    Returns the box dict, or None when the element is not present. Only an
    *unsupported* selector (or missing world) reaches Playwright's
    ``bounding_box``; a genuine not-found stays in-world and returns None.
    """
    world = getattr(page, "_stealth_world", None)
    if world is not None:
        status, data = eval_parsed(world, build_box_js(selector))
        if status == OK:
            return data["box"]
        if status == NOT_FOUND:
            return None
        # UNSUPPORTED -> Playwright below
    try:
        loc = page.locator(selector).first
        return loc.bounding_box(timeout=max(1, min(remaining_ms, 1000)))
    except Exception:
        return None


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
            # Prefer the isolated-world read; fall back to Playwright's locator
            # predicates only for selector grammar the isolated world can't resolve.
            if not _stealth_actionable(page, selector, checks):
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

        box1 = _read_box(page, selector, remaining_ms)
        if box1 is None:
            raise ElementNotAttachedError(selector)

        time.sleep(0.1)

        box2 = _read_box(page, selector, remaining_ms)
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

# data.box is page-space (from bounding_box); rect is frame-local. Their delta
# is the iframe offset, needed to map page-space click coords into the frame's
# own viewport before elementFromPoint. For main-frame elements the offset is 0.
_POINTER_EVENTS_LOCATOR_JS = """(expected, data) => {
    const rect = expected.getBoundingClientRect();
    const frameOffsetX = data.box ? data.box.x - rect.x : 0;
    const frameOffsetY = data.box ? data.box.y - rect.y : 0;
    const target = document.elementFromPoint(data.x - frameOffsetX, data.y - frameOffsetY);
    if (!target) return { hit: false, reason: 'no_element_at_point', covering: 'none' };
    let node = target;
    while (node) { if (node === expected) return { hit: true }; node = node.parentNode; }
    if (expected.contains(target)) return { hit: true };
    return { hit: false, reason: 'covered', covering: target.tagName || 'unknown' };
}"""

_POINTER_EVENTS_HANDLE_JS = """(expected, data) => {
    const rect = expected.getBoundingClientRect();
    const frameOffsetX = data.box ? data.box.x - rect.x : 0;
    const frameOffsetY = data.box ? data.box.y - rect.y : 0;
    const target = document.elementFromPoint(data.x - frameOffsetX, data.y - frameOffsetY);
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
    last_miss: Optional[str] = None

    while True:
        # Isolated-world hit test; the passed-in ``stealth`` world is reused,
        # falling back to Playwright only for unsupported selectors.
        world = stealth if stealth is not None else getattr(page, "_stealth_world", None)
        result: Optional[dict] = None
        handled = False
        if world is not None:
            status, data = eval_parsed(world, build_pointer_js(selector, x, y))
            if status == OK:
                result = {"hit": data.get("hit", False), "covering": data.get("covering", "unknown")}
                handled = True
            elif status == NOT_FOUND:
                result = None  # indeterminate -> proceed (fail-open)
                handled = True
        if not handled:
            try:
                loc = page.locator(selector).first
                box = loc.bounding_box(timeout=max(1, min((deadline - time.monotonic()) * 1000, 1000)))
                result = loc.evaluate(_POINTER_EVENTS_LOCATOR_JS, {"x": x, "y": y, "box": box})
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

    while True:
        try:
            box = el.bounding_box()
            result = el.evaluate(_POINTER_EVENTS_HANDLE_JS, {"x": x, "y": y, "box": box})
        except Exception:
            result = None

        # Proceed if the check confirms a hit, or if it could not be determined
        # (None) — failing closed would block legitimate clicks.
        if result is None or result.get("hit", False):
            return

        covering = (result or {}).get("covering", "unknown")

        if time.monotonic() >= deadline:
            raise ElementNotReceivingEventsError("<ElementHandle>", covering)

        _backoff_sleep(attempt)
        attempt += 1
