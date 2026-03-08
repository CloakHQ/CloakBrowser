"""cloakbrowser-human — Async human-like mouse movement and clicking.

Mirrors mouse.py but uses ``await`` for all Playwright calls and
``async_sleep_ms`` instead of ``sleep_ms``.
"""

from __future__ import annotations

import math
import random
from typing import Any, Protocol

from .config import HumanConfig, rand, rand_range, rand_int_range, async_sleep_ms
from .mouse import Point, _ease_in_out, _bezier, _random_control_points, click_target  # noqa: reuse pure math


class AsyncRawMouse(Protocol):
    async def move(self, x: float, y: float) -> None: ...
    async def down(self) -> None: ...
    async def up(self) -> None: ...
    async def wheel(self, delta_x: float, delta_y: float) -> None: ...


async def async_human_move(
    raw: AsyncRawMouse,
    start_x: float, start_y: float,
    end_x: float, end_y: float,
    cfg: HumanConfig,
) -> None:
    dist = math.hypot(end_x - start_x, end_y - start_y)
    if dist < 1:
        return

    steps = max(cfg.mouse_min_steps, min(cfg.mouse_max_steps, round(dist / cfg.mouse_steps_divisor)))
    start = Point(start_x, start_y)
    end = Point(end_x, end_y)
    cp1, cp2 = _random_control_points(start, end)

    burst_counter = 0
    burst_size = rand_int_range(cfg.mouse_burst_size)

    for i in range(steps + 1):
        progress = i / steps
        eased_t = _ease_in_out(progress)
        pt = _bezier(start, cp1, cp2, end, eased_t)

        wobble_amp = math.sin(math.pi * progress) * cfg.mouse_wobble_max
        wx = pt.x + (random.random() - 0.5) * 2 * wobble_amp
        wy = pt.y + (random.random() - 0.5) * 2 * wobble_amp

        await raw.move(round(wx), round(wy))

        burst_counter += 1
        if burst_counter >= burst_size and i < steps:
            await async_sleep_ms(rand_range(cfg.mouse_burst_pause))
            burst_counter = 0

    if random.random() < cfg.mouse_overshoot_chance:
        overshoot_dist = rand_range(cfg.mouse_overshoot_px)
        angle = math.atan2(end_y - start_y, end_x - start_x)
        await raw.move(round(end_x + math.cos(angle) * overshoot_dist),
                       round(end_y + math.sin(angle) * overshoot_dist))
        await async_sleep_ms(rand(30, 70))
        await raw.move(round(end_x + (random.random() - 0.5) * 4),
                       round(end_y + (random.random() - 0.5) * 4))


async def async_human_click(raw: AsyncRawMouse, is_input: bool, cfg: HumanConfig) -> None:
    aim_delay = rand_range(cfg.click_aim_delay_input) if is_input else rand_range(cfg.click_aim_delay_button)
    await async_sleep_ms(aim_delay)
    hold_time = rand_range(cfg.click_hold_input) if is_input else rand_range(cfg.click_hold_button)
    await raw.down()
    await async_sleep_ms(hold_time)
    await raw.up()


async def async_human_idle(raw: AsyncRawMouse, seconds: float, cx: float, cy: float, cfg: HumanConfig) -> None:
    import time as _time
    end_time = _time.monotonic() + seconds
    x, y = cx, cy
    while _time.monotonic() < end_time:
        dx = (random.random() - 0.5) * 2 * cfg.idle_drift_px
        dy = (random.random() - 0.5) * 2 * cfg.idle_drift_px
        x += dx
        y += dy
        await raw.move(round(x), round(y))
        await async_sleep_ms(rand_range(cfg.idle_pause_range))
