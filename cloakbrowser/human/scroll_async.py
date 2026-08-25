"""cloakbrowser-human — Async human-like scrolling via mouse wheel events.

Mirrors scroll.py but uses ``await`` for all Playwright calls and
``async_sleep_ms`` instead of ``sleep_ms``.
"""

from __future__ import annotations

import asyncio
import math
import random
import time
from typing import Any, Awaitable, Callable, Optional, Tuple

from .config import HumanConfig, rand, rand_range, rand_int_range, async_sleep_ms
from .mouse_async import AsyncRawMouse, async_human_move
from .scroll import _is_in_viewport, _SCROLL_JS
from .stealth_dom import (
    build_box_js, async_eval_parsed, EVALUATION_FAILED, NOT_FOUND, OK, UNSUPPORTED,
    StealthEvaluationError, StealthWorldUnavailableError,
    UnsupportedHumanizeSelectorError, _VIEWPORT_JS,
)


async def _get_element_box_async(
    page: Any, selector: str, timeout: float = 30000,
) -> Optional[dict]:
    """Async isolated-world geometry read with no Playwright fallback."""
    world = getattr(page, "_stealth_world", None)
    if world is None:
        raise StealthWorldUnavailableError()
    deadline = time.monotonic() + max(0, timeout) / 1000.0
    status, data = await async_eval_parsed(world, build_box_js(selector))
    while status in (NOT_FOUND, EVALUATION_FAILED) and time.monotonic() < deadline:
        await asyncio.sleep(0.05)
        status, data = await async_eval_parsed(world, build_box_js(selector))
    if status == OK:
        box = dict(data["box"])
        box["targetId"] = data["targetId"]
        box["gen"] = data["gen"]
        return box
    if status == NOT_FOUND:
        return None
    if status == UNSUPPORTED:
        raise UnsupportedHumanizeSelectorError(selector)
    raise StealthEvaluationError(selector)


async def _async_read_scroll_state(page: Any) -> dict:
    """Read vertical scroll state only through the isolated world."""
    world = getattr(page, "_stealth_world", None)
    if world is None:
        raise StealthWorldUnavailableError()
    try:
        state = await world.evaluate(_SCROLL_JS)
    except Exception as exc:
        raise StealthEvaluationError("<scroll-state>") from exc
    if not isinstance(state, dict):
        raise StealthEvaluationError("<scroll-state>")
    return state


async def _async_smooth_wheel(raw: AsyncRawMouse, delta: int, cfg: HumanConfig) -> None:
    """Send one logical scroll as a burst of small wheel events (like real inertia)."""
    abs_d = abs(delta)
    sign = 1 if delta > 0 else -1
    sent = 0
    while sent < abs_d:
        step_size = rand(20, 40)
        chunk = min(step_size, abs_d - sent)
        await raw.wheel(0, round(chunk) * sign)
        sent += chunk
        await async_sleep_ms(rand(8, 20))


async def async_human_scroll_into_view(
    page: Any,
    raw: AsyncRawMouse,
    get_box: Callable[[], Awaitable[Optional[dict]]],
    cursor_x: float, cursor_y: float,
    cfg: HumanConfig,
) -> Tuple[dict, float, float, bool]:
    """Humanized scrolling using an arbitrary async ``get_box`` callable.

    Used by both ``async_scroll_to_element`` (selector-based) and the
    ElementHandle / Locator ``scroll_into_view_if_needed`` patches so all
    scrolling paths share the same accelerate \u2192 cruise \u2192 decelerate
    \u2192 overshoot behavior.

    Returns ``(box, cursor_x, cursor_y, did_scroll)`` \u2014 *did_scroll* is False
    when the element was already in the viewport.
    """
    viewport = page.viewport_size
    if not viewport:
        # Headed launches default to no_viewport so the page tracks the real OS
        # window; page.viewport_size is then None. Read the live window dimensions
        # through the isolated world, consistent with the other geometry reads here.
        world = getattr(page, "_stealth_world", None)
        if world is None:
            raise StealthWorldUnavailableError()
        try:
            viewport = await world.evaluate(_VIEWPORT_JS)
        except Exception as exc:
            raise StealthEvaluationError("<viewport>") from exc
    if not viewport or not viewport.get("height"):
        raise RuntimeError("Viewport size not available")

    viewport_height = viewport["height"]
    viewport_width = viewport["width"]

    box = await get_box()
    if box is None:
        raise RuntimeError("Element not found while scrolling into view")

    if _is_in_viewport(box, viewport_height, cfg):
        return box, cursor_x, cursor_y, False

    # Already fully visible but off-center, with the page pinned at the boundary
    # in the needed direction: scrolling can't help, so don't waste the budget.
    fully_visible = box["y"] >= 0 and box["y"] + box["height"] <= viewport_height
    if fully_visible:
        zone_mid = viewport_height * (cfg.scroll_target_zone[0] + cfg.scroll_target_zone[1]) / 2
        need_up = box["y"] + box["height"] / 2 < zone_mid
        scroll = await _async_read_scroll_state(page)
        if (scroll["y"] <= 0) if need_up else (scroll["y"] >= scroll["maxY"]):
            return box, cursor_x, cursor_y, False

    # Move cursor into scroll area
    scroll_area_x = round(viewport_width * rand(0.3, 0.7))
    scroll_area_y = round(viewport_height * rand(0.3, 0.7))
    await async_human_move(raw, cursor_x, cursor_y, scroll_area_x, scroll_area_y, cfg)
    cursor_x = scroll_area_x
    cursor_y = scroll_area_y
    await async_sleep_ms(rand_range(cfg.scroll_pre_move_delay))

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

        await _async_smooth_wheel(raw, delta, cfg)
        scrolled += abs(delta)
        await async_sleep_ms(pause)

        # Check visibility every 3 steps
        if i % 3 == 2 or i == total_clicks - 1:
            box = await get_box()
            if box and _is_in_viewport(box, viewport_height, cfg):
                break
        if scrolled >= abs_distance * 1.1:
            break

    # Optional overshoot + correction
    if random.random() < cfg.scroll_overshoot_chance:
        overshoot_px = round(rand_range(cfg.scroll_overshoot_px)) * direction
        await _async_smooth_wheel(raw, overshoot_px, cfg)
        await async_sleep_ms(rand_range(cfg.scroll_settle_delay))
        corrections = rand_int_range((1, 2))
        for _ in range(corrections):
            corr_delta = round(rand(40, 80)) * -direction
            await _async_smooth_wheel(raw, corr_delta, cfg)
            await async_sleep_ms(rand(100, 250))

    # Settle
    await async_sleep_ms(rand_range(cfg.scroll_settle_delay))

    box = await get_box()
    if box is None:
        raise RuntimeError("Element lost after scrolling into view")

    return box, cursor_x, cursor_y, True


async def async_scroll_to_element(
    page: Any,
    raw: AsyncRawMouse,
    selector: str,
    cursor_x: float, cursor_y: float,
    cfg: HumanConfig,
    timeout: float = 30000,
) -> Tuple[dict, float, float, bool]:
    """Selector-based humanized scroll (async).

    ``timeout`` bounds isolated-world geometry polling so callers such as
    ``page.click('#x', timeout=5000)`` can wait for slow elements (#172).

    Returns ``(box, cursor_x, cursor_y, did_scroll)``.
    """
    async def _get():
        return await _get_element_box_async(page, selector, timeout)
    return await async_human_scroll_into_view(
        page, raw, _get, cursor_x, cursor_y, cfg,
    )
