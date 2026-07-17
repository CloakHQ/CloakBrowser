"""Solve PX by position of #px-captcha container (Walmart cloud variant)."""
from __future__ import annotations
import asyncio
import logging
import random
import time
from typing import Any
from .base import BaseSolver, SolveResult, HoldTarget

logger = logging.getLogger("cloakbrowser.pxbypass.solve")

_GET_PX_CONTAINER_POSITION_JS = """
(function() {
  var pxCaptcha = document.getElementById('px-captcha');
  if (!pxCaptcha) {
    // try the modal
    pxCaptcha = document.getElementById('px-captcha-modal');
    if (!pxCaptcha) return null;
  }
  try {
    var r = pxCaptcha.getBoundingClientRect();
    if (!r || typeof r.width === 'undefined' || r.width < 10 || r.height < 10) return null;
    return {
      x: r.left + r.width / 2,
      y: r.top + r.height / 2,
      w: r.width,
      h: r.height,
      source: 'px-container'
    };
  } catch(e) { return null; }
})()
"""


class SolveByHoldContainer(BaseSolver):
    """Solve PX by holding at the #px-captcha container center.

    For cross-origin cloud variants where the hold button is inside
    a cross-origin iframe (Walmart). We position relative to the
    container div which is always visible.
    Supports both sync and async solving.
    """

    def __init__(self, container_selector: str = "#px-captcha"):
        self.container_selector = container_selector

    def find_target(self, page: Any) -> HoldTarget | None:
        try:
            raw = page.evaluate(_GET_PX_CONTAINER_POSITION_JS)
            if raw and raw.get("w") and raw["w"] >= 70:
                logger.debug("Container target: %.0fx%.0f at (%.0f,%.0f) via %s",
                             raw["w"], raw["h"], raw["x"], raw["y"], raw.get("source", ""))
                return HoldTarget(
                    x=float(raw["x"]), y=float(raw["y"]),
                    width=float(raw["w"]), height=float(raw["h"]),
                    source=f"container:{raw.get('source', 'px')}",
                )
        except Exception as exc:
            logger.debug("Container lookup failed: %s", exc)
        return None

    async def find_target_async(self, page: Any) -> HoldTarget | None:
        """Async version of find_target."""
        try:
            raw = await page.evaluate(_GET_PX_CONTAINER_POSITION_JS)
            if raw and raw.get("w") and raw["w"] >= 70:
                logger.debug("Container target (async): %.0fx%.0f at (%.0f,%.0f) via %s",
                             raw["w"], raw["h"], raw["x"], raw["y"], raw.get("source", ""))
                return HoldTarget(
                    x=float(raw["x"]), y=float(raw["y"]),
                    width=float(raw["w"]), height=float(raw["h"]),
                    source=f"container:{raw.get('source', 'px')}",
                )
        except Exception as exc:
            logger.debug("Container lookup failed (async): %s", exc)
        return None

    def _human_move_to(self, page: Any, tx: float, ty: float) -> None:
        vp = page.viewport_size or {"width": 1280, "height": 720}
        sx = random.uniform(vp["width"] * 0.2, vp["width"] * 0.8)
        sy = random.uniform(vp["height"] * 0.2, vp["height"] * 0.8)
        steps = random.randint(10, 18)
        page.mouse.move(sx, sy)
        time.sleep(random.uniform(0.08, 0.2))
        for i in range(1, steps + 1):
            t = i / steps
            ease = t * t * (3 - 2 * t)
            cx = sx + (tx - sx) * ease + random.uniform(-2.5, 2.5)
            cy = sy + (ty - sy) * ease + random.uniform(-2.5, 2.5)
            page.mouse.move(cx, cy)
            time.sleep(random.uniform(0.015, 0.04))
        page.mouse.move(tx, ty)
        time.sleep(random.uniform(0.05, 0.12))

    async def _human_move_to_async(self, page: Any, tx: float, ty: float) -> None:
        """Async version of _human_move_to."""
        vp = page.viewport_size or {"width": 1280, "height": 720}
        sx = random.uniform(vp["width"] * 0.2, vp["width"] * 0.8)
        sy = random.uniform(vp["height"] * 0.2, vp["height"] * 0.8)
        steps = random.randint(10, 18)
        await page.mouse.move(sx, sy)
        await asyncio.sleep(random.uniform(0.08, 0.2))
        for i in range(1, steps + 1):
            t = i / steps
            ease = t * t * (3 - 2 * t)
            cx = sx + (tx - sx) * ease + random.uniform(-2.5, 2.5)
            cy = sy + (ty - sy) * ease + random.uniform(-2.5, 2.5)
            await page.mouse.move(cx, cy)
            await asyncio.sleep(random.uniform(0.015, 0.04))
        await page.mouse.move(tx, ty)
        await asyncio.sleep(random.uniform(0.05, 0.12))

    def simulate_hold(self, page: Any, target: HoldTarget, hold_min: float, hold_max: float, attempt: int) -> None:
        hold_sec = random.uniform(hold_min, hold_max)
        tx = target.x + random.uniform(-target.width * 0.06, target.width * 0.06)
        ty = target.y + random.uniform(-target.height * 0.05, target.height * 0.05)
        logger.info("Container hold %d: (%.0f,%.0f) %.1fs via %s", attempt, tx, ty, hold_sec, target.source)
        self._human_move_to(page, tx, ty)
        time.sleep(random.uniform(0.06, 0.14))
        page.mouse.down(button="left")
        elapsed = 0.0
        while elapsed < hold_sec:
            chunk = random.uniform(0.12, 0.32)
            time.sleep(chunk)
            elapsed += chunk
            try:
                page.mouse.move(tx + random.uniform(-3.5, 3.5), ty + random.uniform(-2.5, 2.5))
            except Exception:
                pass
        time.sleep(random.uniform(0.05, 0.15))
        page.mouse.up(button="left")
        logger.info("Container hold %d: done (%.1fs)", attempt, hold_sec)

    async def simulate_hold_async(self, page: Any, target: HoldTarget, hold_min: float, hold_max: float, attempt: int) -> None:
        """Async version of simulate_hold."""
        hold_sec = random.uniform(hold_min, hold_max)
        tx = target.x + random.uniform(-target.width * 0.06, target.width * 0.06)
        ty = target.y + random.uniform(-target.height * 0.05, target.height * 0.05)
        logger.info("Container hold %d: (%.0f,%.0f) %.1fs via %s", attempt, tx, ty, hold_sec, target.source)
        await self._human_move_to_async(page, tx, ty)
        await asyncio.sleep(random.uniform(0.06, 0.14))
        await page.mouse.down(button="left")
        elapsed = 0.0
        while elapsed < hold_sec:
            chunk = random.uniform(0.12, 0.32)
            await asyncio.sleep(chunk)
            elapsed += chunk
            try:
                await page.mouse.move(tx + random.uniform(-3.5, 3.5), ty + random.uniform(-2.5, 2.5))
            except Exception:
                pass
        await asyncio.sleep(random.uniform(0.05, 0.15))
        await page.mouse.up(button="left")
        logger.info("Container hold %d: done (%.1fs)", attempt, hold_sec)

    def _is_px_visible(self, page: Any) -> bool:
        try:
            return bool(page.evaluate("""() => {
                if (document.getElementById('px-captcha-modal')) return true;
                var px = document.getElementById('px-captcha');
                if (px) {
                    var r = px.getBoundingClientRect();
                    if (r.width > 10) return true;
                }
                var body = (document.body ? document.body.innerText : '') || '';
                return body.toLowerCase().includes('activate and hold')
                    || body.toLowerCase().includes('press and hold')
                    || body.toLowerCase().includes('robot or human')
                    || body.toLowerCase().includes('pressione e segure');
            }"""))
        except Exception:
            return True

    async def _is_px_visible_async(self, page: Any) -> bool:
        """Async version of _is_px_visible."""
        try:
            return bool(await page.evaluate("""() => {
                if (document.getElementById('px-captcha-modal')) return true;
                var px = document.getElementById('px-captcha');
                if (px) {
                    var r = px.getBoundingClientRect();
                    if (r.width > 10) return true;
                }
                var body = (document.body ? document.body.innerText : '') || '';
                return body.toLowerCase().includes('activate and hold')
                    || body.toLowerCase().includes('press and hold')
                    || body.toLowerCase().includes('robot or human')
                    || body.toLowerCase().includes('pressione e segure');
            }"""))
        except Exception:
            return True

    def _wait_until_ready(self, page: Any, cfg: Any) -> bool:
        checker = getattr(cfg, "checker", None)
        if checker is None:
            return True
        deadline = time.monotonic() + getattr(cfg, "app_ready_timeout", 60.0)
        while True:
            try:
                if checker(page):
                    return True
            except Exception:
                pass
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.8)

    async def _wait_until_ready_async(self, page: Any, cfg: Any) -> bool:
        checker = getattr(cfg, "checker", None)
        if checker is None:
            return True
        loop = asyncio.get_running_loop()
        deadline = loop.time() + getattr(cfg, "app_ready_timeout", 60.0)
        while True:
            try:
                ready = checker(page)
                if hasattr(ready, "__await__"):
                    ready = await ready
                if ready:
                    return True
            except Exception:
                pass
            if loop.time() >= deadline:
                return False
            await asyncio.sleep(0.8)

    def _success_result(self, page: Any, cfg: Any, attempt: int, start: float) -> SolveResult:
        if not self._wait_until_ready(page, cfg):
            return SolveResult(method="SolveByHoldContainer", attempts=attempt,
                               duration=time.monotonic() - start, error="app_not_ready")
        return SolveResult(solved=True, method="SolveByHoldContainer", attempts=attempt,
                           duration=time.monotonic() - start)

    async def _success_result_async(self, page: Any, cfg: Any, attempt: int, start: float) -> SolveResult:
        if not await self._wait_until_ready_async(page, cfg):
            return SolveResult(method="SolveByHoldContainer", attempts=attempt,
                               duration=time.monotonic() - start, error="app_not_ready")
        return SolveResult(solved=True, method="SolveByHoldContainer", attempts=attempt,
                           duration=time.monotonic() - start)

    def solve(self, page: Any, cfg: Any, detect_result: Any = None) -> SolveResult:
        import time as _time
        start = _time.monotonic()

        # Wait for a target to appear
        target = None
        button_wait = getattr(cfg, 'button_wait_timeout', 20.0)
        deadline = _time.monotonic() + button_wait
        while _time.monotonic() < deadline:
            target = self.find_target(page)
            if target is not None:
                break
            _time.sleep(0.5)

        if target is None:
            return SolveResult(method="SolveByHoldContainer", duration=_time.monotonic() - start, error="no_target")

        for attempt in range(1, cfg.max_attempts + 1):
            if not self._is_px_visible(page):
                return self._success_result(page, cfg, attempt, start)

            # Re-find target before each attempt
            current = self.find_target(page) or target
            try:
                self.simulate_hold(page, current, cfg.hold_min, cfg.hold_max, attempt)
            except Exception as e:
                return SolveResult(method="SolveByHoldContainer", attempts=attempt, duration=_time.monotonic() - start, error=str(e))

            post_deadline = _time.monotonic() + cfg.post_wait
            while _time.monotonic() < post_deadline:
                if not self._is_px_visible(page):
                    return self._success_result(page, cfg, attempt, start)
                _time.sleep(0.5)
            _time.sleep(random.uniform(1.5, 3.0))

        return SolveResult(method="SolveByHoldContainer", attempts=cfg.max_attempts, duration=_time.monotonic() - start, error="max_attempts")

    async def async_solve(self, page: Any, cfg: Any, detect_result: Any = None) -> SolveResult:
        """Async version of solve()."""
        import time as _time
        start = _time.monotonic()

        target = None
        button_wait = getattr(cfg, 'button_wait_timeout', 20.0)
        deadline = _time.monotonic() + button_wait
        while _time.monotonic() < deadline:
            target = await self.find_target_async(page)
            if target is not None:
                break
            await asyncio.sleep(0.5)

        if target is None:
            return SolveResult(method="SolveByHoldContainer", duration=_time.monotonic() - start, error="no_target")

        for attempt in range(1, cfg.max_attempts + 1):
            if not await self._is_px_visible_async(page):
                return await self._success_result_async(page, cfg, attempt, start)

            current = await self.find_target_async(page) or target
            try:
                await self.simulate_hold_async(page, current, cfg.hold_min, cfg.hold_max, attempt)
            except Exception as e:
                return SolveResult(method="SolveByHoldContainer", attempts=attempt, duration=_time.monotonic() - start, error=str(e))

            post_deadline = _time.monotonic() + cfg.post_wait
            while _time.monotonic() < post_deadline:
                if not await self._is_px_visible_async(page):
                    return await self._success_result_async(page, cfg, attempt, start)
                await asyncio.sleep(0.5)
            await asyncio.sleep(random.uniform(1.5, 3.0))

        return SolveResult(method="SolveByHoldContainer", attempts=cfg.max_attempts, duration=_time.monotonic() - start, error="max_attempts")