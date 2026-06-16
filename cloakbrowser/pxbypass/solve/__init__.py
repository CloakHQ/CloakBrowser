"""Solving strategies for PerimeterX challenges."""
from .base import BaseSolver, SolveResult, HoldTarget
from .press_hold_button import SolveByHoldButton
from .press_hold_container import SolveByHoldContainer
from .composite import CompositeSolver

__all__ = [
    "BaseSolver", "SolveResult", "HoldTarget",
    "SolveByHoldButton", "SolveByHoldContainer",
    "CompositeSolver",
]
