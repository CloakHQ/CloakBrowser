"""Detection strategies for PerimeterX challenges."""
from .base import BaseDetector, DetectResult
from .keyword import DetectPxByKeyword
from .dom_element import DetectPxByDomElement
from .script_src import DetectPxByScriptSrc
from .url_pattern import DetectPxByUrlPattern
from .globals import DetectPxByGlobals
from .composite import CompositeDetector, DetectMode

__all__ = [
    "BaseDetector", "DetectResult",
    "DetectPxByKeyword", "DetectPxByDomElement", "DetectPxByScriptSrc",
    "DetectPxByUrlPattern", "DetectPxByGlobals",
    "CompositeDetector", "DetectMode",
]