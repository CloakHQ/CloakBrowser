"""cloakbrowser-human — Async human-like scrolling via mouse wheel events.

Mirrors scroll.py but uses ``await`` for all Playwright calls and
``async_sleep_ms`` instead of ``sleep_ms``.
"""

from __future__ import annotations

import math
import random
from typing import Any, Optional, Tuple

from .config import HumanConfig, rand, rand_range, rand_int_range, async_sleep_ms
from .mouse_async import AsyncRawMouse, async_human_move
from .scroll import _is_in_viewport


async def _get_element_box_async(page: Any, selector: str) -> Optional[dict]:
    try:
        el = page.locator(selector).first
        return await el.bounding_box(timeout=2000)
    except Exception:
        return None


async def async_scroll_to_element(
    page: Any,
    raw: AsyncRawMouse,
    selector: str,
    cursor_x: float, cursor_y: float,
    cfg: HumanConfig,
) -> Tuple[dict, float, float]:
    viewport = page.viewport_size
    if not viewport:
        raise RuntimeError("Viewport size not available")

    viewport_height = viewport["height"]
    viewport_width = viewport["width"]

    box = await _get_element_box_async(page, selector)
    if box is None:
        await async_sleep_ms(200)
        box = await _get_element_box_async(page, selector)
        if box is None:
            raise RuntimeError(f"Element not found: {selector}")

    if _is_in_viewport(box, viewport_height, cfg):
        return box, cursor_x, cursor_y

    scroll_area_x = round(viewport_width * rand(0.3, 0.7))
    scroll_area_y = round(viewport_height * rand(0.3, 0.7))
    await async_human_move(raw, cursor_x, cursor_y, scroll_area_x, scroll_area_y, cfg)
    cursor_x = scroll_area_x
    cursor_y = scroll_area_y
    await async_sleep_ms(rand_range(cfg.scroll_pre_move_delay))

    target_y = viewport_height * rand(cfg.scroll_target_zone[0], cfg.scroll_target_zone[1])
    element_center = box["y"] + box["height"] / 2
    distance_to_scroll = element_center - target_y

    direction = 1 if distance_to_scroll > 0 else -1
    abs_distance = abs(distance_to_scroll)
    avg_delta = (cfg.scroll_delta_base[0] + cfg.scroll_delta_base[1]) / 2
    total_clicks = max(3, math.ceil(abs_distance / avg_delta))
    accel_steps = rand_int_range(cfg.scroll_accel_steps)
    decel_steps = rand_int_range(cfg.scroll_decel_steps)

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

        await raw.wheel(0, delta)
        scrolled += abs(delta)
        await async_sleep_ms(pause)

        if i % 3 == 2 or i == total_clicks - 1:
            box = await _get_element_box_async(page, selector)
            if box and _is_in_viewport(box, viewport_height, cfg):
                break
        if scrolled >= abs_distance * 1.1:
            break

    if random.random() < cfg.scroll_overshoot_chance:
        overshoot_px = rand_range(cfg.scroll_overshoot_px) * direction
        await raw.wheel(0, round(overshoot_px))
        await async_sleep_ms(rand_range(cfg.scroll_settle_delay))
        corrections = rand_int_range((1, 2))
        for _ in range(corrections):
            corr_delta = rand(40, 80) * -direction
            await raw.wheel(0, round(corr_delta))
            await async_sleep_ms(rand(100, 250))

    await async_sleep_ms(rand_range(cfg.scroll_settle_delay))

    box = await _get_element_box_async(page, selector)
    if box is None:
        raise RuntimeError(f"Element lost after scrolling: {selector}")

    return box, cursor_x, cursor_y
