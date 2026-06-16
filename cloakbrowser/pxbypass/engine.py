"""PxEngine: orchestrates detection → solving for PerimeterX challenges.

Auto-detects the PX variant using site-specific handlers and generic
detectors, then selects the best solving strategy.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from .config import PxConfig
from .detect.base import BaseDetector, DetectResult
from .detect.composite import CompositeDetector
from .detect.keyword import DetectPxByKeyword
from .detect.dom_element import DetectPxByDomElement
from .detect.script_src import DetectPxByScriptSrc
from .solve.base import BaseSolver, SolveResult
from .solve.composite import CompositeSolver
from .solve.press_hold_button import SolveByHoldButton
from .solve.press_hold_container import SolveByHoldContainer
from .site.base import SiteHandler

logger = logging.getLogger("cloakbrowser.pxbypass.engine")

# Keywords that indicate PX/security challenge is active on the page.
_PX_CHALLENGE_KEYWORDS = [
    'activate and hold', 'press and hold', 'pressione e segure',
    'robot or human', 'verificação de segurança', 'segurança',
    'press & hold', 'perimeterx', 'px-captcha',
    'antes de continuarmos', 'confirmar que você',
    'não é um robô', 'não um robô',
]

# JS expression that checks whether PX challenge UI is visible on the page.
_PX_UI_WATCHER_JS = """() => {
  // Check known container/overlay elements
  var px = document.getElementById('px-captcha');
  if (px) { var r = px.getBoundingClientRect(); if (r.width > 10 && r.height > 10) return true; }
  px = document.getElementById('px-captcha-modal');
  if (px) { var r = px.getBoundingClientRect(); if (r.width > 10 && r.height > 10) return true; }
  var el = document.querySelector('[data-px-captcha]');
  if (el) { var r = el.getBoundingClientRect(); if (r.width > 10 && r.height > 10) return true; }
  el = document.querySelector('.px-challenge');
  if (el) { var r = el.getBoundingClientRect(); if (r.width > 10 && r.height > 10) return true; }
  // Check body text for challenge markers
  var body = (document.body ? document.body.innerText : '') || '';
  var t = body.toLowerCase();
  return t.includes('activate and hold') || t.includes('press and hold')
      || t.includes('pressione e segure') || t.includes('robot or human')
      || t.includes('verifica') || (t.includes('segurança') && body.length < 500)
      || t.includes('px-captcha') || t.includes('perimeterx')
      || t.includes('antes de continuarmos');
}"""

# MutationObserver script injected into the page.
_PX_MUTATION_OBSERVER_JS = """() => {
  if (window.__pxObserverInstalled) return;
  window.__pxObserverInstalled = true;

  function pxCheckAndNotify() {
    if (window.__pxSolving) return;
    var found = false;
    var px = document.getElementById('px-captcha');
    if (px) { var r = px.getBoundingClientRect(); if (r.width > 10 && r.height > 10) found = true; }
    if (!found) {
      px = document.getElementById('px-captcha-modal');
      if (px) { var r = px.getBoundingClientRect(); if (r.width > 10 && r.height > 10) found = true; }
    }
    if (!found) {
      var el = document.querySelector('[data-px-captcha], .px-challenge');
      if (el) { var r = el.getBoundingClientRect(); if (r.width > 10 && r.height > 10) found = true; }
    }
    if (!found && document.body) {
      var body = (document.body ? document.body.innerText : '') || '';
      var t = body.toLowerCase();
      found = t.includes('activate and hold') || t.includes('press and hold')
           || t.includes('pressione e segure') || t.includes('robot or human')
           || (t.includes('verifica') && body.length < 800)
           || t.includes('px-captcha') || t.includes('antes de continuarmos');
    }
    if (found && window.__pxNotify) {
      window.__pxSolving = true;
      window.__pxNotify();
    }
  }

  // Observe DOM AND text changes
  var observer = new MutationObserver(function(mutations) {
    pxCheckAndNotify();
  });
  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  } else {
    document.addEventListener('DOMContentLoaded', function() {
      observer.observe(document.body, { childList: true, subtree: true, characterData: true });
      pxCheckAndNotify();
    });
  }
  // Also poll every 2 seconds as fallback
  setInterval(pxCheckAndNotify, 2000);
}"""


class PxEngine:
    """Orchestrates detection and solving of PerimeterX challenges.

    Detection uses MutationObserver injected into the page's JS context,
    so it works across all navigations without cross-thread issues.
    """

    def __init__(self, cfg: PxConfig | None = None):
        self.cfg = cfg or PxConfig()
        self._site_handlers: list[SiteHandler] = []
        self._detect_only = False

    def register_handler(self, handler: SiteHandler) -> None:
        """Register a site-specific handler."""
        self._site_handlers.append(handler)
        self._site_handlers.sort(key=lambda h: h.priority, reverse=True)

    @property
    def generic_detector(self) -> BaseDetector:
        """Fallback detector used when no site handler matches."""
        return CompositeDetector([
            DetectPxByKeyword(),
            DetectPxByDomElement(),
            DetectPxByScriptSrc(),
        ])

    @property
    def generic_solver(self) -> BaseSolver:
        """Fallback solver used when no site handler matches."""
        return CompositeSolver([
            SolveByHoldButton(),
            SolveByHoldContainer(),
        ])

    def _px_ui_visible(self, page: Any) -> bool:
        """Check if PX challenge UI is actually visible on the page.
        
        Returns False if page is empty, loading, or has no PX challenge.
        This is the gating check to prevent false positives from script detection.
        """
        try:
            body = page.evaluate("""() => {
                var body = (document.body ? document.body.innerText : '') || '';
                if (body.length < 20) return 'empty';
                // Check for real PX elements
                var px = document.getElementById('px-captcha');
                if (px) { var r = px.getBoundingClientRect(); if (r.width > 10 && r.height > 10) return 'element'; }
                px = document.getElementById('px-captcha-modal');
                if (px) { var r = px.getBoundingClientRect(); if (r.width > 10 && r.height > 10) return 'element'; }
                var el = document.querySelector('[data-px-captcha], .px-challenge');
                if (el) { var r = el.getBoundingClientRect(); if (r.width > 10 && r.height > 10) return 'element'; }
                var t = body.toLowerCase();
                if (t.includes('activate and hold') || t.includes('press and hold')
                    || t.includes('pressione e segure') || t.includes('robot or human')) {
                    return 'text';
                }
                return 'none';
            }""")
            return body in ('element', 'text')
        except Exception:
            return False

    def detect(self, page: Any) -> tuple[SiteHandler | None, DetectResult]:
        """Detect PX challenge and identify the best handler.

        First checks the page URL to find matching site handlers,
        then verifies PX UI is actually visible.

        Args:
            page: Playwright Page object.

        Returns:
            (handler, result) — handler may be None if no specific site matches.
        """
        # Try site-specific handlers that match the current URL
        for handler in self._site_handlers:
            if not handler.match_url(page):
                logger.debug("Site handler '%s' skipped (URL mismatch)", handler.name)
                continue
            result = handler.detect(page)
            if result.detected and result.confidence >= 0.3:
                logger.debug("Site handler '%s' matched (confidence=%.2f)",
                             handler.name, result.confidence)
                return handler, result

        # Fallback: generic detection (only if PX UI is visible)
        if self._px_ui_visible(page):
            generic_result = self.generic_detector.detect(page)
            if generic_result.detected:
                logger.debug("Generic detector matched (confidence=%.2f)",
                             generic_result.confidence)
                return None, generic_result

        return None, DetectResult()

    def solve(self, page: Any, handler: SiteHandler | None,
              detect_result: DetectResult) -> SolveResult:
        """Solve the detected PX challenge."""
        if not self.cfg.enabled:
            return SolveResult(method="PxEngine", error="disabled")

        if handler is not None:
            logger.info("Using site handler '%s' for solving", handler.name)
            return handler.solve(page, self.cfg, detect_result)

        logger.info("Using generic solver")
        return self.generic_solver.solve(page, self.cfg, detect_result)

    def install_observer(self, page: Any) -> None:
        """Inject MutationObserver into the page and expose Python callback."""
        if getattr(page, '_px_observer_installed', False):
            return
        page._px_observer_installed = True

        page.expose_binding("__pxNotify", lambda: self._on_px_detected(page))
        page.on("load", lambda: self._reinject_observer(page))
        self._reinject_observer(page)

    def _reinject_observer(self, page: Any) -> None:
        try:
            page.evaluate(_PX_MUTATION_OBSERVER_JS)
        except Exception:
            pass

    def _on_px_detected(self, page: Any) -> None:
        try:
            self.check_and_solve(page)
        except Exception as exc:
            logger.debug("PX solve failed (non-fatal): %s", exc)
        finally:
            try:
                page.evaluate("window.__pxSolving = false")
            except Exception:
                pass

    def check_and_solve(self, page: Any) -> bool:
        """Check if PX is present and solve it (one-shot)."""
        if not self.cfg.enabled:
            return True

        try:
            px_visible = bool(page.evaluate(_PX_UI_WATCHER_JS))
        except Exception:
            return True
        if not px_visible:
            return True

        handler, result = self.detect(page)
        if not result.detected:
            return True

        logger.info("PX detected (confidence=%.2f), solving...", result.confidence)
        solve_result = self.solve(page, handler, result)

        if solve_result.solved:
            logger.info("PX solved via %s in %.1fs",
                        solve_result.method, solve_result.duration)
        else:
            logger.warning("PX solve failed via %s: %s",
                           solve_result.method, solve_result.error)
        return solve_result.solved

    async def install_observer_async(self, page: Any) -> None:
        """Async version of install_observer."""
        if getattr(page, '_px_observer_installed', False):
            return
        page._px_observer_installed = True

        await page.expose_binding("__pxNotify", lambda: self._on_px_detected_async(page))
        page.on("load", lambda: asyncio.create_task(self._reinject_observer_async(page)))
        await self._reinject_observer_async(page)

    async def _reinject_observer_async(self, page: Any) -> None:
        try:
            await page.evaluate(_PX_MUTATION_OBSERVER_JS)
        except Exception:
            pass

    def _on_px_detected_async(self, page: Any) -> None:
        try:
            asyncio.create_task(self._solve_async(page))
        except Exception as exc:
            logger.debug("PX solve failed (async, non-fatal): %s", exc)

    async def _solve_async(self, page: Any) -> None:
        await self.check_and_solve_async(page)
        try:
            await page.evaluate("window.__pxSolving = false")
        except Exception:
            pass

    async def check_and_solve_async(self, page: Any) -> bool:
        """Async version of check_and_solve."""
        if not self.cfg.enabled:
            return True

        try:
            px_visible = bool(await page.evaluate(_PX_UI_WATCHER_JS))
        except Exception:
            return True
        if not px_visible:
            return True

        handler, result = self.detect(page)
        if not result.detected:
            return True

        logger.info("PX detected (async, confidence=%.2f), solving...", result.confidence)
        solve_result = self.solve(page, handler, result)

        if solve_result.solved:
            logger.info("PX solved via %s (async) in %.1fs",
                        solve_result.method, solve_result.duration)
        else:
            logger.warning("PX solve failed via %s (async): %s",
                           solve_result.method, solve_result.error)
        return solve_result.solved