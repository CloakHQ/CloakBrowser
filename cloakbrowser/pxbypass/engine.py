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

# JS expression that checks whether PX UI is present on the page.
_PX_UI_WATCHER_JS = """() => {
  if (document.getElementById('px-captcha')) return true;
  if (document.getElementById('px-captcha-modal')) return true;
  var el = document.querySelector('[data-px-captcha]');
  if (el) { var r = el.getBoundingClientRect(); if (r.width > 10) return true; }
  el = document.querySelector('.px-challenge');
  if (el) { var r = el.getBoundingClientRect(); if (r.width > 10) return true; }
  var body = (document.body ? document.body.innerText : '') || '';
  var t = body.toLowerCase();
  return t.includes('activate and hold') || t.includes('press and hold')
      || t.includes('pressione e segure') || t.includes('robot or human');
}"""

# MutationObserver script injected into the page.
# Watches for PX challenge elements to appear in the DOM.
# When detected, calls window.__pxNotify() which triggers Python solver.
_PX_MUTATION_OBSERVER_JS = """() => {
  if (window.__pxObserverInstalled) return;
  window.__pxObserverInstalled = true;

  function pxCheckAndNotify() {
    if (window.__pxSolving) return;  // solver is already running
    var found = false;
    if (document.getElementById('px-captcha')) found = true;
    else if (document.getElementById('px-captcha-modal')) found = true;
    else {
      var el = document.querySelector('[data-px-captcha]');
      if (el) { var r = el.getBoundingClientRect(); if (r.width > 10) found = true; }
      if (!found) {
        el = document.querySelector('.px-challenge');
        if (el) { var r = el.getBoundingClientRect(); if (r.width > 10) found = true; }
      }
      if (!found) {
        var body = (document.body ? document.body.innerText : '') || '';
        var t = body.toLowerCase();
        found = t.includes('activate and hold') || t.includes('press and hold')
             || t.includes('pressione e segure') || t.includes('robot or human');
      }
    }
    if (found && window.__pxNotify) {
      window.__pxSolving = true;
      window.__pxNotify();
    }
  }

  // Observe DOM changes
  var observer = new MutationObserver(function(mutations) {
    for (var i = 0; i < mutations.length; i++) {
      for (var j = 0; j < (mutations[i].addedNodes || []).length; j++) {
        var n = mutations[i].addedNodes[j];
        if (n.nodeType === 1 && (n.id === 'px-captcha' || n.id === 'px-captcha-modal'
            || n.matches && n.matches('[data-px-captcha], .px-challenge'))) {
          pxCheckAndNotify();
          return;
        }
      }
    }
  });
  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true });
  } else {
    document.addEventListener('DOMContentLoaded', function() {
      observer.observe(document.body, { childList: true, subtree: true });
      pxCheckAndNotify();
    });
  }

  // Also check periodically as a fallback (every 3 seconds)
  setInterval(pxCheckAndNotify, 3000);
}"""


class PxEngine:
    """Orchestrates detection and solving of PerimeterX challenges.

    Flow:
        1. Try site-specific handlers (Walmart, iFood, etc.) in priority order
        2. If no site matches, fall back to generic CompositeDetector/Solver
        3. detect() returns handler + result → solve() uses handler's solver

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

    def detect(self, page: Any) -> tuple[SiteHandler | None, DetectResult]:
        """Detect PX challenge and identify the best handler.

        Args:
            page: Playwright Page object.

        Returns:
            (handler, result) — handler may be None if no specific site matches.
        """
        # Try site-specific handlers first
        for handler in self._site_handlers:
            result = handler.detect(page)
            if result.detected and result.confidence >= 0.3:
                logger.debug("Site handler '%s' matched (confidence=%.2f)",
                             handler.name, result.confidence)
                return handler, result

        # Fallback: generic detection
        generic_result = self.generic_detector.detect(page)
        if generic_result.detected:
            logger.debug("Generic detector matched (confidence=%.2f)",
                         generic_result.confidence)
            return None, generic_result

        return None, DetectResult()

    def solve(self, page: Any, handler: SiteHandler | None,
              detect_result: DetectResult) -> SolveResult:
        """Solve the detected PX challenge.

        Args:
            page: Playwright Page object.
            handler: SiteHandler from detect(), or None for generic.
            detect_result: DetectResult from detect().

        Returns:
            SolveResult indicating success/failure.
        """
        if not self.cfg.enabled:
            return SolveResult(method="PxEngine", error="disabled")

        if handler is not None:
            logger.info("Using site handler '%s' for solving", handler.name)
            return handler.solve(page, self.cfg, detect_result)

        logger.info("Using generic solver")
        return self.generic_solver.solve(page, self.cfg, detect_result)

    def install_observer(self, page: Any) -> None:
        """Inject MutationObserver into the page and expose Python callback.

        Safe to call multiple times — only installs once per page.

        Args:
            page: Playwright Page object.
        """
        if getattr(page, '_px_observer_installed', False):
            return
        page._px_observer_installed = True

        # Expose a Python callback that JS can call via window.__pxNotify()
        page.expose_binding("__pxNotify", lambda: self._on_px_detected(page))

        # When navigation happens, the observer may need to be re-injected
        # because the execution context is destroyed.
        page.on("load", lambda: self._reinject_observer(page))

        # Inject the observer JS
        self._reinject_observer(page)

    def _reinject_observer(self, page: Any) -> None:
        """Re-inject the MutationObserver after navigation."""
        try:
            page.evaluate(_PX_MUTATION_OBSERVER_JS)
        except Exception:
            pass

    def _on_px_detected(self, page: Any) -> None:
        """Called from JS when PX is detected via MutationObserver."""
        try:
            self.check_and_solve(page)
        except Exception as exc:
            logger.debug("PX solve failed (non-fatal): %s", exc)
        finally:
            # Reset the solving flag so observer can fire again next time
            try:
                page.evaluate("window.__pxSolving = false")
            except Exception:
                pass

    def check_and_solve(self, page: Any) -> bool:
        """Check if PX is present and solve it.

        One-shot: checks the current page state and solves if PX is there.
        Does NOT wait.

        Args:
            page: Playwright Page object.

        Returns:
            True if PX was not present or was solved.
        """
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
        """Called from JS when PX is detected (async variant)."""
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