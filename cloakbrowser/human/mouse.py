"""cloakbrowser-human — Human-like mouse movement and clicking."""

from __future__ import annotations

import math
import random
from typing import Any, Callable, List, Optional, Protocol, Tuple

from .config import HumanConfig, rand, rand_lognormal, rand_range, rand_int_range, sleep_ms


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


def _random_control_points(start: Point, end: Point, curvature: float = 0.3) -> Tuple[Point, Point]:
    dx = end.x - start.x
    dy = end.y - start.y
    dist = math.hypot(dx, dy) or 1
    px = -dy / dist
    py = dx / dist
    # Both control points bend the same way more often than not: a hand
    # sweeps an arc, it rarely draws an S.
    bias1 = rand(-curvature, curvature) * dist
    bias2 = bias1 * rand(0.2, 1.2) if random.random() < 0.8 else rand(-curvature, curvature) * dist
    return (
        Point(start.x + dx * 0.25 + px * bias1, start.y + dy * 0.25 + py * bias1),
        Point(start.x + dx * 0.75 + px * bias2, start.y + dy * 0.75 + py * bias2),
    )


# ---------------------------------------------------------------------------
# Stroke planning (shared by the humanize engine and human_move)
# ---------------------------------------------------------------------------
#
# A pointing movement is a fast main stroke whose speed peaks early, then a
# slow approach to the target, often finished by a short corrective stroke
# (Meyer's optimised sub-movements; Plamondon's log-normal strokes). How long
# it takes grows with log2 of the distance (Fitts' law) and varies a lot from
# one move to the next. A mouse reports its position at a steady rate and
# only when it actually moved.

FRAME_MS = 1000 / 60  # pointer events arrive about once per display frame
_PEAK = (0.22, 0.38)  # where the speed peaks, as a fraction of the stroke time


def _progress_curve(peak: float) -> "Callable[[float], float]":
    """Smooth 0->1 distance curve whose speed peaks at ``peak`` of the time
    (a time-warped minimum-jerk profile: fast early, long slow tail)."""
    k = math.log(0.5) / math.log(peak)  # u = t**k puts the mid point at peak

    def f(t: float) -> float:
        u = t ** k
        return u * u * u * (10 - 15 * u + 6 * u * u)

    return f


def stroke_duration(dist: float, cfg: HumanConfig) -> float:
    """Milliseconds for a ``dist`` px stroke (Fitts' law, log-normal spread)."""
    median = cfg.mouse_time_base + cfg.mouse_time_per_bit * math.log2(1 + dist / 8)
    return max(FRAME_MS * 2, rand_lognormal(median, cfg.mouse_time_spread))


def plan_stroke(sx: float, sy: float, ex: float, ey: float, cfg: HumanConfig,
                duration: Optional[float] = None) -> List[Tuple[float, float, float]]:
    """Points of one stroke as ``(x, y, ms_since_previous)``; the last point is
    exactly ``(ex, ey)``. Consecutive points always differ (a real mouse does
    not report a move without movement)."""
    dist = math.hypot(ex - sx, ey - sy)
    if dist < 0.5:
        return []
    total = duration if duration is not None else stroke_duration(dist, cfg)
    n = int(max(cfg.mouse_min_steps, min(cfg.mouse_max_steps, round(total / FRAME_MS))))
    n = max(1, n)
    start, end = Point(sx, sy), Point(ex, ey)
    cp1, cp2 = _random_control_points(start, end, 0.12)
    curve = _progress_curve(rand(*_PEAK))
    # Low-frequency sideways drift (a hand is not a ruler), zero at both ends.
    ux, uy = (ex - sx) / dist, (ey - sy) / dist
    amp = min(cfg.mouse_wobble_max, dist * 0.02) * rand(-1, 1)
    waves = rand(0.5, 1.5)
    phase = rand(0, math.pi)
    out: List[Tuple[float, float, float]] = []
    lx, ly = sx, sy
    t_prev = 0.0
    for i in range(1, n + 1):
        # Frame timing jitters a little; the final event lands on the target.
        t = min(1.0, (i + (rand(-0.2, 0.2) if i < n else 0)) / n)
        if i == n:
            x, y = ex, ey
            if abs(x - lx) < 1 and abs(y - ly) < 1:
                if not out:
                    break  # already there (sub-pixel move): nothing to report
                # The last frame already got there: land exactly on it instead.
                _, _, pdt = out.pop()
                out.append((x, y, pdt + (t - t_prev) * total))
                break
        else:
            p = _bezier(start, cp1, cp2, end, curve(t))
            w = amp * math.sin(math.pi * t) * math.sin(phase + 2 * math.pi * waves * t)
            x, y = round(p.x - uy * w), round(p.y + ux * w)
            if abs(x - lx) < 1 and abs(y - ly) < 1:
                continue
        dt = (t - t_prev) * total
        t_prev = t
        out.append((x, y, dt))
        lx, ly = x, y
    return out


def plan_move(sx: float, sy: float, ex: float, ey: float,
              cfg: HumanConfig) -> List[Tuple[float, float, float]]:
    """A whole move: main stroke, and sometimes a miss near the target plus a
    short corrective stroke onto it."""
    dist = math.hypot(ex - sx, ey - sy)
    if dist < 0.5:
        return []
    if dist > 40 and random.random() < cfg.mouse_overshoot_chance:
        # Land a little past (or short of) the target, slightly off-line.
        ang = math.atan2(ey - sy, ex - sx) + rand(-0.25, 0.25)
        miss = dist * rand(0.01, 0.05) + rand_range(cfg.mouse_overshoot_px)
        if random.random() < 0.3:
            miss = -miss  # undershoot
        mx, my = round(ex + math.cos(ang) * miss), round(ey + math.sin(ang) * miss)
        pts = plan_stroke(sx, sy, mx, my, cfg)
        corr = math.hypot(ex - mx, ey - my)
        pause = rand(40, 140)
        tail = plan_stroke(mx, my, ex, ey, cfg,
                           duration=max(FRAME_MS * 2, rand_lognormal(90 + 25 * math.log2(1 + corr), 0.3)))
        if tail:
            x, y, dt = tail[0]
            tail[0] = (x, y, dt + pause)
        return pts + tail
    return plan_stroke(sx, sy, ex, ey, cfg)


def human_move(
    raw: RawMouse,
    start_x: float, start_y: float,
    end_x: float, end_y: float,
    cfg: HumanConfig,
) -> None:
    for x, y, dt in plan_move(start_x, start_y, end_x, end_y, cfg):
        sleep_ms(dt)
        raw.move(x, y)


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
