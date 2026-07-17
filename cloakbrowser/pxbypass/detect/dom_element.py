"""Detect PX by checking for specific DOM elements."""
from __future__ import annotations
from typing import Any
from .base import BaseDetector, DetectResult

# Common PX-related DOM elements
PX_ELEMENT_SELECTORS = [
    "#px-captcha",
    "#px-captcha-modal",
    ".re-captcha",
    "[data-px-captcha]",
    ".px-challenge",
]

class DetectPxByDomElement(BaseDetector):
    """Detect PerimeterX by checking for known DOM element patterns."""
    def __init__(self, selectors: list[str] | None = None):
        self.selectors = selectors or PX_ELEMENT_SELECTORS

    def detect(self, page: Any) -> DetectResult:
        try:
            found = []
            for sel in self.selectors:
                count = page.evaluate(
                    "(sel) => document.querySelectorAll(sel).length", sel
                )
                if count and count > 0:
                    found.append({"selector": sel, "count": count})
            if not found:
                return DetectResult()
            return DetectResult(
                detected=True,
                confidence=0.85,
                evidence={"elements_found": found},
            )
        except Exception as exc:
            return DetectResult(evidence={"error": str(exc)})

    async def detect_async(self, page: Any) -> DetectResult:
        try:
            found = []
            for sel in self.selectors:
                count = await page.evaluate(
                    "(sel) => document.querySelectorAll(sel).length", sel
                )
                if count and count > 0:
                    found.append({"selector": sel, "count": count})
            if not found:
                return DetectResult()
            return DetectResult(
                detected=True,
                confidence=0.85,
                evidence={"elements_found": found},
            )
        except Exception as exc:
            return DetectResult(evidence={"error": str(exc)})
