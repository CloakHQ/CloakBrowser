"""Detect PX by scanning page body text for known keywords."""
from __future__ import annotations
from typing import Any
from .base import BaseDetector, DetectResult

# Default keyword sets for different PX variants
PERIMETERX_KEYWORDS = [
    "pressione e segure",
    "press and hold",
    "press & hold",
    "activate and hold",
    "antes de continuarmos",
    "confirmar que você é um humano",
    "robot or human",
]

# Keywords that strongly indicate an active PX challenge
HIGH_CONFIDENCE_KEYWORDS = [
    "activate and hold the button",
    "pressione e segure o botão",
    "press and hold the button",
    "confirm that you're human",
    "confirmar que você é um humano",
]


class DetectPxByKeyword(BaseDetector):
    """Detect PerimeterX challenge by scanning page body text.

    The body text often contains phrases like:
    - "Activate and hold the button to confirm that you're human."
    - "Robot or human?"
    - "Pressione e segure o botão"
    """

    def __init__(self, keywords: list[str] | None = None):
        """
        Args:
            keywords: Custom keyword list. Uses defaults if None.
        """
        self.keywords = keywords or PERIMETERX_KEYWORDS

    def detect(self, page: Any) -> DetectResult:
        """Scan page body text for PX-related keywords."""
        try:
            body = page.evaluate(
                "() => (document.body ? document.body.innerText : '') || ''"
            )
            if not body:
                return DetectResult()

            body_lower = body.lower()
            matches = [kw for kw in self.keywords if kw.lower() in body_lower]

            if not matches:
                return DetectResult()

            # Check high-confidence matches
            hc_matches = [kw for kw in HIGH_CONFIDENCE_KEYWORDS if kw.lower() in body_lower]
            confidence = 0.9 if hc_matches else min(0.5 + len(matches) * 0.15, 0.85)

            return DetectResult(
                detected=True,
                confidence=confidence,
                px_type="perimeterx",
                evidence={"keywords_matched": matches, "high_confidence": hc_matches or None},
            )
        except Exception as exc:
            return DetectResult(evidence={"error": str(exc)})

    async def detect_async(self, page: Any) -> DetectResult:
        """Scan an async Playwright page for PX-related keywords."""
        try:
            body = await page.evaluate(
                "() => (document.body ? document.body.innerText : '') || ''"
            )
            if not body:
                return DetectResult()
            body_lower = body.lower()
            matches = [kw for kw in self.keywords if kw.lower() in body_lower]
            if not matches:
                return DetectResult()
            hc_matches = [kw for kw in HIGH_CONFIDENCE_KEYWORDS if kw.lower() in body_lower]
            confidence = 0.9 if hc_matches else min(0.5 + len(matches) * 0.15, 0.85)
            return DetectResult(
                detected=True,
                confidence=confidence,
                px_type="perimeterx",
                evidence={"keywords_matched": matches, "high_confidence": hc_matches or None},
            )
        except Exception as exc:
            return DetectResult(evidence={"error": str(exc)})