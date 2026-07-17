"""Base SiteHandler class."""
from __future__ import annotations
from ..detect.base import BaseDetector, DetectResult
from ..detect.composite import CompositeDetector
from ..solve.base import BaseSolver, SolveResult
from ..solve.composite import CompositeSolver


class SiteHandler:
    """Base class for site-specific PX configurations.

    Each subclass defines:
    - A URL pattern to restrict handler to a specific domain
    - Which detectors and solvers to use for that site
    """

    name: str = "generic"
    priority: int = 0  # Higher = tried first
    url_pattern: str | None = None  # e.g. "ifood.com.br"

    def match_url(self, page: object) -> bool:
        """Check if this handler should run on the current page.

        Returns True if the page URL matches this handler's domain.
        If url_pattern is None, matches any page.
        """
        if self.url_pattern is None:
            return True
        try:
            url = page.url
            return self.url_pattern in url
        except Exception:
            return False

    def build_detector(self) -> BaseDetector:
        """Build the detection strategy for this site."""
        raise NotImplementedError

    def build_solver(self) -> BaseSolver:
        """Build the solving strategy for this site."""
        raise NotImplementedError

    def detect(self, page: object) -> DetectResult:
        """Run detection for this site."""
        return self.build_detector().detect(page)

    async def detect_async(self, page: object) -> DetectResult:
        """Run detection for an async Playwright page."""
        return await self.build_detector().detect_async(page)

    def solve(self, page: object, cfg: object, detect_result: DetectResult | None = None) -> SolveResult:
        """Run solving for this site."""
        return self.build_solver().solve(page, cfg, detect_result)