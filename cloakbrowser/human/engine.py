"""Unified humanized action pipeline (async core, Playwright impl objects).

One implementation drives page / frame / locator / element-handle actions for
both the sync and the async Playwright API:

    resolve (isolated world, Playwright selector engine, strict mode)
      -> wait for element states (visible / enabled / editable / stable)
      -> scroll into view with mouse-wheel bursts (page, iframes, containers)
      -> Bezier move to a point inside the visible part of the element
      -> hit-target check (element itself, and every ancestor <iframe>)
      -> press / type

Nothing falls back to Playwright's stock actions, and failures raise
Playwright ``Error`` / ``TimeoutError``.
"""

from __future__ import annotations

import re
import sys

import asyncio
import math
import random
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from playwright._impl._errors import Error, TimeoutError

from . import fields
from .config import HumanConfig, merge_config, rand, rand_int_range, rand_range
from .keyboard import NEARBY_KEYS, SHIFT_SYMBOLS, _SHIFT_SYMBOL_CODES, _SHIFT_SYMBOL_KEYCODES
from .mouse import Point, _bezier, _ease_in_out, _random_control_points, click_target
from .world import HELPERS, StaleElement, Worlds, intersect

_ENTER_FRAME_SPLIT = re.compile(r"\s*>>\s*internal:control=enter-frame\s*>>\s*")

CLICK_STATES = ["visible", "enabled", "stable"]
HOVER_STATES = ["visible", "stable"]
INPUT_STATES = ["visible", "enabled", "editable"]
FOCUS_STATES = ["visible", "enabled"]

_RETRY_MS = [0, 20, 100, 100, 500]


class CursorState:
    __slots__ = ("x", "y", "initialized")

    def __init__(self) -> None:
        self.x: float = 0
        self.y: float = 0
        self.initialized: bool = False


async def sleep_ms(ms: float) -> None:
    if ms > 0:
        await asyncio.sleep(ms / 1000.0)


# ---------------------------------------------------------------------------
# Targets
# ---------------------------------------------------------------------------

class Target:
    """What an action is aimed at: a selector in a frame, or an ElementHandle."""

    __slots__ = ("frame", "selector", "strict", "handle", "description")

    def __init__(self, frame: Any, selector: Optional[str] = None, strict: bool = False,
                 handle: Any = None) -> None:
        self.frame = frame
        self.selector = selector
        self.strict = strict
        self.handle = handle
        self.description = f"locator({selector!r})" if selector is not None else "element handle"


class Resolved:
    __slots__ = ("frame", "id")

    def __init__(self, frame: Any, element_id: int) -> None:
        self.frame = frame
        self.id = element_id


class _Deadline:
    def __init__(self, timeout_ms: float) -> None:
        self.timeout = timeout_ms
        self._end = None if not timeout_ms else time.monotonic() + timeout_ms / 1000.0

    def remaining(self) -> float:
        if self._end is None:
            return math.inf
        return max(0.0, (self._end - time.monotonic()) * 1000.0)

    def left(self) -> float:
        """Remaining budget as a Playwright timeout value (0 = no limit)."""
        return 0 if self._end is None else max(1.0, self.remaining())

    def expired(self) -> bool:
        return self._end is not None and time.monotonic() >= self._end


class _Retry(Exception):
    """Internal: the current attempt failed for ``reason``; retry until timeout."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Human
# ---------------------------------------------------------------------------

class Human:
    """Humanized input for one Playwright impl page."""

    def __init__(self, page: Any, cfg: HumanConfig, cursor: CursorState) -> None:
        self.page = page
        self.cfg = cfg
        self.cursor = cursor
        self.worlds = Worlds(page)
        self._typeahead_until = 0.0  # monotonic time until which the browser joins typed letters
        self.mouse = page.mouse
        self.keyboard = page.keyboard
        self._platform: Optional[str] = None
        self._handle_ids: Dict[str, Tuple[Any, int, int]] = {}

    # -- configuration ------------------------------------------------------

    def call_cfg(self, overrides: Optional[dict]) -> HumanConfig:
        return merge_config(self.cfg, overrides)

    def timeout(self, frame: Any, timeout: Optional[float]) -> float:
        return float(frame._timeout(timeout))

    def deadline(self, target: Target, opts: dict) -> "_Deadline":
        """Deadline for an action; nested sub-actions share their caller's."""
        d = opts.get("_deadline")
        return d if d is not None else _Deadline(self.timeout(target.frame, opts.get("timeout")))

    async def platform(self) -> str:
        """Persona platform (``navigator.platform`` read in the isolated world)."""
        if self._platform is None:
            try:
                self._platform = str(await self.worlds.call(self.page.main_frame, "platform"))
            except Error:
                self._platform = ""
        return self._platform

    async def is_mac(self) -> bool:
        return (await self.platform()).lower().startswith("mac")

    async def select_all_key(self) -> str:
        return "Meta+a" if await self.is_mac() else "Control+a"

    async def _modifier(self, key: str) -> str:
        if key == "ControlOrMeta":
            return "Meta" if await self.is_mac() else "Control"
        return key

    # -- cursor -------------------------------------------------------------

    async def ensure_cursor(self, cfg: Optional[HumanConfig] = None) -> None:
        if not self.cursor.initialized:
            cfg = cfg or self.cfg
            self.cursor.x = rand(*cfg.initial_cursor_x)
            self.cursor.y = rand(*cfg.initial_cursor_y)
            await self.mouse.move(self.cursor.x, self.cursor.y)
            self.cursor.initialized = True

    async def move_to(self, x: float, y: float, cfg: HumanConfig) -> None:
        """Bezier move from the current cursor position to (x, y)."""
        await self.ensure_cursor(cfg)
        sx, sy = self.cursor.x, self.cursor.y
        dist = math.hypot(x - sx, y - sy)
        if dist >= 1:
            steps = max(cfg.mouse_min_steps, min(cfg.mouse_max_steps, round(dist / cfg.mouse_steps_divisor)))
            start, end = Point(sx, sy), Point(x, y)
            cp1, cp2 = _random_control_points(start, end)
            burst, burst_size = 0, rand_int_range(cfg.mouse_burst_size)
            for i in range(1, steps + 1):
                progress = i / steps
                pt = _bezier(start, cp1, cp2, end, _ease_in_out(progress))
                wobble = math.sin(math.pi * progress) * cfg.mouse_wobble_max
                if i == steps:
                    await self.mouse.move(x, y)  # exact end point (position= offsets)
                    continue
                else:
                    wx = pt.x + (random.random() - 0.5) * 2 * wobble
                    wy = pt.y + (random.random() - 0.5) * 2 * wobble
                await self.mouse.move(round(wx), round(wy))
                burst += 1
                if burst >= burst_size and i < steps:
                    await sleep_ms(rand_range(cfg.mouse_burst_pause))
                    burst = 0
            if random.random() < cfg.mouse_overshoot_chance:
                angle = math.atan2(y - sy, x - sx)
                over = rand_range(cfg.mouse_overshoot_px)
                await self.mouse.move(round(x + math.cos(angle) * over), round(y + math.sin(angle) * over))
                await sleep_ms(rand(30, 70))
                await self.mouse.move(x, y)
        self.cursor.x, self.cursor.y = x, y

    async def idle(self, cfg: HumanConfig) -> None:
        if not cfg.idle_between_actions:
            return
        await self.ensure_cursor(cfg)
        end = time.monotonic() + rand(*cfg.idle_between_duration)
        x, y = self.cursor.x, self.cursor.y
        while time.monotonic() < end:
            x += (random.random() - 0.5) * 2 * cfg.idle_drift_px
            y += (random.random() - 0.5) * 2 * cfg.idle_drift_px
            await self.mouse.move(round(x), round(y))
            await sleep_ms(min(rand_range(cfg.idle_pause_range), max(0.0, (end - time.monotonic()) * 1000)))
        # Drift is noise around the resting point, not a new position.
        await self.mouse.move(self.cursor.x, self.cursor.y)

    # -- resolution ---------------------------------------------------------

    async def resolve(self, target: Target, deadline: _Deadline) -> Resolved:
        """Resolve once. Raises ``_Retry`` (not yet there) or ``Error`` (final)."""
        if target.handle is not None:
            return await self._resolve_handle(target.handle, deadline)
        frame = target.frame
        parts = _ENTER_FRAME_SPLIT.split(target.selector)
        for i, part in enumerate(parts):
            res = await self.worlds.call(frame, "resolve", part, bool(target.strict), 0)
            status = res["status"]
            if status == "none":
                raise _Retry(f"waiting for {target.description}")
            if status == "strict":
                raise Error(res["message"])
            if status == "error":
                raise Error(res["message"])
            if i == len(parts) - 1:
                return Resolved(frame, res["id"])
            child = await self.worlds.content_frame(frame, res["id"])
            if child is None:
                raise _Retry(f"waiting for the frame of {target.description}")
            frame = child
        raise Error("unreachable")  # pragma: no cover

    async def _resolve_handle(self, handle: Any, deadline: _Deadline) -> Resolved:
        frame = handle._frame
        rec = await self.worlds._ready(frame)
        cached = self._handle_ids.get(handle._guid)
        if cached and cached[0] is frame and cached[1] == rec.ctx:
            return Resolved(frame, cached[2])
        # An ElementHandle carries no identity our context can read, so find
        # the element with exactly its border box.
        box = await handle.bounding_box()
        if box is None:
            if cached and cached[0] is frame:
                # Resolved in an earlier document of this frame and gone now
                # (a same-document navigation keeps the element, and its box).
                raise Error("Element is not attached to the DOM")
            raise _Retry("element is not visible")
        ox, oy, _ = await self.worlds.frame_geometry(frame)
        res = await self.worlds.call(frame, "matchRect", box["x"] - ox, box["y"] - oy,
                                     box["width"], box["height"])
        if res.get("count") != 1:
            raise Error(
                "cloakbrowser humanize: cannot identify the element behind this ElementHandle "
                "inside the isolated world (it shares its box with another element); "
                "use a Locator instead"
            )
        self._handle_ids[handle._guid] = (frame, rec.ctx, res["id"])
        return Resolved(frame, res["id"])

    async def wait_for(self, target: Target, states: Sequence[str], deadline: _Deadline,
                       api: str, force: bool = False) -> Resolved:
        """Resolve and wait for ``states``; Playwright-style retry + timeout."""
        return await self.retry(api, target, deadline, lambda: self._attempt_states(target, states, deadline, force))

    async def _attempt_states(self, target: Target, states: Sequence[str], deadline: _Deadline,
                              force: bool) -> Resolved:
        r = await self.resolve(target, deadline)
        if force:
            return r
        res = await self.worlds.call(r.frame, "states", r.id, list(states))
        if res is None:
            return r
        if "error" in res:
            raise Error(res["error"])
        missing = res["missing"]
        if missing == "attached":
            if target.handle is not None:
                raise Error("Element is not attached to the DOM")
            raise _Retry("element was detached from the DOM, retrying")
        raise _Retry(f"element is not {missing}")

    async def retry(self, api: str, target: Target, deadline: _Deadline,
                    attempt: Callable[[], Awaitable[Any]]) -> Any:
        reasons: List[str] = []
        n = 0
        while True:
            try:
                return await attempt()
            except StaleElement:
                if target.handle is not None:
                    raise Error(f"{api}: Element is not attached to the DOM") from None
                self._note(reasons, "element was detached from the DOM, retrying")
            except _Retry as r:
                self._note(reasons, r.reason)
            except Error as exc:
                msg = str(exc)
                if msg.startswith(api):
                    raise
                raise type(exc)(f"{api}: {msg}") from None
            if deadline.expired():
                log = "\n".join(f"  - {r}" for r in [f"waiting for {target.description}"] + reasons[-5:])
                raise TimeoutError(f"{api}: Timeout {deadline.timeout:.0f}ms exceeded.\nCall log:\n{log}")
            wait = _RETRY_MS[min(n, len(_RETRY_MS) - 1)]
            n += 1
            await sleep_ms(min(wait, deadline.remaining()))

    @staticmethod
    def _note(reasons: List[str], reason: str) -> None:
        if not reasons or reasons[-1] != reason:
            reasons.append(reason)

    # -- geometry -----------------------------------------------------------

    async def element_box(self, r: Resolved) -> Optional[Dict[str, float]]:
        """Element border box in viewport coordinates plus its visible clip."""
        g = await self.worlds.call(r.frame, "geometry", r.id)
        if g is None:
            raise StaleElement()
        ox, oy, clip = await self.worlds.frame_geometry(r.frame)
        box = {"x": g["x"] + ox, "y": g["y"] + oy, "width": g["width"], "height": g["height"],
               "bl": g["bl"], "bt": g["bt"]}
        scroller = await self.worlds.call(r.frame, "scroller", r.id)
        if scroller:
            sc = {"x": scroller["x"] + ox, "y": scroller["y"] + oy,
                  "width": scroller["width"], "height": scroller["height"]}
            clip = intersect(clip, sc)
            box["scroller"] = sc
        box["clip"] = clip
        box["visible"] = intersect(clip, box)
        return box

    # -- scrolling ----------------------------------------------------------

    async def scroll_into_view(self, r: Resolved, cfg: HumanConfig, deadline: _Deadline) -> Dict[str, Any]:
        """Wheel-scroll until the element sits inside its visible clip (and, for
        the main document, inside ``scroll_target_zone`` when the page can
        still scroll that way). Returns the final box."""
        box = await self.element_box(r)
        vp = await self.worlds.viewport()
        stalled = rounds = 0
        overshot = False
        while stalled < 2 and rounds < 40 and not deadline.expired():
            dx, dy = await self._needed_scroll(r, box, vp, cfg)
            if abs(dx) < 1 and abs(dy) < 1:
                break
            rounds += 1
            area = box["clip"] if box["clip"]["width"] > 4 and box["clip"]["height"] > 4 else \
                {"x": 0.0, "y": 0.0, "width": float(vp["width"]), "height": float(vp["height"])}
            if not self._inside(area, self.cursor):
                await self.move_to(area["x"] + area["width"] * rand(0.3, 0.7),
                                   area["y"] + area["height"] * rand(0.3, 0.7), cfg)
                await sleep_ms(rand_range(cfg.scroll_pre_move_delay))
            before = (box["x"], box["y"])
            if abs(dy) >= 1:
                await self._wheel_burst(0, dy, cfg, deadline)
                if not overshot:
                    overshot = True
                    await self._overshoot(dy, cfg, deadline)
            if abs(dx) >= 1:
                await self._wheel_burst(dx, 0, cfg, deadline)
            await sleep_ms(min(rand_range(cfg.scroll_settle_delay), deadline.remaining()))
            box = await self.element_box(r)
            moved = abs(box["x"] - before[0]) + abs(box["y"] - before[1])
            stalled = stalled + 1 if moved < 1 else 0
        return box

    @staticmethod
    def _inside(area: Dict[str, float], c: CursorState) -> bool:
        return area["x"] <= c.x <= area["x"] + area["width"] and area["y"] <= c.y <= area["y"] + area["height"]

    async def _needed_scroll(self, r: Resolved, box: Dict[str, Any], vp: Dict[str, float],
                             cfg: HumanConfig) -> Tuple[float, float]:
        clip = box["clip"]
        if clip["width"] <= 0 or clip["height"] <= 0:
            # The frame (or container) itself is out of view: bring it in first.
            return 0.0, (box["y"] + box["height"] / 2) - vp["height"] / 2
        dy = dx = 0.0
        # Vertical
        top, bottom = box["y"], box["y"] + box["height"]
        main_doc = r.frame.parent_frame is None and not box.get("scroller")
        if main_doc and box["height"] <= vp["height"] * (cfg.scroll_target_zone[1] - cfg.scroll_target_zone[0]):
            zt, zb = vp["height"] * cfg.scroll_target_zone[0], vp["height"] * cfg.scroll_target_zone[1]
            if top < zt or bottom > zb:
                dy = (top + box["height"] / 2) - vp["height"] * rand(*cfg.scroll_target_zone)
                if top >= clip["y"] - 1 and bottom <= clip["y"] + clip["height"] + 1:
                    # Fully visible but off-centre: only if the page can scroll that way.
                    doc = await self.worlds.call(self.page.main_frame, "doc")
                    if (dy < 0 and doc["y"] <= 0) or (dy > 0 and doc["y"] >= doc["maxY"]):
                        dy = 0.0
        elif box["height"] <= clip["height"]:
            if top < clip["y"] - 1 or bottom > clip["y"] + clip["height"] + 1:
                dy = (top + box["height"] / 2) - (clip["y"] + clip["height"] / 2)
        elif box["visible"]["height"] < clip["height"] * 0.5:
            dy = top - clip["y"] - clip["height"] * 0.1
        # Horizontal (#521): containment only.
        left, right = box["x"], box["x"] + box["width"]
        if box["width"] <= clip["width"]:
            if left < clip["x"] - 1 or right > clip["x"] + clip["width"] + 1:
                dx = (left + box["width"] / 2) - (clip["x"] + clip["width"] / 2)
        elif box["visible"]["width"] <= 0:
            dx = left - clip["x"]
        return dx, dy

    async def _overshoot(self, dy: float, cfg: HumanConfig, deadline: _Deadline) -> None:
        """Sometimes scroll a little past the target, pause, and wheel back
        (``scroll_overshoot_chance`` / ``scroll_overshoot_px``). The next
        round of :meth:`scroll_into_view` fixes whatever is left."""
        if random.random() >= cfg.scroll_overshoot_chance or deadline.expired():
            return
        sign = 1 if dy > 0 else -1
        await self._wheel_burst(0, round(rand_range(cfg.scroll_overshoot_px)) * sign, cfg, deadline)
        await sleep_ms(min(rand_range(cfg.scroll_settle_delay), deadline.remaining()))
        for _ in range(rand_int_range((1, 2))):
            if deadline.expired():
                break
            await self._wheel_burst(0, round(rand(40, 80)) * -sign, cfg, deadline)
            await sleep_ms(min(rand(100, 250), deadline.remaining()))

    async def _wheel_burst(self, dx: float, dy: float, cfg: HumanConfig,
                           deadline: Optional[_Deadline] = None) -> None:
        """One logical scroll: accelerate -> cruise -> decelerate in wheel ticks."""
        total = abs(dy) if dy else abs(dx)
        sign = 1 if (dy or dx) > 0 else -1
        accel, decel = rand_int_range(cfg.scroll_accel_steps), rand_int_range(cfg.scroll_decel_steps)
        avg = (cfg.scroll_delta_base[0] + cfg.scroll_delta_base[1]) / 2
        ticks = max(1, math.ceil(total / avg))
        sent = 0.0
        for i in range(ticks):
            if sent >= total or (deadline is not None and deadline.expired()):
                break
            if i < accel or i >= ticks - decel:
                pause = rand_range(cfg.scroll_pause_slow)
            else:
                pause = rand_range(cfg.scroll_pause_fast)
            tick = min(total - sent, rand_range(cfg.scroll_delta_base) *
                       (1 + (random.random() - 0.5) * 2 * cfg.scroll_delta_variance))
            # Split each tick into small wheel events like real inertia.
            left = tick
            while left > 0.5:
                chunk = min(left, rand(20, 40))
                step = round(chunk) * sign
                if step:
                    await self.mouse.wheel(step if dx else 0, step if dy else 0)
                left -= chunk
                await sleep_ms(rand(8, 20))
            sent += tick
            await sleep_ms(pause)

    # -- pointer ------------------------------------------------------------

    async def _point(self, box: Dict[str, Any], position: Optional[dict], is_input: bool,
                     cfg: HumanConfig) -> Tuple[float, float]:
        if position is not None:
            return box["x"] + box["bl"] + position["x"], box["y"] + box["bt"] + position["y"]
        vis = box["visible"]
        if vis["width"] <= 0 or vis["height"] <= 0:
            raise _Retry("element is outside of the viewport")
        # Aim inside the visible part, keep the input bias for text fields.
        full = click_target(box, is_input, cfg)
        x = min(max(full.x, vis["x"] + 1), vis["x"] + vis["width"] - 1)
        y = min(max(full.y, vis["y"] + 1), vis["y"] + vis["height"] - 1)
        return x, y

    @staticmethod
    def _aim_point(box: Dict[str, Any], aim: tuple) -> Tuple[float, float]:
        """Exact aim points: a date-editor segment, or a fraction along a slider."""
        if aim[0] == "segment":
            seg = aim[1]
            x, y = box["x"] + seg["dx"] + rand(-2, 2), box["y"] + seg["dy"] + rand(-2, 2)
        else:
            frac, vertical = aim[1], aim[2]
            # Native thumbs are inset by about half their width (~8px) at both ends.
            if vertical:
                inset = min(8.0, box["height"] / 4)
                y = box["y"] + box["height"] - inset - frac * (box["height"] - 2 * inset)
                x = box["x"] + box["width"] / 2
            else:
                inset = min(8.0, box["width"] / 4)
                x = box["x"] + inset + frac * (box["width"] - 2 * inset)
                y = box["y"] + box["height"] / 2 + rand(-1.5, 1.5)
        vis = box["visible"]
        if not (vis["x"] <= x <= vis["x"] + vis["width"] and vis["y"] <= y <= vis["y"] + vis["height"]):
            raise _Retry("element is outside of the viewport")
        return x, y

    async def _hit(self, r: Resolved, x: float, y: float) -> None:
        ox, oy, clip = await self.worlds.frame_geometry(r.frame)
        if not (clip["x"] <= x <= clip["x"] + clip["width"] and clip["y"] <= y <= clip["y"] + clip["height"]):
            raise _Retry("element is outside of the viewport")
        desc = await self.worlds.call(r.frame, "hit", r.id, x - ox, y - oy)
        if desc is None and r.frame.parent_frame is not None:
            desc = await self.worlds.owners_hit(r.frame, x, y)
        if desc:
            raise _Retry(f"{desc} intercepts pointer events")

    async def pointer_action(self, api: str, target: Target, opts: dict,
                             states: Sequence[str], is_input_hint: Optional[bool] = None,
                             action: Optional[Callable[[Resolved, float, float, HumanConfig], Awaitable[None]]] = None,
                             hold: Optional[Sequence[str]] = None,
                             ) -> Resolved:
        """Shared scroll -> move -> hit-check -> ``action`` sequence.

        ``hold``: modifier names (``Shift``, ``ControlOrMeta``...) held down while
        the cursor travels to the target, as Playwright's ``hover(modifiers=)``."""
        cfg = self.call_cfg(opts.get("human_config"))
        if opts.get("steps"):
            cfg = merge_config(cfg, {"mouse_min_steps": int(opts["steps"]), "mouse_max_steps": int(opts["steps"]),
                                     "mouse_overshoot_chance": 0.0})
        deadline = self.deadline(target, opts)
        force = bool(opts.get("force"))
        trial = bool(opts.get("trial"))
        position = opts.get("position")
        no_scroll = opts.get("scroll") == "none"
        await self.ensure_cursor(cfg)
        if not (opts.get("_nested") or opts.get("_deadline")):
            await self.idle(cfg)
        done: Dict[str, Any] = {}

        async def attempt() -> Resolved:
            r = await self._attempt_states(target, states, deadline, force)
            box = await self.element_box(r) if no_scroll else await self.scroll_into_view(r, cfg, deadline)
            if is_input_hint is None:
                info = await self.worlds.call(r.frame, "info", r.id)
                is_input = info["tag"] in ("input", "textarea") or info["editable"]
            else:
                is_input = is_input_hint
            aim = opts.get("_aim")
            if aim is not None:
                x, y = self._aim_point(box, aim)
            else:
                x, y = await self._point(box, position, is_input, cfg)
            if not force:
                await self._hit(r, x, y)
            if trial:
                return r
            keys = [await self._modifier(m) for m in (hold or [])]
            for k in keys:
                await self.keyboard.down(k)
            try:
                await self.move_to(x, y, cfg)
            finally:
                for k in reversed(keys):
                    await self.keyboard.up(k)
            # The page may replace or remove the target while the cursor
            # travels; never press on whatever is under it now (even with
            # force). Locators re-resolve and run the whole move again.
            if not await self.worlds.call(r.frame, "connected", r.id):
                raise StaleElement()
            if not force:
                await self._hit(r, self.cursor.x, self.cursor.y)
            done["is_input"] = is_input
            if action is not None:
                await action(r, self.cursor.x, self.cursor.y, cfg)
            return r

        return await self.retry(api, target, deadline, attempt)

    async def press_mouse(self, cfg: HumanConfig, is_input: bool, button: str = "left",
                          click_count: int = 1, delay: Optional[float] = None,
                          modifiers: Optional[Sequence[str]] = None) -> None:
        mods = [await self._modifier(m) for m in (modifiers or [])]
        await sleep_ms(rand_range(cfg.click_aim_delay_input if is_input else cfg.click_aim_delay_button))
        for m in mods:
            await self.keyboard.down(m)
        try:
            for n in range(1, max(1, int(click_count)) + 1):
                hold = delay if delay is not None else rand_range(cfg.click_hold_input if is_input else cfg.click_hold_button)
                await self.mouse.down(button=button, clickCount=n)
                await sleep_ms(hold)
                await self.mouse.up(button=button, clickCount=n)
                if n < click_count:
                    await sleep_ms(delay if delay is not None else rand(60, 140))
        finally:
            for m in reversed(mods):
                await self.keyboard.up(m)

    # -- public actions -----------------------------------------------------

    async def click(self, target: Target, opts: dict, api: str = "click", click_count: Optional[int] = None) -> None:
        count = click_count if click_count is not None else int(opts.get("click_count") or 1)

        async def act(r: Resolved, x: float, y: float, cfg: HumanConfig) -> None:
            info = await self.worlds.call(r.frame, "info", r.id)
            is_input = info["tag"] in ("input", "textarea") or info["editable"]
            await self.press_mouse(cfg, is_input, opts.get("button") or "left", count,
                                   opts.get("delay"), opts.get("modifiers"))

        await self.pointer_action(api, target, opts, CLICK_STATES, action=act)

    async def hover(self, target: Target, opts: dict, api: str = "hover") -> None:
        # Playwright holds the modifiers while the mouse moves onto the target.
        await self.pointer_action(api, target, opts, HOVER_STATES, is_input_hint=False,
                                  hold=opts.get("modifiers"))

    async def focus_element(self, target: Target, opts: dict, api: str, cfg: HumanConfig,
                            deadline: _Deadline, require_focus: bool = True) -> Tuple[Resolved, bool]:
        """Focus by a human click unless already focused.

        Returns ``(r, clicked_in)``: ``clicked_in`` is true when this call
        clicked and focus landed in the target (the caret then sits wherever the
        click put it). With ``require_focus=False`` (press / type) a click that
        does not move focus is fine, as in Playwright: the keys then go to
        whatever handles them (a <canvas>, document-level key handlers)."""
        r = await self.wait_for(target, FOCUS_STATES, deadline, api, bool(opts.get("force")))
        info = await self.worlds.call(r.frame, "info", r.id)
        if info["focused"]:
            return r, False
        # A person focuses a field by clicking it: scroll it into view with the
        # wheel and click. When it cannot be brought on screen at all (e.g.
        # positioned at negative offsets) the click times out with "element is
        # outside of the viewport" -- no silent programmatic focus.
        await self.click(target, {"_deadline": deadline, "force": opts.get("force"),
                                  "human_config": opts.get("human_config")}, api=api)
        info = await self.worlds.call(r.frame, "info", r.id)
        if info["focused"] or await self._focus_by_tab(r, info):
            return r, True
        if require_focus:
            raise Error(f"{api}: Error: element did not receive focus when clicked "
                        f"(it may not be focusable): {info['preview']}")
        return r, False

    async def _focus_by_tab(self, r: Resolved, info: dict) -> bool:
        """The click landed but focus went elsewhere (a focusable child or a
        label-less wrapper). Accept focus that moved into the target."""
        act = await self.worlds.call(r.frame, "activeValue")
        return bool(act.get("tag")) and await self.worlds.evaluate(
            r.frame, f"(() => {{ const e = {HELPERS}.el({r.id}); const a = document.activeElement;"
                     f" return !!a && (e === a || e.contains(a)); }})()")

    async def caret_to_end(self, r: Resolved) -> None:
        info = await self.worlds.call(r.frame, "info", r.id)
        if info["tag"] == "input":
            if not await self.worlds.call(r.frame, "caretAtEnd", r.id):
                await self.keyboard.press("End")
        else:
            await self.keyboard.press("Control+End")
        await sleep_ms(rand(20, 60))

    async def press(self, target: Target, key: str, opts: dict, api: str = "press") -> None:
        cfg = self.call_cfg(opts.get("human_config"))
        deadline = self.deadline(target, opts)
        await self.focus_element(target, opts, api, cfg, deadline, require_focus=False)
        await sleep_ms(rand(50, 150))
        await self.keyboard.press(await self._keys(key), delay=opts.get("delay"))

    async def _keys(self, key: str) -> str:
        if "ControlOrMeta" in key:
            return key.replace("ControlOrMeta", await self._modifier("ControlOrMeta"))
        return key

    async def type(self, target: Target, text: str, opts: dict, api: str = "type") -> None:
        cfg = self.call_cfg(opts.get("human_config"))
        deadline = self.deadline(target, opts)
        await sleep_ms(rand_range(cfg.field_switch_delay))
        r, clicked_in = await self.focus_element(target, opts, api, cfg, deadline, require_focus=False)
        if clicked_in:
            await self.caret_to_end(r)
        await sleep_ms(rand(100, 250))
        info = await self.worlds.call(r.frame, "info", r.id)
        await self.type_text(text, cfg, r.frame, info, opts.get("delay"))

    async def fill(self, target: Target, value: str, opts: dict, api: str = "fill") -> None:
        cfg = self.call_cfg(opts.get("human_config"))
        deadline = self.deadline(target, opts)
        force = bool(opts.get("force"))
        r = await self.wait_for(target, INPUT_STATES, deadline, api, force)
        info = await self.worlds.call(r.frame, "info", r.id)
        kind = fields.classify(info["tag"], info["type"], info["editable"])
        if kind == fields.NOT_FILLABLE:
            raise Error(f"{api}: Error: {fields.not_fillable_message(info['tag'], info['type'])}")
        if info["type"] == "number":
            try:
                value = fields.validate_number(value)
            except fields.FieldKindError as exc:
                raise Error(f"{api}: Error: {exc}") from None
        if kind == fields.SET:
            value = fields.normalize_set_value(info["type"], value)
            await sleep_ms(rand_range(cfg.field_switch_delay))
            if info["type"] == "range":
                await self.set_range(target, r, value, opts, api, cfg, deadline)
            elif info["type"] == "color":
                await self.set_color(target, r, value, opts, api, cfg, deadline)
            else:
                await self.set_datetime(target, r, info["type"], value, opts, api, cfg, deadline)
            return
        await sleep_ms(rand_range(cfg.field_switch_delay))
        r, _ = await self.focus_element(target, opts, api, cfg, deadline)
        await sleep_ms(rand(100, 250))
        info = await self.worlds.call(r.frame, "info", r.id)
        if info["value"]:
            await self.keyboard.press(await self.select_all_key())
            await sleep_ms(rand(30, 80))
            await self.keyboard.press("Backspace")
            await sleep_ms(rand(50, 150))
            info = await self.worlds.call(r.frame, "info", r.id)
            if info["value"]:
                # Some widgets ignore select-all; clear what is left by keys.
                await self.caret_to_end(r)
                for _ in range(len(info["value"])):
                    await self.keyboard.press("Backspace")
                    await sleep_ms(rand(15, 40))
        if value:
            await self.type_text(value, cfg, r.frame, info, None)

    async def set_checked(self, target: Target, checked: bool, opts: dict, api: str) -> None:
        deadline = self.deadline(target, opts)
        r = await self.wait_for(target, CLICK_STATES, deadline, api, bool(opts.get("force")))
        state = await self.worlds.call(r.frame, "checked", r.id)
        if "error" in state:
            raise Error(f"{api}: Error: {state['error']}")
        if state["checked"] == checked:
            return
        if state["radio"] and not checked:
            raise Error(f"{api}: Error: Cannot uncheck radio button. Radio buttons can only be unchecked "
                        "by selecting another radio button in the same group.")
        sub = {k: opts.get(k) for k in ("force", "position", "trial", "human_config")}
        sub["_deadline"] = deadline
        await self.click(target, sub, api=api)
        if opts.get("trial"):
            return
        state = await self.worlds.call(r.frame, "checked", r.id)
        if state.get("checked") != checked:
            raise Error(f"{api}: Error: Clicking the checkbox did not change its state")

    # -- value inputs: what a person does --------------------------------

    async def set_datetime(self, target: Target, r: Resolved, input_type: str, value: str, opts: dict,
                           api: str, cfg: HumanConfig, deadline: _Deadline) -> None:
        """date / time / datetime-local / month / week: click the first segment
        of the native editor and type each part with the keyboard, the way a
        person fills these fields. Segment order comes from the editor itself,
        so any locale works."""
        parts = fields.datetime_parts(input_type, value)
        if parts is None:
            raise Error(f"{api}: Error: Malformed value")
        segs = await self.worlds.editor_fields(r.frame, r.id)
        kinds = [f["kind"] for f in segs]
        parts = fields.use_24h(parts, "ampm" in kinds)
        if not segs or any(k not in parts and k != "ampm" for k in kinds):
            raise Error(f"{api}: Error: unsupported date/time editor layout {kinds}")
        await self.pointer_action(api, target, {**opts, "_deadline": deadline, "position": None,
                                                 "_aim": ("segment", segs[0])},
                                  INPUT_STATES, is_input_hint=True,
                                  action=lambda rr, x, y, c: self.press_mouse(c, True))
        await sleep_ms(rand(80, 200))
        current = fields.datetime_parts(input_type, await self.worlds.call(r.frame, "value", r.id) or "")
        for i, seg in enumerate(segs):
            kind = seg["kind"]
            if input_type == "month" and kind == "month" and current:
                # Shown as a month name; over an existing month Chromium's digit
                # matching is unreliable, so step with the arrow keys like a
                # person scrolling through the names.
                diff = int(parts["month"]) - int(current["month"])
                for _ in range(abs(diff)):
                    await self.keyboard.press("ArrowUp" if diff > 0 else "ArrowDown")
                    await sleep_ms(rand(60, 140))
            elif kind == "ampm":
                await self._type_char("P" if parts["hour24"] >= 12 else "A", cfg)
            else:
                digits = parts[kind]
                for j, ch in enumerate(digits):
                    await self._type_char(ch, cfg)
                    if j < len(digits) - 1:
                        # The editor forgets a partial entry after ~1 s without
                        # a key; people type a number in one go, so keep the
                        # gap inside a segment short (pauses go between parts).
                        await sleep_ms(min(450.0, max(40.0, cfg.typing_delay +
                                                      (random.random() - 0.5) * 2 * cfg.typing_delay_spread)))
            if i < len(segs) - 1 and not fields.segment_auto_advances(kind, parts, input_type):
                await self.keyboard.press("ArrowRight")
            await sleep_ms(rand(60, 160))
        got = await self.worlds.call(r.frame, "value", r.id)
        if got != value:
            raise Error(f"{api}: Error: the date/time editor produced {got!r} instead of {value!r}")

    async def set_range(self, target: Target, r: Resolved, value: str, opts: dict, api: str,
                        cfg: HumanConfig, deadline: _Deadline) -> None:
        """Slider: click on the track near the wanted value, then nudge with
        arrow keys until it is exact."""
        info = await self.worlds.call(r.frame, "rangeInfo", r.id)
        try:
            want = float(value)
        except ValueError:
            raise Error(f"{api}: Error: Malformed value") from None
        span = info["max"] - info["min"]
        frac = 0.5 if span <= 0 else min(1.0, max(0.0, (want - info["min"]) / span))
        if info["rtl"] and not info["vertical"]:
            frac = 1 - frac
        await self.pointer_action(api, target, {**opts, "_deadline": deadline, "position": None,
                                                 "_aim": ("fraction", frac, info["vertical"])},
                                  INPUT_STATES, is_input_hint=False,
                                  action=lambda rr, x, y, c: self.press_mouse(c, False))
        for _ in range(400):
            cur = float(await self.worlds.call(r.frame, "value", r.id))
            if abs(cur - want) < 1e-9 or (info["step"] and abs(cur - want) < info["step"] / 2):
                break
            up = cur < want
            key = ("ArrowRight" if up else "ArrowLeft") if not info["rtl"] else ("ArrowLeft" if up else "ArrowRight")
            await self.keyboard.press(key)
            await sleep_ms(rand(40, 110))
            if float(await self.worlds.call(r.frame, "value", r.id)) == cur:
                break  # cannot move further (min/max reached)
        got = await self.worlds.call(r.frame, "value", r.id)
        if float(got) != float(await self._range_snap(r, want)):
            raise Error(f"{api}: Error: slider stopped at {got} instead of {value}")

    async def _range_snap(self, r: Resolved, want: float) -> float:
        info = await self.worlds.call(r.frame, "rangeInfo", r.id)
        v = min(info["max"], max(info["min"], want))
        if info["step"]:
            v = info["min"] + round((v - info["min"]) / info["step"]) * info["step"]
            v = min(info["max"], v)
        return v

    async def set_color(self, target: Target, r: Resolved, value: str, opts: dict, api: str,
                        cfg: HumanConfig, deadline: _Deadline) -> None:
        """<input type=color> opens an OS colour dialog that page input cannot
        drive. Playwright sets the value; doing that silently would hide a
        robot-only path, so refuse instead."""
        raise Error(f"{api}: Error: <input type=color> opens a native colour picker that cannot be "
                    "operated with human input; set it with page._original.fill(...) if a programmatic "
                    "value is acceptable")

    async def select_option(self, target: Target, options: List[dict], element_handles: List[Any],
                            opts: dict, api: str = "select_option") -> List[str]:
        """Pick options like a person: a dropdown is opened with a click and
        moved with arrow keys + Enter; a list box gets clicks on the options
        (Ctrl/Cmd-click to add more in a multi-select)."""
        cfg = self.call_cfg(opts.get("human_config"))
        deadline = self.deadline(target, opts)
        force = bool(opts.get("force"))

        async def plan() -> Tuple[Resolved, dict]:
            r = await self._attempt_states(target, ["visible", "enabled"], deadline, force)
            ids = [(await self._resolve_handle(h, deadline)).id for h in element_handles]
            res = await self.worlds.call(r.frame, "selectPlan", r.id, options, ids)
            if "error" in res:
                raise Error(res["error"])
            if "retry" in res:
                raise _Retry(res["retry"])
            return r, res

        r, p = await self.retry(api, target, deadline, plan)
        if not p["listbox"]:
            await self._select_dropdown(target, r, p["targets"][0] if p["targets"] else None, p, opts, api,
                                        cfg, deadline)
        else:
            await self._select_listbox(target, r, p, opts, api, cfg, deadline)
        state = await self.worlds.call(r.frame, "selectState", r.id)
        if sorted(state["selected"]) != sorted(p["targets"]):
            raise Error(f"{api}: Error: selection ended as {state['values']} instead of {p['values']}")
        return state["values"]

    async def _select_dropdown(self, target: Target, r: Resolved, index: Optional[int], p: dict, opts: dict,
                               api: str, cfg: HumanConfig, deadline: _Deadline) -> None:
        if index is None:
            raise Error(f"{api}: Error: a dropdown always keeps one option selected")
        state = await self.worlds.call(r.frame, "selectState", r.id)
        if state["current"] == index:
            await self.hover(target, {"_deadline": deadline, "human_config": opts.get("human_config")}, api=api)
            return
        await self.click(target, {"_deadline": deadline, "force": opts.get("force"),
                                  "human_config": opts.get("human_config")}, api=api)
        await sleep_ms(rand(200, 450))  # popup opens; eyes find the option
        mac = sys.platform == "darwin"  # a macOS host's native popup ignores arrow keys
        plan = await self.worlds.call(r.frame, "typeAheadPlan", r.id, index, 0 if mac else 3)
        if plan is None:
            raise Error(f"{api}: Error: no option of this dropdown can be reached")
        if plan.get("home"):
            # No name prefix is unique (duplicate labels): Home, then walk; on
            # macOS type the whole label instead.
            keys = list(plan["label"]) if mac else ["Home"] + [
                "ArrowDown" if plan["arrows"] > 0 else "ArrowUp"] * abs(plan["arrows"])
        else:
            keys = list(plan["typed"]) + ["ArrowDown" if plan["arrows"] > 0 else "ArrowUp"] * abs(plan["arrows"])
        # The browser joins letters typed within ~1s into one search: let an
        # earlier select_option's search lapse before starting a new one.
        if keys and len(keys[0]) == 1:
            wait = self._typeahead_until - time.monotonic()
            if wait > 0:
                await sleep_ms(wait * 1000)
        typed = False
        for k in keys:
            if deadline.expired():
                await self.keyboard.press("Escape")
                raise TimeoutError(f"{api}: Timeout {deadline.timeout:.0f}ms exceeded.\n"
                                   f"Call log:\n  - choosing an option of {target.description}")
            if len(k) == 1:
                await self._typeahead_char(k, cfg)
                typed = True
                self._typeahead_until = time.monotonic() + 1.1
                await sleep_ms(rand(60, 160))
            else:
                await self.keyboard.press(k)
                await sleep_ms(rand(90, 200))
        await sleep_ms(rand(100, 250))
        await self.keyboard.press("Enter")
        if typed:
            self._typeahead_until = time.monotonic() + 1.1
        await sleep_ms(rand(80, 160))

    async def _typeahead_char(self, ch: str, cfg: HumanConfig) -> None:
        """One type-ahead letter. Letters go lowercase (a person doesn't hold Shift
        to search a list); a character without a US-layout key is sent as itself."""
        if ch.isascii():
            await self._type_char(ch, cfg)
            return
        session = await self.worlds.session()
        await session.send("Input.dispatchKeyEvent", {"type": "keyDown", "key": ch, "text": ch, "unmodifiedText": ch})
        await sleep_ms(rand_range(cfg.key_hold))
        await session.send("Input.dispatchKeyEvent", {"type": "keyUp", "key": ch})

    async def _select_listbox(self, target: Target, r: Resolved, p: dict, opts: dict, api: str,
                              cfg: HumanConfig, deadline: _Deadline) -> None:
        state = await self.worlds.call(r.frame, "selectState", r.id)
        want = list(p["targets"])
        if sorted(state["selected"]) == sorted(want):
            await self.hover(target, {"_deadline": deadline, "human_config": opts.get("human_config")}, api=api)
            return
        add_key = "Meta" if await self.is_mac() else "Control"
        first = True
        if not want:
            raise Error(f"{api}: Error: deselecting every option is not something a click can do")
        for idx in want:
            oid = await self.worlds.call(r.frame, "optionId", r.id, idx)
            opt = Target(r.frame, None)
            opt.description = f"option #{idx}"
            res = Resolved(r.frame, oid)
            # Plain click on the first option replaces the selection; further
            # options are added with Ctrl/Cmd held, as a person does.
            mods = [] if first else [add_key]
            await self._click_resolved(res, opt, cfg, deadline, api, mods)
            first = False
            await sleep_ms(rand(120, 300))

    async def _click_resolved(self, r: Resolved, label: Target, cfg: HumanConfig, deadline: _Deadline,
                              api: str, modifiers: Sequence[str]) -> None:
        """Scroll / move / hit-check / click an already resolved element."""
        async def attempt() -> None:
            box = await self.scroll_into_view(r, cfg, deadline)
            x, y = await self._point(box, None, False, cfg)
            await self._hit(r, x, y)
            await self.move_to(x, y, cfg)
            await self._hit(r, self.cursor.x, self.cursor.y)
            await self.press_mouse(cfg, False, "left", 1, None, modifiers)

        await self.retry(api, label, deadline, attempt)

    async def drag(self, source: Target, dest: Target, opts: dict, api: str = "drag_and_drop") -> None:
        sub = {"_deadline": self.deadline(source, opts), "force": opts.get("force"), "human_config": opts.get("human_config"),
               "position": opts.get("source_position"), "trial": opts.get("trial")}
        await self.idle(self.call_cfg(opts.get("human_config")))
        await self.hover(source, sub, api=api)
        if opts.get("trial"):
            await self.hover(dest, {**sub, "position": opts.get("target_position"), "_nested": True}, api=api)
            return
        await sleep_ms(rand(100, 200))
        await self.mouse.down()
        try:
            await sleep_ms(rand(80, 150))
            await self.hover(dest, {**sub, "position": opts.get("target_position"), "force": True, "_nested": True},
                             api=api)
            await sleep_ms(rand(80, 150))
        finally:
            await self.mouse.up()

    async def focus(self, target: Target, opts: dict, api: str = "focus", move: bool = False) -> None:
        deadline = self.deadline(target, opts)
        if move:
            await self.hover(target, {"timeout": opts.get("timeout"), "human_config": opts.get("human_config")}, api=api)
        r = await self.retry(api, target, deadline, lambda: self.resolve(target, deadline))
        await self.worlds.call(r.frame, "focus", r.id)

    async def scroll_into_view_if_needed(self, target: Target, opts: dict) -> None:
        cfg = self.call_cfg(opts.get("human_config"))
        deadline = self.deadline(target, opts)
        await self.ensure_cursor(cfg)

        async def attempt() -> None:
            r = await self._attempt_states(target, ["visible", "stable"], deadline, False)
            await self.scroll_into_view(r, cfg, deadline)

        await self.retry("scroll_into_view_if_needed", target, deadline, attempt)

    # -- keyboard -----------------------------------------------------------

    async def type_text(self, text: str, cfg: HumanConfig, frame: Any, info: Optional[dict],
                        delay: Optional[float]) -> None:
        """Type ``text`` key by key into the focused element of ``frame``."""
        tag = info.get("tag") if info else None
        mistypes = cfg.mistype_chance > 0 and tag is not None and fields.allows_mistype(tag, info.get("type"))
        for i, ch in enumerate(text):
            if not ch.isascii():
                await sleep_ms(rand_range(cfg.key_hold))
                await self.keyboard.insert_text(ch)
            else:
                if mistypes and ch.isalnum() and random.random() < cfg.mistype_chance:
                    await self._typo(ch, cfg, frame)
                await self._type_char(ch, cfg)
            if i < len(text) - 1:
                await self._between_keys(cfg, delay)

    async def _typo(self, ch: str, cfg: HumanConfig, frame: Any) -> None:
        lower = ch.lower()
        if lower not in NEARBY_KEYS:
            return
        wrong = random.choice(NEARBY_KEYS[lower])
        if ch.isupper():
            wrong = wrong.upper()
        before = await self._active_value(frame)
        await self._type_char(wrong, cfg)
        await sleep_ms(rand_range(cfg.mistype_delay_notice))
        after = await self._active_value(frame)
        if before is not None and after == before:
            # The page rejected the wrong key (mask / filter): nothing to undo.
            await sleep_ms(rand_range(cfg.mistype_delay_correct))
            return
        await self.keyboard.down("Backspace")
        await sleep_ms(rand_range(cfg.key_hold))
        await self.keyboard.up("Backspace")
        await sleep_ms(rand_range(cfg.mistype_delay_correct))

    async def _active_value(self, frame: Any) -> Optional[str]:
        try:
            return (await self.worlds.call(frame, "activeValue")).get("value")
        except Error:
            return None

    async def _type_char(self, ch: str, cfg: HumanConfig) -> None:
        if ch.isalpha() and ch.isupper():
            await self.keyboard.down("Shift")
            await sleep_ms(rand_range(cfg.shift_down_delay))
            await self.keyboard.down(ch)
            await sleep_ms(rand_range(cfg.key_hold))
            await self.keyboard.up(ch)
            await sleep_ms(rand_range(cfg.shift_up_delay))
            await self.keyboard.up("Shift")
        elif ch in SHIFT_SYMBOLS:
            session = await self.worlds.session()
            code = _SHIFT_SYMBOL_CODES.get(ch, "")
            vk = _SHIFT_SYMBOL_KEYCODES.get(ch, 0)
            await self.keyboard.down("Shift")
            await sleep_ms(rand_range(cfg.shift_down_delay))
            await session.send("Input.dispatchKeyEvent", {
                "type": "keyDown", "modifiers": 8, "key": ch, "code": code,
                "windowsVirtualKeyCode": vk, "text": ch, "unmodifiedText": ch,
            })
            await sleep_ms(rand_range(cfg.key_hold))
            await session.send("Input.dispatchKeyEvent", {
                "type": "keyUp", "modifiers": 8, "key": ch, "code": code, "windowsVirtualKeyCode": vk,
            })
            await sleep_ms(rand_range(cfg.shift_up_delay))
            await self.keyboard.up("Shift")
        else:
            await self.keyboard.down(ch)
            await sleep_ms(rand_range(cfg.key_hold))
            await self.keyboard.up(ch)

    async def _between_keys(self, cfg: HumanConfig, delay: Optional[float]) -> None:
        if delay is not None:
            await sleep_ms(delay)
        elif random.random() < cfg.typing_pause_chance:
            await sleep_ms(rand_range(cfg.typing_pause_range))
        else:
            await sleep_ms(max(10, cfg.typing_delay + (random.random() - 0.5) * 2 * cfg.typing_delay_spread))

    async def keyboard_type(self, text: str, delay: Optional[float] = None) -> None:
        """``page.keyboard.type``: no target; mistypes only where safe."""
        frame = self.page.main_frame
        try:
            info = await self.worlds.call(frame, "activeValue")
        except Error:
            info = None
        if info and info.get("tag") == "iframe":
            info = None  # focus is inside a child frame: value checks impossible
        await self.type_text(text, self.cfg, frame, info if info and info.get("tag") else None, delay)

    # -- raw mouse API ------------------------------------------------------

    async def mouse_move(self, x: float, y: float, steps: Optional[int] = None) -> None:
        if steps is not None:
            await self.ensure_cursor()
            await self.mouse.move(x, y, steps=steps)
            self.cursor.x, self.cursor.y = x, y
            return
        await self.move_to(x, y, self.cfg)
        self.cursor.x, self.cursor.y = x, y

    async def mouse_click(self, x: float, y: float, delay: Optional[float] = None,
                          button: Optional[str] = None, click_count: Optional[int] = None) -> None:
        await self.move_to(x, y, self.cfg)
        self.cursor.x, self.cursor.y = x, y
        await self.press_mouse(self.cfg, False, button or "left", click_count or 1, delay)
