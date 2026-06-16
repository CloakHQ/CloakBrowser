"""Detect PX by checking page script sources for PX CDN URLs."""
from __future__ import annotations
from typing import Any
from .base import BaseDetector, DetectResult

PX_SCRIPT_PATTERNS = [
    "px-cloud.net",
    "client.px-cloud.net",
    "collector-px",
    "/px/",
    "perimeterx",
]

class DetectPxByScriptSrc(BaseDetector):
    """Detect PerimeterX by scanning script src URLs."""
    def __init__(self, patterns: list[str] | None = None):
        self.patterns = patterns or PX_SCRIPT_PATTERNS

    def detect(self, page: Any) -> DetectResult:
        try:
            scripts = page.evaluate("""() => {
                const urls = [];
                document.querySelectorAll('script').forEach(s => {
                    if (s.src) urls.push(s.src);
                });
                return urls;
            }""")
            if not scripts:
                return DetectResult()
            found = []
            for s in scripts:
                for p in self.patterns:
                    if p in s:
                        found.append({"script": s[:120], "pattern": p})
                        break
            if not found:
                return DetectResult()
            return DetectResult(
                detected=True,
                confidence=0.9 if any("main.min.js" in f["script"] for f in found) else 0.75,
                evidence={"scripts_matched": found},
            )
        except Exception as exc:
            return DetectResult(evidence={"error": str(exc)})
