"""Base solver class and result types."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass
class HoldTarget:
    """Position of the click/hold target in viewport coordinates."""
    x: float
    y: float
    width: float
    height: float
    source: str = ""


@dataclass
class SolveResult:
    """Result from a solving attempt.

    Attributes:
        solved: Whether the challenge was solved.
        attempts: Number of attempts made.
        method: Name of the solver method used.
        duration: Total time spent solving (seconds).
        error: Error message if failed.
    """
    solved: bool = False
    attempts: int = 0
    method: str = ""
    duration: float = 0.0
    error: str | None = None


class BaseSolver:
    """Abstract base class for PX solving strategies."""

    def solve(self, page: Any, cfg: Any, detect_result: Any = None) -> SolveResult:
        """Attempt to solve the PX challenge.

        Args:
            page: Playwright Page object.
            cfg: PxConfig instance.
            detect_result: Optional DetectResult from detection phase.

        Returns:
            SolveResult indicating success/failure.
        """
        raise NotImplementedError
