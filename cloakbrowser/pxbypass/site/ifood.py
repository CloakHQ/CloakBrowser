"""iFood-specific PX handler."""
from __future__ import annotations
from ..detect.base import BaseDetector
from ..detect.composite import CompositeDetector
from ..detect.keyword import DetectPxByKeyword
from ..detect.dom_element import DetectPxByDomElement
from ..solve.base import BaseSolver
from ..solve.composite import CompositeSolver
from ..solve.press_hold_button import SolveByHoldButton
from .base import SiteHandler


class IfoodHandler(SiteHandler):
    """iFood.com.br uses PerimeterX with iframe modal (same-origin)."""

    name = "ifood"
    priority = 10

    def build_detector(self) -> BaseDetector:
        return CompositeDetector([
            DetectPxByKeyword(["pressione e segure", "antes de continuarmos", "confirmar que você"]),
            DetectPxByDomElement(["#px-captcha-modal", "#px-captcha"]),
        ])

    def build_solver(self) -> BaseSolver:
        return CompositeSolver([
            SolveByHoldButton(["Pressione e segure", "Press and hold"]),
        ])
