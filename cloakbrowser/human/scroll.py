"""cloakbrowser-human — Human-like scrolling via mouse wheel events."""

from __future__ import annotations

import math
import random
from typing import Any, Callable, Optional, Tuple

from .config import HumanConfig, rand, rand_range, rand_int_range, sleep_ms
from .mouse import RawMouse, human_move


def _is_in_viewport(bounds: dict, viewport_height: int, cfg: HumanConfig) -> bool:
    top_edge = bounds["y"]
    bottom_edge = bounds["y"] + bounds["height"]
    zone_top = viewport_height * cfg.scroll_target_zone[0]
    zone_bottom = viewport_height * cfg.scroll_target_zone[1]
    return top_edge >= zone_top and bottom_edge <= zone_bottom


def _get_element_box(page: Any, selector: str, timeout: float = 2000) -> Optional[dict]:
    """Locate ``selector`` and return its bounding box.

    The ``timeout`` is forwarded to Playwright's ``boundingBox(timeout=...)``
    so callers can extend it for slow-loading elements (#172).
    """
    try:
        el = page.locator(selector).first
        return el.bounding_box(timeout=timeout)
    except Exception:
        return None


def _smooth_wheel(raw: RawMouse, delta: int, cfg: HumanConfig) -> None:
    """Send one logical scroll as a burst of small wheel events (like real inertia)."""
    abs_d = abs(delta)
    sign = 1 if delta > 0 else -1
    sent = 0
    while sent < abs_d:
        step_size = rand(20, 40)
        chunk = min(step_size, abs_d - sent)
        raw.wheel(0, round(chunk) * sign)
        sent += chunk
        sleep_ms(rand(8, 20))


def human_scroll_into_view(
    page: Any,
    raw: RawMouse,
    get_box: Callable[[], Optional[dict]],
    cursor_x: float, cursor_y: float,
    cfg: HumanConfig,
) -> Tuple[dict, float, float]:
    """Humanized scrolling that uses an arbitrary ``get_box`` callable
    instead of a CSS selector.

    Used both by ``scroll_to_element`` (selector-based) and by
    ``ElementHandle.scroll_into_view_if_needed`` / ``Locator.scroll_into_view_if_needed``
    (handle-based) so the same accelerate \u2192 cruise \u2192 decelerate \u2192 overshoot
    behavior runs everywhere.
    """
    viewport = page.viewport_size
    if not viewport:
        raise RuntimeError("Viewport size not available")

    viewport_height = viewport["height"]
    viewport_width = viewport["width"]

    box = get_box()
    if box is None:
        sleep_ms(200)
        box = get_box()
        if box is None:
            raise RuntimeError("Element not found while scrolling into view")

    if _is_in_viewport(box, viewport_height, cfg):
        return box, cursor_x, cursor_y

    # Move cursor into scroll area
    scroll_area_x = round(viewport_width * rand(0.3, 0.7))
    scroll_area_y = round(viewport_height * rand(0.3, 0.7))
    human_move(raw, cursor_x, cursor_y, scroll_area_x, scroll_area_y, cfg)
    cursor_x = scroll_area_x
    cursor_y = scroll_area_y
    sleep_ms(rand_range(cfg.scroll_pre_move_delay))

    # Calculate scroll distance
    target_y = viewport_height * rand(cfg.scroll_target_zone[0], cfg.scroll_target_zone[1])
    element_center = box["y"] + box["height"] / 2
    distance_to_scroll = element_center - target_y

    direction = 1 if distance_to_scroll > 0 else -1
    abs_distance = abs(distance_to_scroll)
    avg_delta = (cfg.scroll_delta_base[0] + cfg.scroll_delta_base[1]) / 2
    total_clicks = max(3, math.ceil(abs_distance / avg_delta))
    accel_steps = rand_int_range(cfg.scroll_accel_steps)
    decel_steps = rand_int_range(cfg.scroll_decel_steps)

    # Scroll loop: accelerate → cruise → decelerate
    scrolled = 0
    for i in range(total_clicks):
        if i < accel_steps:
            delta = rand(80, 100)
            pause = rand_range(cfg.scroll_pause_slow)
        elif i >= total_clicks - decel_steps:
            delta = rand(60, 90)
            pause = rand_range(cfg.scroll_pause_slow)
        else:
            delta = rand_range(cfg.scroll_delta_base)
            pause = rand_range(cfg.scroll_pause_fast)

        delta *= 1 + (random.random() - 0.5) * 2 * cfg.scroll_delta_variance
        delta = round(delta) * direction

        _smooth_wheel(raw, delta, cfg)
        scrolled += abs(delta)
        sleep_ms(pause)

        # Check visibility every 3 steps
        if i % 3 == 2 or i == total_clicks - 1:
            box = get_box()
            if box and _is_in_viewport(box, viewport_height, cfg):
                break
        if scrolled >= abs_distance * 1.1:
            break

    # Optional overshoot + correction
    if random.random() < cfg.scroll_overshoot_chance:
        overshoot_px = round(rand_range(cfg.scroll_overshoot_px)) * direction
        _smooth_wheel(raw, overshoot_px, cfg)
        sleep_ms(rand_range(cfg.scroll_settle_delay))
        corrections = rand_int_range((1, 2))
        for _ in range(corrections):
            corr_delta = round(rand(40, 80)) * -direction
            _smooth_wheel(raw, corr_delta, cfg)
            sleep_ms(rand(100, 250))

    # Settle
    sleep_ms(rand_range(cfg.scroll_settle_delay))

    box = get_box()
    if box is None:
        raise RuntimeError("Element lost after scrolling into view")

    return box, cursor_x, cursor_y


def scroll_to_element(
    page: Any,
    raw: RawMouse,
    selector: str,
    cursor_x: float, cursor_y: float,
    cfg: HumanConfig,
    timeout: float = 2000,
) -> Tuple[dict, float, float]:
    """Selector-based humanized scroll.

    ``timeout`` is forwarded to ``locator.bounding_box(timeout=...)`` so callers
    such as ``page.click('#x', timeout=5000)`` can wait longer for slow elements
    (#172). Default stays at 2000ms when not specified.
    """
    return human_scroll_into_view(
        page, raw,
        lambda: _get_element_box(page, selector, timeout),
        cursor_x, cursor_y, cfg,
    )
