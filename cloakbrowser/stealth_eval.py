"""Stealth evaluate — run JS in a CDP isolated world.

Provides page.stealth_evaluate(expression) on every page returned by
cloakbrowser launch functions.  Produces clean Error.stack traces (no
``eval at evaluate :302:`` leak) and full variable isolation from main
world JS.  Context auto-recreates after navigation.

The same isolated world instances are reused by the humanize layer
(human/__init__.py) for stealth DOM queries.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("cloakbrowser.stealth_eval")


# ============================================================================
# Isolated world classes
# ============================================================================

class _SyncIsolatedWorld:
    """CDP isolated execution context for DOM reads (sync).

    Produces clean Error.stack traces and is invisible to
    querySelector monkey-patches in the main world.
    Context ID is invalidated on navigation and auto-recreated.
    """

    __slots__ = ("_page", "_cdp", "_context_id")

    def __init__(self, page: Any):
        self._page = page
        self._cdp: Any = None
        self._context_id: Optional[int] = None

    def _ensure_cdp(self) -> Any:
        if self._cdp is None:
            self._cdp = self._page.context.new_cdp_session(self._page)
        return self._cdp

    def _create_world(self) -> int:
        cdp = self._ensure_cdp()
        tree = cdp.send("Page.getFrameTree")
        frame_id = tree["frameTree"]["frame"]["id"]
        result = cdp.send("Page.createIsolatedWorld", {
            "frameId": frame_id,
            "worldName": "",
            "grantUniveralAccess": True,
        })
        self._context_id = result["executionContextId"]
        return self._context_id

    def evaluate(self, expression: str) -> Any:
        """Evaluate JS in isolated world. Auto-recreates on stale context."""
        if self._context_id is None:
            try:
                self._create_world()
            except Exception:
                logger.debug("stealth_evaluate: failed to create isolated world")
                return None

        for attempt in range(2):
            try:
                result = self._cdp.send("Runtime.evaluate", {
                    "expression": expression,
                    "contextId": self._context_id,
                    "returnByValue": True,
                })
                if "exceptionDetails" in result:
                    if attempt == 0:
                        self._create_world()
                        continue
                    logger.debug("stealth_evaluate: JS exception: %s",
                                 result["exceptionDetails"].get("text", "unknown"))
                    return None
                return result.get("result", {}).get("value")
            except Exception:
                if attempt == 0:
                    self._context_id = None
                    try:
                        self._create_world()
                    except Exception:
                        logger.debug("stealth_evaluate: failed to recreate isolated world")
                        return None
                    continue
                logger.debug("stealth_evaluate: CDP evaluate failed after retry")
                return None
        return None

    def invalidate(self) -> None:
        """Mark context as stale — call after navigation."""
        self._context_id = None

    def get_cdp_session(self) -> Any:
        """Get the underlying CDP session (reused for Input.dispatchKeyEvent)."""
        return self._ensure_cdp()


class _AsyncIsolatedWorld:
    """CDP isolated execution context for DOM reads (async).

    Same as _SyncIsolatedWorld but uses await for all CDP calls.
    """

    __slots__ = ("_page", "_cdp", "_context_id")

    def __init__(self, page: Any):
        self._page = page
        self._cdp: Any = None
        self._context_id: Optional[int] = None

    async def _ensure_cdp(self) -> Any:
        if self._cdp is None:
            self._cdp = await self._page.context.new_cdp_session(self._page)
        return self._cdp

    async def _create_world(self) -> int:
        cdp = await self._ensure_cdp()
        tree = await cdp.send("Page.getFrameTree")
        frame_id = tree["frameTree"]["frame"]["id"]
        result = await cdp.send("Page.createIsolatedWorld", {
            "frameId": frame_id,
            "worldName": "",
            "grantUniveralAccess": True,
        })
        self._context_id = result["executionContextId"]
        return self._context_id

    async def evaluate(self, expression: str) -> Any:
        """Evaluate JS in isolated world. Auto-recreates on stale context."""
        if self._context_id is None:
            try:
                await self._create_world()
            except Exception:
                logger.debug("stealth_evaluate: failed to create isolated world")
                return None

        for attempt in range(2):
            try:
                result = await self._cdp.send("Runtime.evaluate", {
                    "expression": expression,
                    "contextId": self._context_id,
                    "returnByValue": True,
                })
                if "exceptionDetails" in result:
                    if attempt == 0:
                        await self._create_world()
                        continue
                    logger.debug("stealth_evaluate: JS exception: %s",
                                 result["exceptionDetails"].get("text", "unknown"))
                    return None
                return result.get("result", {}).get("value")
            except Exception:
                if attempt == 0:
                    self._context_id = None
                    try:
                        await self._create_world()
                    except Exception:
                        logger.debug("stealth_evaluate: failed to recreate isolated world")
                        return None
                    continue
                logger.debug("stealth_evaluate: CDP evaluate failed after retry")
                return None
        return None

    def invalidate(self) -> None:
        """Mark context as stale — call after navigation."""
        self._context_id = None

    async def get_cdp_session(self) -> Any:
        """Get the underlying CDP session (reused for Input.dispatchKeyEvent)."""
        return await self._ensure_cdp()


# ============================================================================
# Page / context / browser patching
# ============================================================================

def _patch_page_sync(page: Any) -> None:
    """Attach page.stealth_evaluate() using a sync isolated world."""
    if hasattr(page, "stealth_evaluate"):
        return
    existing = getattr(page, "_stealth_world", None)
    if isinstance(existing, _SyncIsolatedWorld):
        world = existing
    else:
        world = _SyncIsolatedWorld(page)
        page._stealth_world = world
    page.stealth_evaluate = world.evaluate


def _patch_page_async(page: Any) -> None:
    """Attach page.stealth_evaluate() using an async isolated world."""
    if hasattr(page, "stealth_evaluate"):
        return
    existing = getattr(page, "_stealth_world", None)
    if isinstance(existing, _AsyncIsolatedWorld):
        world = existing
    else:
        world = _AsyncIsolatedWorld(page)
        page._stealth_world = world
    page.stealth_evaluate = world.evaluate


def patch_context_stealth_eval(context: Any, *, is_async: bool = False) -> None:
    """Patch existing pages + hook new_page() for stealth_evaluate."""
    if getattr(context, "_stealth_eval_patched", False):
        return
    context._stealth_eval_patched = True
    patch_fn = _patch_page_async if is_async else _patch_page_sync

    for p in context.pages:
        patch_fn(p)

    orig_new_page = context.new_page

    if is_async:
        async def _patched_new_page(*args: Any, **kwargs: Any) -> Any:
            page = await orig_new_page(*args, **kwargs)
            patch_fn(page)
            return page
    else:
        def _patched_new_page(*args: Any, **kwargs: Any) -> Any:
            page = orig_new_page(*args, **kwargs)
            patch_fn(page)
            return page

    context.new_page = _patched_new_page
    context.on("page", lambda p: patch_fn(p))


def patch_browser_stealth_eval(browser: Any, *, is_async: bool = False) -> None:
    """Patch browser factory methods for stealth_evaluate."""
    patch_fn = _patch_page_async if is_async else _patch_page_sync

    # Hook new_context()
    orig_new_context = browser.new_context

    if is_async:
        async def _patched_new_context(*args: Any, **kwargs: Any) -> Any:
            ctx = await orig_new_context(*args, **kwargs)
            patch_context_stealth_eval(ctx, is_async=True)
            return ctx
    else:
        def _patched_new_context(*args: Any, **kwargs: Any) -> Any:
            ctx = orig_new_context(*args, **kwargs)
            patch_context_stealth_eval(ctx, is_async=False)
            return ctx

    browser.new_context = _patched_new_context

    # Hook new_page()
    orig_new_page = browser.new_page

    if is_async:
        async def _patched_new_page(*args: Any, **kwargs: Any) -> Any:
            page = await orig_new_page(*args, **kwargs)
            patch_context_stealth_eval(page.context, is_async=True)
            patch_fn(page)
            return page
    else:
        def _patched_new_page(*args: Any, **kwargs: Any) -> Any:
            page = orig_new_page(*args, **kwargs)
            patch_context_stealth_eval(page.context, is_async=False)
            patch_fn(page)
            return page

    browser.new_page = _patched_new_page
