"""Human-like behavioral layer for cloakbrowser.

Activated via ``humanize=True`` in ``launch()`` / ``launch_async()``.

Every humanized action (page, frame, locator, element handle, mouse,
keyboard; sync and async API) runs through one engine (``engine.py``):

* elements are resolved by Playwright's own selector engine running in a CDP
  isolated world per frame (``world.py`` / ``injected.py``) -- full selector
  syntax (role, label, text, ``>>`` chains, filters, frame locators) and
  strict mode;
* scrolling uses mouse-wheel bursts, pointer movement uses Bezier curves,
  every press is preceded by a hit-target check (also through iframes);
* Playwright's options and timeouts are honoured; failures raise Playwright
  ``Error`` / ``TimeoutError`` instead of falling back to Playwright's stock
  actions.
"""

from __future__ import annotations

from .config import HumanConfig, HumanPreset, merge_config, resolve_config
from .engine import CursorState, Human
from .errors import (
    ActionabilityError, ElementNotAttachedError, ElementNotEditableError,
    ElementNotEnabledError, ElementNotReceivingEventsError, ElementNotStableError,
    ElementNotVisibleError, ElementTargetChangedError,
    StealthDomError, StealthEvaluationError, StealthWorldUnavailableError,
    UnsupportedHumanizeSelectorError,
)
from .keyboard import human_type
from .mouse import click_target, human_click, human_idle, human_move
from .patch import (
    patch_browser, patch_browser_async, patch_context, patch_context_async,
    patch_page, patch_page_async,
)

# Backwards-compatible name used by callers that build pages manually.
_CursorState = CursorState

__all__ = [
    "patch_browser", "patch_context", "patch_page",
    "patch_browser_async", "patch_context_async", "patch_page_async",
    "HumanConfig", "HumanPreset", "resolve_config", "merge_config", "CursorState", "Human",
    "human_move", "human_click", "click_target", "human_idle",
    "human_type",
    # Error classes kept for API compatibility (actions raise Playwright errors).
    "ActionabilityError", "ElementNotAttachedError", "ElementNotVisibleError",
    "ElementNotStableError", "ElementNotEnabledError", "ElementNotEditableError",
    "ElementNotReceivingEventsError", "ElementTargetChangedError",
    "StealthDomError", "UnsupportedHumanizeSelectorError",
    "StealthWorldUnavailableError", "StealthEvaluationError",
]
