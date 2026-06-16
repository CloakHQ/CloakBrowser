"""Solve PX by locating hold button text and simulating press-and-hold."""
from __future__ import annotations
import logging, random, time
from typing import Any
from .base import BaseSolver, SolveResult, HoldTarget
from ..config import PX_HOLD_BUTTON_LABELS

logger = logging.getLogger("cloakbrowser.pxbypass.solve")

# JS: find hold button in main document / iframe modal
_PICK_HOLD_BUTTON_JS = """
() => {
  const btnLabels = ['pressione e segure', 'press and hold', 'press & hold', 'activate and hold'];
  const instructionRe = /antes de continuarmos|confirmar que voc\u00ea|n\u00e3o um bot|thank you/i;
  function scoreHoldButton(el) {
    const t = (el.innerText || '').trim();
    const r = el.getBoundingClientRect();
    if (r.width < 70 || r.height < 22 || r.height > 90) return -1;
    if (instructionRe.test(t)) return -1;
    if (['P','H1','H2','H3'].includes(el.tagName) && t.length > 40) return -1;
    const tLow = t.toLowerCase();
    let s = -1;
    if (btnLabels.some(l => tLow === l)) s = 200;
    else if (btnLabels.some(l => tLow.includes(l)) && t.length <= 40) s = 80;
    else return -1;
    if (el.getAttribute('role') === 'button' || el.tagName === 'BUTTON') s += 60;
    if (el.tagName === 'DIV' || el.tagName === 'A') s += 15;
    return s;
  }
  function scanDoc(doc) {
    let best = null, bestScore = -1;
    for (const el of doc.querySelectorAll('button, [role="button"], a, div, span')) {
      const s = scoreHoldButton(el);
      if (s > bestScore) { bestScore = s; best = el; }
    }
    if (!best) return null;
    const r = best.getBoundingClientRect();
    return { x: r.left + r.width/2, y: r.top + r.height/2, w: r.width, h: r.height,
             text: (best.innerText||'').slice(0,40), tag: best.tagName, source: 'px-hold-button' };
  }
  var modal = document.getElementById('px-captcha-modal');
  if (modal && modal.contentDocument) {
    var ir = modal.getBoundingClientRect();
    var hit = scanDoc(modal.contentDocument);
    if (hit) { hit.x += ir.left; hit.y += ir.top; return hit; }
  }
  return scanDoc(document);
}
"""


class SolveByHoldButton(BaseSolver):
    """Solve "Press & Hold" by locating button text and simulating hold.

    Works for same-origin and iframe-modal PX variants (iFood, etc.).
    """

    def __init__(self, labels: list[str] | None = None):
        self.labels = labels or list(PX_HOLD_BUTTON_LABELS)

    def find_target(self, page: Any) -> HoldTarget | None:
        # Strategy A: Playwright exact text locator
        try:
            for label in self.labels:
                loc = page.get_by_text(label, exact=True).first
                if loc.count() and loc.is_visible():
                    box = loc.bounding_box()
                    if box and box["width"] >= 70 and box["height"] >= 22:
                        return HoldTarget(
                            x=box["x"] + box["width"] / 2,
                            y=box["y"] + box["height"] / 2,
                            width=box["width"], height=box["height"],
                            source=f"playwright:{label[:12]}",
                        )
        except Exception:
            pass
        # Strategy B: JS scorer
        try:
            raw = page.evaluate(_PICK_HOLD_BUTTON_JS)
            if raw and raw.get("w") and raw["w"] >= 70:
                return HoldTarget(
                    x=float(raw["x"]), y=float(raw["y"]),
                    width=float(raw["w"]), height=float(raw["h"]),
                    source=f"js:{raw.get('source', 'px-btn')}",
                )
        except Exception:
            pass
        return None

    def simulate_hold(self, page: Any, target: HoldTarget, hold_min: float, hold_max: float, attempt: int) -> None:
        hold_sec = random.uniform(hold_min, hold_max)
        tx = target.x + random.uniform(-target.width * 0.06, target.width * 0.06)
        ty = target.y + random.uniform(-target.height * 0.05, target.height * 0.05)
        logger.info("Hold %d: (%.0f,%.0f) %.1fs via %s", attempt, tx, ty, hold_sec, target.source)
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
        logger.info("Hold %d: done (%.1fs)", attempt, hold_sec)

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

    def solve(self, page: Any, cfg: Any, detect_result: Any = None) -> SolveResult:
        import time as _time
        start = _time.monotonic()
        target = self.find_target(page)
        if target is None:
            return SolveResult(method="SolveByHoldButton", duration=_time.monotonic() - start, error="no_target")
        for attempt in range(1, cfg.max_attempts + 1):
            try:
                self.simulate_hold(page, target, cfg.hold_min, cfg.hold_max, attempt)
            except Exception as e:
                return SolveResult(method="SolveByHoldButton", attempts=attempt, duration=_time.monotonic() - start, error=str(e))
            # Check clear
            deadline = _time.monotonic() + cfg.post_wait
            while _time.monotonic() < deadline:
                if not self._is_px_visible(page):
                    return SolveResult(solved=True, method="SolveByHoldButton", attempts=attempt, duration=_time.monotonic() - start)
                _time.sleep(0.5)
            _time.sleep(random.uniform(1.5, 3.0))
        return SolveResult(method="SolveByHoldButton", attempts=cfg.max_attempts, duration=_time.monotonic() - start, error="max_attempts")

    def _is_px_visible(self, page: Any) -> bool:
        try:
            return bool(page.evaluate("""() => {
                if (document.getElementById('px-captcha')) return true;
                if (document.getElementById('px-captcha-modal')) return true;
                const body = (document.body ? document.body.innerText : '') || '';
                return body.toLowerCase().includes('activate and hold') || body.toLowerCase().includes('press and hold');
            }"""))
        except Exception:
            return True
