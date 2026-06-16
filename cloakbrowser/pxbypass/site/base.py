"""Base SiteHandler class."""
from __future__ import annotations
from ..detect.base import BaseDetector, DetectResult
from ..detect.composite import CompositeDetector
from ..solve.base import BaseSolver, SolveResult
from ..solve.composite import CompositeSolver


class SiteHandler:
    """Base class for site-specific PX configurations.

    Each subclass defines which detectors and solvers to use,
    including site-specific keywords, selectors, and parameters.
    """

    name: str = "generic"
    priority: int = 0  # Higher = tried first

    def build_detector(self) -> BaseDetector:
        """Build the detection strategy for this site."""
        raise NotImplementedError

    def build_solver(self) -> BaseSolver:
        """Build the solving strategy for this site."""
        raise NotImplementedError

    def detect(self, page: object) -> DetectResult:
        """Run detection for this site."""
        return self.build_detector().detect(page)

    def solve(self, page: object, cfg: object, detect_result: DetectResult | None = None) -> SolveResult:
        """Run solving for this site."""
        return self.build_solver().solve(page, cfg, detect_result)
