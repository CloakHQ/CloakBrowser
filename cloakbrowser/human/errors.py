"""Error classes kept for API compatibility.

The unified engine raises Playwright ``Error`` / ``TimeoutError`` (with a call
log) instead; these classes stay importable from ``cloakbrowser.human`` so
existing ``except`` clauses and imports keep working. Same set as the JS
(``js/src/human/errors.ts``) and .NET (``Human/Actionability.cs``) ports.
"""

from __future__ import annotations


class ActionabilityError(RuntimeError):
    """Base for all actionability failures."""

    def __init__(self, selector: str, check: str, message: str):
        self.selector = selector
        self.check = check
        super().__init__(f"Element {selector!r} failed {check} check: {message}")


class ElementNotAttachedError(ActionabilityError):
    def __init__(self, selector: str):
        super().__init__(selector, "attached", "element not found in DOM")


class ElementNotVisibleError(ActionabilityError):
    def __init__(self, selector: str):
        super().__init__(selector, "visible", "element is not visible")


class ElementNotStableError(ActionabilityError):
    def __init__(self, selector: str):
        super().__init__(selector, "stable", "element position is still changing")


class ElementNotEnabledError(ActionabilityError):
    def __init__(self, selector: str):
        super().__init__(selector, "enabled", "element is disabled")


class ElementNotEditableError(ActionabilityError):
    def __init__(self, selector: str):
        super().__init__(selector, "editable", "element is not editable")


class ElementNotReceivingEventsError(ActionabilityError):
    def __init__(self, selector: str, covering_tag: str = "unknown"):
        self.covering_tag = covering_tag
        super().__init__(selector, "pointer_events", f"element is covered by <{covering_tag}>")


class ElementTargetChangedError(ActionabilityError):
    def __init__(self, selector: str):
        super().__init__(
            selector, "target_identity",
            "selector resolved to a different element before input dispatch",
        )


# Raised by the previous humanize layer; the engine no longer raises them.

class StealthDomError(RuntimeError):
    """Base for isolated-world DOM helper failures."""


class UnsupportedHumanizeSelectorError(StealthDomError):
    def __init__(self, selector: str):
        super().__init__(f"Humanized selector {selector!r} is not supported")


class StealthWorldUnavailableError(StealthDomError):
    def __init__(self):
        super().__init__("Humanized DOM read requires an active isolated world")


class StealthEvaluationError(StealthDomError):
    def __init__(self, selector: str):
        super().__init__(f"Isolated-world DOM evaluation failed for {selector!r}")


__all__ = [
    "ActionabilityError", "ElementNotAttachedError", "ElementNotVisibleError",
    "ElementNotStableError", "ElementNotEnabledError", "ElementNotEditableError",
    "ElementNotReceivingEventsError", "ElementTargetChangedError",
    "StealthDomError", "UnsupportedHumanizeSelectorError",
    "StealthWorldUnavailableError", "StealthEvaluationError",
]
