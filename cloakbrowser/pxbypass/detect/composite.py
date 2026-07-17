"""Composite detector that runs multiple sub-detectors."""
from __future__ import annotations
from enum import Enum
from typing import Any
from .base import BaseDetector, DetectResult

class DetectMode(Enum):
    """How sub-detector results are combined."""
    ANY = "any"       # At least one detector hits
    ALL = "all"       # All detectors must hit
    WEIGHTED = "weighted"  # Weighted confidence average


class CompositeDetector(BaseDetector):
    """Run multiple detection strategies and combine results.

    Usage:
        detector = CompositeDetector([
            DetectPxByKeyword(["robot or human"]),
            DetectPxByDomElement(["#px-captcha"]),
            DetectPxByScriptSrc(["px-cloud.net"]),
        ], mode=DetectMode.ANY)
    """

    def __init__(
        self,
        detectors: list[BaseDetector],
        mode: DetectMode = DetectMode.ANY,
        min_confidence: float = 0.3,
    ):
        """
        Args:
            detectors: List of detector instances.
            mode: How to combine results.
            min_confidence: Minimum confidence to consider a positive detection.
        """
        self.detectors = detectors
        self.mode = mode
        self.min_confidence = min_confidence

    def detect(self, page: Any) -> DetectResult:
        results = [d.detect(page) for d in self.detectors]
        return self._combine(results)

    async def detect_async(self, page: Any) -> DetectResult:
        results = [await detector.detect_async(page) for detector in self.detectors]
        return self._combine(results)

    def _combine(self, results: list[DetectResult]) -> DetectResult:
        hits = [r for r in results if r.detected and r.confidence >= self.min_confidence]

        if self.mode == DetectMode.ALL:
            if len(hits) < len(self.detectors):
                return DetectResult(
                    confidence=max((r.confidence for r in hits), default=0.0),
                    evidence={"partial_hits": [r.evidence for r in hits]},
                )
        elif self.mode == DetectMode.ANY:
            if not hits:
                return DetectResult()

        # Weighted confidence: higher from more detectors
        avg_conf = sum(r.confidence for r in hits) / len(hits) if hits else 0.0
        count_bonus = min(len(hits) * 0.1, 0.2)
        final_conf = min(avg_conf + count_bonus, 1.0)

        # Collect evidence
        evidence = {
            "detectors": [
                {
                    "type": d.__class__.__name__,
                    "result": r.detected,
                    "confidence": r.confidence,
                    "evidence": r.evidence,
                }
                for d, r in zip(self.detectors, results)
            ]
        }

        return DetectResult(
            detected=True,
            confidence=final_conf,
            px_type="perimeterx",
            evidence=evidence,
        )
