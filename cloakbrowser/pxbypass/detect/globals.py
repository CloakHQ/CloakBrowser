"""Detect PX by checking for JS global objects."""
from __future__ import annotations
from typing import Any
from .base import BaseDetector, DetectResult

PX_GLOBAL_KEYS = ["_px", "px_captcha", "PX", "PERIMETERX"]

class DetectPxByGlobals(BaseDetector):
    """Detect PerimeterX by checking for known global JS variables."""
    def __init__(self, keys: list[str] | None = None):
        self.keys = keys or PX_GLOBAL_KEYS

    def detect(self, page: Any) -> DetectResult:
        try:
            found = []
            for key in self.keys:
                exists = page.evaluate("(k) => k in window", key)
                if exists:
                    found.append(key)
            if not found:
                return DetectResult()
            return DetectResult(
                detected=True,
                confidence=0.6,
                evidence={"globals_found": found},
            )
        except Exception as exc:
            return DetectResult(evidence={"error": str(exc)})
