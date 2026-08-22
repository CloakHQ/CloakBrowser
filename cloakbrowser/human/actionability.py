"""Playwright-style actionability checks for the humanize layer (sync).

Checks: attached, visible, stable, enabled, editable, receives pointer events.
Retry loop with backoff matching Playwright internals: [100, 250, 500, 1000]ms.
"""

from __future__ import annotations

import time
from typing import Any, FrozenSet, Optional

from .stealth_dom import (
    build_actionable_js, build_box_js, build_validate_js, eval_parsed,
    EVALUATION_FAILED, NOT_FOUND, OK, STALE, UNSUPPORTED,
    StealthEvaluationError, StealthWorldUnavailableError,
    UnsupportedHumanizeSelectorError,
)

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


class ElementTargetChangedError(ActionabilityError):
    def __init__(self, selector: str):
        super().__init__(
            selector,
            "target_identity",
            "resolved element changed before pointer dispatch",
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

def _stealth_actionable(page: Any, selector: str, checks: FrozenSet[str]) -> None:
    """Run actionability checks exclusively through the isolated world."""
    world = getattr(page, "_stealth_world", None)
    if world is None:
        raise StealthWorldUnavailableError()
    status, data = eval_parsed(world, build_actionable_js(selector))
    if status == UNSUPPORTED:
        raise UnsupportedHumanizeSelectorError(selector)
    if status == EVALUATION_FAILED:
        raise StealthEvaluationError(selector)
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


def _read_box(page: Any, selector: str, remaining_ms: float) -> Optional[dict]:
    """Read geometry exclusively through the isolated world."""
    world = getattr(page, "_stealth_world", None)
    if world is None:
        raise StealthWorldUnavailableError()
    status, data = eval_parsed(world, build_box_js(selector))
    if status == OK:
        return data["box"]
    if status == NOT_FOUND:
        return None
    if status == UNSUPPORTED:
        raise UnsupportedHumanizeSelectorError(selector)
    raise StealthEvaluationError(selector)


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
            _stealth_actionable(page, selector, checks)
            return

        except (ActionabilityError, StealthEvaluationError) as e:
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

        try:
            box1 = _read_box(page, selector, remaining_ms)
            if box1 is None:
                raise ElementNotAttachedError(selector)

            time.sleep(0.1)

            box2 = _read_box(page, selector, remaining_ms)
            if box2 is None:
                raise ElementNotAttachedError(selector)
        except StealthEvaluationError:
            if time.monotonic() >= deadline:
                raise
            _backoff_sleep(attempt)
            attempt += 1
            continue

        if not _boxes_differ(box1, box2):
            return

        if time.monotonic() >= deadline:
            raise ElementNotStableError(selector)

        _backoff_sleep(attempt)
        attempt += 1


# ---------------------------------------------------------------------------
# Pointer-events check (post-scroll, at actual click coordinates)
# ---------------------------------------------------------------------------

# Legacy ElementHandle paths cannot use selector-based isolated-world identity.
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
    target_id: int,
    gen: int,
    x: float,
    y: float,
    stealth: Any = None,
    timeout: float = 5000,
) -> None:
    """Revalidate that the click point still hits the same resolved element.

    Callers skip this entirely when ``force=True`` (matching Playwright, where
    ``force`` bypasses all actionability checks).
    """
    deadline = time.monotonic() + timeout / 1000.0
    attempt = 0
    last_miss: Optional[str] = None
    world = stealth if stealth is not None else getattr(page, "_stealth_world", None)
    if world is None:
        raise StealthWorldUnavailableError()
    if not isinstance(target_id, int) or not isinstance(gen, int):
        raise StealthEvaluationError(selector)

    while True:
        status, data = eval_parsed(
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
