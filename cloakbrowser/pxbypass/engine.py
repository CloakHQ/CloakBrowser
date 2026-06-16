"""PxEngine: orchestrates detection → solving for PerimeterX challenges.

Auto-detects the PX variant using site-specific handlers and generic
detectors, then selects the best solving strategy.
"""
from __future__ import annotations

import logging
import time
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

    def detect_and_solve(self, page: Any) -> bool:
        """Convenience: detect and solve in one call.

        Args:
            page: Playwright Page object.

        Returns:
            True if PX was solved or not present.
        """
        if not self.cfg.enabled:
            return True

        handler, result = self.detect(page)
        if not result.detected:
            logger.debug("No PX detected, skipping solve")
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