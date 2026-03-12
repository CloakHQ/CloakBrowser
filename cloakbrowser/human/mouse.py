"""cloakbrowser-human — Human-like mouse movement and clicking."""

from __future__ import annotations

import math
import random
from typing import Any, Protocol, Tuple

from .config import HumanConfig, rand, rand_range, rand_int_range, sleep_ms


class RawMouse(Protocol):
    def move(self, x: float, y: float) -> None: ...
    def down(self) -> None: ...
    def up(self) -> None: ...
    def wheel(self, delta_x: float, delta_y: float) -> None: ...


class Point:
    __slots__ = ("x", "y")
    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y


def _ease_in_out(t: float) -> float:
    if t < 0.5:
        return 4 * t * t * t
    return 1 - pow(-2 * t + 2, 3) / 2


def _bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: float) -> Point:
    u = 1 - t
    uu = u * u
    uuu = uu * u
    tt = t * t
    ttt = tt * t
    return Point(
        uuu * p0.x + 3 * uu * t * p1.x + 3 * u * tt * p2.x + ttt * p3.x,
        uuu * p0.y + 3 * uu * t * p1.y + 3 * u * tt * p2.y + ttt * p3.y,
    )


def _random_control_points(start: Point, end: Point) -> Tuple[Point, Point]:
    dx = end.x - start.x
    dy = end.y - start.y
    dist = math.hypot(dx, dy) or 1
    px = -dy / dist
    py = dx / dist
    bias1 = rand(-0.3, 0.3) * dist
    bias2 = rand(-0.3, 0.3) * dist
    return (
        Point(start.x + dx * 0.25 + px * bias1, start.y + dy * 0.25 + py * bias1),
        Point(start.x + dx * 0.75 + px * bias2, start.y + dy * 0.75 + py * bias2),
    )


def human_move(
    raw: RawMouse,
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

        raw.move(round(wx), round(wy))

        burst_counter += 1
        if burst_counter >= burst_size and i < steps:
            sleep_ms(rand_range(cfg.mouse_burst_pause))
            burst_counter = 0

    if random.random() < cfg.mouse_overshoot_chance:
        overshoot_dist = rand_range(cfg.mouse_overshoot_px)
        angle = math.atan2(end_y - start_y, end_x - start_x)
        raw.move(round(end_x + math.cos(angle) * overshoot_dist),
                 round(end_y + math.sin(angle) * overshoot_dist))
        sleep_ms(rand(30, 70))
        raw.move(round(end_x + (random.random() - 0.5) * 4),
                 round(end_y + (random.random() - 0.5) * 4))


def click_target(box: dict, is_input: bool, cfg: HumanConfig) -> Point:
    if is_input:
        x_frac = rand_range(cfg.click_input_x_range)
        y_frac = rand(0.30, 0.70)
    else:
        x_frac = rand(0.35, 0.65)
        y_frac = rand(0.35, 0.65)
    return Point(round(box["x"] + box["width"] * x_frac),
                 round(box["y"] + box["height"] * y_frac))


def human_click(raw: RawMouse, is_input: bool, cfg: HumanConfig) -> None:
    aim_delay = rand_range(cfg.click_aim_delay_input) if is_input else rand_range(cfg.click_aim_delay_button)
    sleep_ms(aim_delay)
    hold_time = rand_range(cfg.click_hold_input) if is_input else rand_range(cfg.click_hold_button)
    raw.down()
    sleep_ms(hold_time)
    raw.up()


def human_idle(raw: RawMouse, seconds: float, cx: float, cy: float, cfg: HumanConfig) -> None:
    import time as _time
    end_time = _time.monotonic() + seconds
    x, y = cx, cy
    while _time.monotonic() < end_time:
        dx = (random.random() - 0.5) * 2 * cfg.idle_drift_px
        dy = (random.random() - 0.5) * 2 * cfg.idle_drift_px
        x += dx
        y += dy
        raw.move(round(x), round(y))
        sleep_ms(rand_range(cfg.idle_pause_range))
