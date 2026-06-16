"""Solve PX by locating hold button text and simulating press-and-hold.

Uses refined button detection that distinguishes actual hold buttons
from instruction paragraphs — prevents false positive on text like
"Pressione e segure para confirmar que você não é um bot".
"""
from __future__ import annotations
import logging, random, re
from typing import Any
from .base import BaseSolver, SolveResult, HoldTarget
from ..config import PX_HOLD_BUTTON_LABELS

logger = logging.getLogger("cloakbrowser.pxbypass.solve")

# Regex matching ONLY the short button label (not instruction paragraph)
_HOLD_BTN_RE = re.compile(
    r"^\s*(pressione e segure|press and hold|press & hold)\s*$",
    re.IGNORECASE,
)

# JS scorer: score elements, penalizing instruction paragraphs
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
  function scanDoc(doc, offsetLeft, offsetTop) {
    let best = null, bestScore = -1;
    for (const el of doc.querySelectorAll('button, [role="button"], a, div, span')) {
      const s = scoreHoldButton(el);
      if (s > bestScore) { bestScore = s; best = el; }
    }
    if (!best) return null;
    const r = best.getBoundingClientRect();
    return {
      x: offsetLeft + r.left + r.width/2,
      y: offsetTop + r.top + r.height/2,
      w: r.width, h: r.height,
      text: (best.innerText||'').slice(0,40), tag: best.tagName,
      source: 'px-hold-button'
    };
  }
  // Check iframe modal first (iFood style)
  var modal = document.getElementById('px-captcha-modal');
  if (modal && modal.contentDocument) {
    var ir = modal.getBoundingClientRect();
    var hit = scanDoc(modal.contentDocument, ir.left, ir.top);
    if (hit) return hit;
  }
  return scanDoc(document, 0, 0);
}
"""

# JS: check if element is a real hold button (not instruction text)
_IS_REAL_HOLD_BTN_JS = """(el) => {
  const t = (el.innerText || '').trim();
  const r = el.getBoundingClientRect();
  const tag = el.tagName;
  const role = el.getAttribute('role');
  const exactHold = /^(pressione e segure|press and hold|press & hold)$/i.test(t);
  const isInstruction = /antes de continuarmos|confirmar que voc\u00ea|n\u00e3o um bot|thank you/i.test(t);
  const isParagraph = ['P','H1','H2','H3'].includes(tag) && t.length > 40;
  const sizeOk = r.width >= 70 && r.height >= 22 && r.height <= 90;
  return {
    ok: sizeOk && !isInstruction && !isParagraph && (
      exactHold ||
      role === 'button' || tag === 'BUTTON' ||
      (t.length <= 40 && /segure|hold/i.test(t))
    ),
    text: t.slice(0, 60),
    w: r.width, h: r.height, tag: tag,
  };
}"""


class SolveByHoldButton(BaseSolver):
    """Solve "Press & Hold" by locating button text and simulating hold.

    Works for same-origin and iframe-modal PX variants (iFood, etc.).
    Uses refined detection to avoid confusing instruction text with buttons.
    """

    def __init__(self, labels: list[str] | None = None):
        self.labels = labels or list(PX_HOLD_BUTTON_LABELS)

    def _is_real_button(self, page: Any, locator: Any) -> bool:
        """Check if a Playwright locator points to a real hold button."""
        try:
            meta = locator.evaluate(_IS_REAL_HOLD_BTN_JS)
            return bool(meta and meta.get("ok"))
        except Exception:
            return False

    def find_target(self, page: Any) -> HoldTarget | None:
        # Strategy A: Playwright locator via exact text match (most reliable)
        try:
            for label in self.labels:
                loc = page.get_by_text(label, exact=True).first
                if loc.count() and loc.is_visible() and self._is_real_button(page, loc):
                    box = loc.bounding_box()
                    if box and box["width"] >= 70 and box["height"] >= 22:
                        logger.debug("Button found via exact text: %s", label)
                        return HoldTarget(
                            x=box["x"] + box["width"] / 2,
                            y=box["y"] + box["height"] / 2,
                            width=box["width"], height=box["height"],
                            source=f"playwright:{label[:12]}",
                        )
        except Exception:
            pass

        # Strategy B: role=button with regex name
        try:
            loc = page.get_by_role(
                "button",
                name=re.compile(r"pressione e segure|press and hold|press & hold", re.I),
            ).first
            if loc.count() and loc.is_visible() and self._is_real_button(page, loc):
                box = loc.bounding_box()
                if box and box["width"] >= 70:
                    return HoldTarget(
                        x=box["x"] + box["width"] / 2,
                        y=box["y"] + box["height"] / 2,
                        width=box["width"], height=box["height"],
                        source="role:button",
                    )
        except Exception:
            pass

        # Strategy C: filter locator with exact regex
        try:
            loc = page.locator("button, [role='button'], div, a").filter(
                has_text=_HOLD_BTN_RE,
            ).first
            if loc.count() and loc.is_visible() and self._is_real_button(page, loc):
                box = loc.bounding_box()
                if box and box["width"] >= 70:
                    return HoldTarget(
                        x=box["x"] + box["width"] / 2,
                        y=box["y"] + box["height"] / 2,
                        width=box["width"], height=box["height"],
                        source="filter:hold-btn",
                    )
        except Exception:
            pass

        # Strategy D: iframe modal (iFood #px-captcha-modal)
        try:
            modal_frame = page.frame_locator("#px-captcha-modal")
            for label in self.labels:
                loc = modal_frame.get_by_text(label, exact=True).first
                if loc.count() and loc.is_visible() and self._is_real_button(page, loc):
                    box = loc.bounding_box()
                    if box and box["width"] >= 70:
                        return HoldTarget(
                            x=box["x"] + box["width"] / 2,
                            y=box["y"] + box["height"] / 2,
                            width=box["width"], height=box["height"],
                            source=f"modal:{label[:12]}",
                        )
        except Exception:
            pass

        # Strategy E: JS scorer (covers all remaining cases)
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

    def simulate_hold(self, page: Any, target: HoldTarget,
                      hold_min: float, hold_max: float, attempt: int,
                      locator: Any = None) -> None:
        """Simulate press-and-hold with human-like mouse movements."""
        hold_sec = random.uniform(hold_min, hold_max)
        tx = target.x + random.uniform(-target.width * 0.06, target.width * 0.06)
        ty = target.y + random.uniform(-target.height * 0.05, target.height * 0.05)

        # Scroll into view if locator is available
        if locator is not None:
            try:
                locator.scroll_into_view_if_needed(timeout=5000)
            except Exception:
                pass

        logger.info("Hold %d: (%.0f,%.0f) %.1fs via %s",
                     attempt, tx, ty, hold_sec, target.source)

        # Human-like movement to target
        self._human_move_to(page, tx, ty)

        # Hover on locator for precise iframe targeting
        if locator is not None:
            try:
                locator.hover(timeout=3000, force=True)
                box = locator.bounding_box()
                if box:
                    tx = box["x"] + box["width"] / 2 + random.uniform(-2, 2)
                    ty = box["y"] + box["height"] / 2 + random.uniform(-2, 2)
                    page.mouse.move(tx, ty)
            except Exception:
                pass

        import time as _time
        _time.sleep(random.uniform(0.06, 0.14))
        page.mouse.down(button="left")

        # Hold with micro-movements
        elapsed = 0.0
        while elapsed < hold_sec:
            chunk = random.uniform(0.12, 0.32)
            _time.sleep(chunk)
            elapsed += chunk
            try:
                page.mouse.move(tx + random.uniform(-3.5, 3.5),
                                 ty + random.uniform(-2.5, 2.5))
            except Exception:
                pass

        _time.sleep(random.uniform(0.05, 0.15))
        page.mouse.up(button="left")
        logger.info("Hold %d: done (%.1fs)", attempt, hold_sec)

    def _human_move_to(self, page: Any, tx: float, ty: float) -> None:
        """Move mouse to target with Bezier-like trajectory."""
        vp = page.viewport_size or {"width": 1280, "height": 720}
        sx = random.uniform(vp["width"] * 0.2, vp["width"] * 0.8)
        sy = random.uniform(vp["height"] * 0.2, vp["height"] * 0.8)
        steps = random.randint(10, 18)
        page.mouse.move(sx, sy)
        import time as _time
        _time.sleep(random.uniform(0.08, 0.2))
        for i in range(1, steps + 1):
            t = i / steps
            ease = t * t * (3 - 2 * t)
            cx = sx + (tx - sx) * ease + random.uniform(-2.5, 2.5)
            cy = sy + (ty - sy) * ease + random.uniform(-2.5, 2.5)
            page.mouse.move(cx, cy)
            _time.sleep(random.uniform(0.015, 0.04))
        page.mouse.move(tx, ty)
        _time.sleep(random.uniform(0.05, 0.12))

    def solve(self, page: Any, cfg: Any, detect_result: Any = None) -> SolveResult:
        import time as _time
        start = _time.monotonic()
        target = self.find_target(page)
        if target is None:
            return SolveResult(method="SolveByHoldButton",
                               duration=_time.monotonic() - start,
                               error="no_target")

        for attempt in range(1, cfg.max_attempts + 1):
            try:
                self.simulate_hold(page, target, cfg.hold_min, cfg.hold_max, attempt)
            except Exception as e:
                return SolveResult(method="SolveByHoldButton", attempts=attempt,
                                   duration=_time.monotonic() - start, error=str(e))
            # Check if PX cleared
            deadline = _time.monotonic() + cfg.post_wait
            while _time.monotonic() < deadline:
                if not self._is_px_visible(page):
                    return SolveResult(solved=True, method="SolveByHoldButton",
                                       attempts=attempt,
                                       duration=_time.monotonic() - start)
                _time.sleep(0.5)
            _time.sleep(random.uniform(1.5, 3.0))

        return SolveResult(method="SolveByHoldButton", attempts=cfg.max_attempts,
                           duration=_time.monotonic() - start, error="max_attempts")

    def _is_px_visible(self, page: Any) -> bool:
        try:
            return bool(page.evaluate("""() => {
                if (document.getElementById('px-captcha')) return true;
                if (document.getElementById('px-captcha-modal')) return true;
                const body = (document.body ? document.body.innerText : '') || '';
                return body.toLowerCase().includes('activate and hold')
                    || body.toLowerCase().includes('press and hold');
            }"""))
        except Exception:
            return True