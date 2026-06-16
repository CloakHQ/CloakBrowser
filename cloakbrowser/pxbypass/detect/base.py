"""Base detector class and detection result."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any


@dataclass
class DetectResult:
    """Result from a detection strategy.

    Attributes:
        detected: Whether the PX challenge was detected.
        confidence: Detection confidence score (0.0 - 1.0).
        px_type: Type of PX detected ('perimeterx' or site-specific).
        evidence: Optional data supporting the detection (e.g. matched text).
    """
    detected: bool = False
    confidence: float = 0.0
    px_type: str = "perimeterx"
    evidence: dict | None = None


class BaseDetector:
    """Abstract base class for PX detection strategies.

    Each subclass implements a single detection method (keyword scan,
    DOM element check, script URL check, etc.).
    """

    def detect(self, page: Any) -> DetectResult:
        """Run this detection strategy on the page.

        Args:
            page: Playwright Page object (sync or async compatible).

        Returns:
            DetectResult with detection status and evidence.
        """
        raise NotImplementedError