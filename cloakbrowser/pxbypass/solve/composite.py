"""Composite solver that tries multiple strategies in order."""
from __future__ import annotations
import logging, time
from typing import Any
from .base import BaseSolver, SolveResult

logger = logging.getLogger("cloakbrowser.pxbypass.solve")


class CompositeSolver(BaseSolver):
    """Try multiple solvers in order until one succeeds.

    Usage:
        solver = CompositeSolver([
            SolveByHoldButton(),
            SolveByHoldContainer(),
        ])
    """

    def __init__(self, solvers: list[BaseSolver], stop_on_first: bool = True):
        """
        Args:
            solvers: List of solver instances, tried in order.
            stop_on_first: If True, stop after first success.
        """
        self.solvers = solvers
        self.stop_on_first = stop_on_first

    def solve(self, page: Any, cfg: Any, detect_result: Any = None) -> SolveResult:
        results = []
        for solver in self.solvers:
            logger.debug("Trying solver: %s", solver.__class__.__name__)
            result = solver.solve(page, cfg, detect_result)
            results.append(result)
            if result.solved and self.stop_on_first:
                logger.info("Solver %s succeeded", solver.__class__.__name__)
                return result
            if not result.solved:
                logger.debug("Solver %s failed: %s", solver.__class__.__name__, result.error)
        # Return best result
        solved = [r for r in results if r.solved]
        if solved:
            return solved[0]
        if results:
            return results[-1]
        return SolveResult(method="CompositeSolver", error="no_solvers")

    async def async_solve(self, page: Any, cfg: Any, detect_result: Any = None) -> SolveResult:
        results = []
        for solver in self.solvers:
            logger.debug("Trying async solver: %s", solver.__class__.__name__)
            result = await solver.async_solve(page, cfg, detect_result)
            results.append(result)
            if result.solved and self.stop_on_first:
                logger.info("Async solver %s succeeded", solver.__class__.__name__)
                return result
            if not result.solved:
                logger.debug("Async solver %s failed: %s", solver.__class__.__name__, result.error)
        solved = [result for result in results if result.solved]
        if solved:
            return solved[0]
        if results:
            return results[-1]
        return SolveResult(method="CompositeSolver", error="no_solvers")
