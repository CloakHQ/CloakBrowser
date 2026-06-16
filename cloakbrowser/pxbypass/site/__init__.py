"""Site-specific PX detection and solving configurations."""
from .base import SiteHandler
from .walmart import WalmartHandler
from .ifood import IfoodHandler

__all__ = ["SiteHandler", "WalmartHandler", "IfoodHandler"]
