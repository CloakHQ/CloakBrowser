"""Detect PX by checking page URL patterns."""
from __future__ import annotations
from typing import Any
from .base import BaseDetector, DetectResult

PX_URL_PATTERNS = [
    "/blocked",
    "px-captcha",
    "captcha",
]

class DetectPxByUrlPattern(BaseDetector):
    """Detect PerimeterX by analyzing the page URL."""
    def __init__(self, patterns: list[str] | None = None):
        self.patterns = patterns or PX_URL_PATTERNS

    def detect(self, page: Any) -> DetectResult:
        try:
            url = page.evaluate("() => window.location.href")
            if not url:
                return DetectResult()
            url_lower = url.lower()
            found = [p for p in self.patterns if p.lower() in url_lower]
            if not found:
                return DetectResult()
            return DetectResult(
                detected=True,
                confidence=0.7,
                px_type="perimeterx",
                evidence={"url_patterns": found, "url": url[:200]},
            )
        except Exception as exc:
            return DetectResult(evidence={"error": str(exc)})
