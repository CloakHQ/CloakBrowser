"""Walmart-specific PX handler."""
from __future__ import annotations
from ..detect.base import BaseDetector
from ..detect.composite import CompositeDetector
from ..detect.keyword import DetectPxByKeyword
from ..detect.dom_element import DetectPxByDomElement
from ..detect.script_src import DetectPxByScriptSrc
from ..solve.base import BaseSolver
from ..solve.composite import CompositeSolver
from ..solve.press_hold_button import SolveByHoldButton
from ..solve.press_hold_container import SolveByHoldContainer
from .base import SiteHandler


class WalmartHandler(SiteHandler):
    """Walmart.com uses PerimeterX Cloud with cross-origin iframe."""

    name = "walmart"
    priority = 10
    url_pattern = "walmart.com"  # Only runs on walmart pages

    def build_detector(self) -> BaseDetector:
        return CompositeDetector([
            DetectPxByKeyword(["activate and hold", "robot or human", "Activate and hold the button"]),
            DetectPxByDomElement(["#px-captcha", ".re-captcha"]),
            DetectPxByScriptSrc(["px-cloud.net", "client.px-cloud.net"]),
        ])

    def build_solver(self) -> BaseSolver:
        return CompositeSolver([
            SolveByHoldButton(["Activate and hold"]),
            SolveByHoldContainer("#px-captcha"),
        ])