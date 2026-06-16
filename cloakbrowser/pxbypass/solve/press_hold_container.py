"""Solve PX by position of #px-captcha container (Walmart cloud variant)."""
from __future__ import annotations
import logging, random, time
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
                    || body.toLowerCase().includes('robot or human');
            }"""))
        except Exception:
            return True

    def solve(self, page: Any, cfg: Any, detect_result: Any = None) -> SolveResult:
        import time as _time
        start = _time.monotonic()
        target = self.find_target(page)
        if target is None:
            return SolveResult(method="SolveByHoldContainer", duration=_time.monotonic() - start, error="no_target")
        for attempt in range(1, cfg.max_attempts + 1):
            try:
                self.simulate_hold(page, target, cfg.hold_min, cfg.hold_max, attempt)
            except Exception as e:
                return SolveResult(method="SolveByHoldContainer", attempts=attempt, duration=_time.monotonic() - start, error=str(e))
            deadline = _time.monotonic() + cfg.post_wait
            while _time.monotonic() < deadline:
                if not self._is_px_visible(page):
                    return SolveResult(solved=True, method="SolveByHoldContainer", attempts=attempt, duration=_time.monotonic() - start)
                _time.sleep(0.5)
            _time.sleep(random.uniform(1.5, 3.0))
        return SolveResult(method="SolveByHoldContainer", attempts=cfg.max_attempts, duration=_time.monotonic() - start, error="max_attempts")
