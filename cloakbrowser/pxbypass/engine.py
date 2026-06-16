"""PxEngine: orchestrates detection → solving for PerimeterX challenges.

Auto-detects the PX variant using site-specific handlers and generic
detectors, then selects the best solving strategy.
"""
from __future__ import annotations

import logging
import threading
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


class PxEngine:
    """Orchestrates detection and solving of PerimeterX challenges.

    Flow:
        1. Try site-specific handlers (Walmart, iFood, etc.) in priority order
        2. If no site matches, fall back to generic CompositeDetector/Solver
        3. detect() returns handler + result → solve() uses handler's solver
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

    def check_and_solve(self, page: Any) -> bool:
        """Check if PX is present and solve it.

        One-shot: checks the current page state and solves if PX is there.
        Does NOT wait. Used by the background monitor.

        Args:
            page: Playwright Page object.

        Returns:
            True if PX was not present or was solved.
        """
        if not self.cfg.enabled:
            return True

        # Quick check: is PX UI visible right now?
        try:
            px_visible = bool(page.evaluate(_PX_UI_WATCHER_JS))
        except Exception:
            # Page might be closed or navigating
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

    def start_monitoring(self, page: Any) -> None:
        """Start background monitoring for PX on this page (sync API).

        The monitor runs in a daemon thread, polling the page every
        ``monitor_interval`` seconds. It auto-stops when the page is closed.

        Safe to call multiple times — only starts once per page.
        """
        if getattr(page, '_px_monitor_active', False):
            return
        page._px_monitor_active = True

        interval = self.cfg.monitor_interval

        def _loop() -> None:
            logger.debug("PX monitor started for page (sync)")
            try:
                while getattr(page, '_px_monitor_active', False):
                    # Check if page is still alive
                    try:
                        _ = page.url
                    except Exception:
                        break

                    self.check_and_solve(page)

                    import time as _time
                    _time.sleep(interval)
            except Exception:
                pass
            finally:
                logger.debug("PX monitor stopped for page (sync)")

        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    async def check_and_solve_async(self, page: Any) -> bool:
        """Async version of check_and_solve. Used by async monitor."""
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

    async def start_monitoring_async(self, page: Any) -> None:
        """Start background monitoring for PX on this page (async API).

        Spawns an asyncio task that polls the page every ``monitor_interval``
        seconds. The task auto-cancels when the page is closed.

        Safe to call multiple times — only starts once per page.
        """
        if getattr(page, '_px_monitor_task', None) is not None:
            return

        interval = self.cfg.monitor_interval

        async def _monitor_loop() -> None:
            import asyncio
            logger.debug("PX monitor started for page (async)")
            try:
                while True:
                    # Check if page is still alive
                    try:
                        _ = page.url
                    except Exception:
                        break

                    await self.check_and_solve_async(page)
                    await asyncio.sleep(interval)
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
            finally:
                page._px_monitor_task = None
                logger.debug("PX monitor stopped for page (async)")

        import asyncio
        page._px_monitor_task = asyncio.create_task(_monitor_loop())