"""Human-like behavioral layer for cloakbrowser.

Activated via humanize=True in launch() / launch_async().
Patches page methods to use Bezier mouse curves, realistic typing, and smooth scrolling.

Stealth-aware (fixes #110):
  - isInputElement / isSelectorFocused use CDP Isolated Worlds instead of page.evaluate
  - Shift symbol typing uses CDP Input.dispatchKeyEvent for isTrusted=true events
  - Falls back to page.evaluate only when CDP session is unavailable

Supports both sync and async Playwright APIs.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any, Optional

from .config import HumanConfig, HumanPreset, resolve_config, merge_config
from .config import rand, rand_range, sleep_ms, async_sleep_ms
from .mouse import RawMouse, human_move, human_click, click_target, human_idle
from .keyboard import RawKeyboard, human_type
from .scroll import scroll_to_element, human_scroll_into_view
from .mouse_async import AsyncRawMouse, async_human_move, async_human_click, async_human_idle
from .keyboard_async import AsyncRawKeyboard, async_human_type
from .scroll_async import async_scroll_to_element, async_human_scroll_into_view

_SELECT_ALL = "Meta+a" if sys.platform == "darwin" else "Control+a"

__all__ = [
    "patch_browser", "patch_context", "patch_page",
    "patch_browser_async", "patch_context_async", "patch_page_async",
    "HumanConfig", "resolve_config", "merge_config",
    "human_move", "human_click", "click_target", "human_idle",
    "human_type", "scroll_to_element", "human_scroll_into_view",
]

logger = logging.getLogger("cloakbrowser.human")


# ============================================================================
# CDP Isolated World — stealth DOM evaluation
# ============================================================================

class _SyncIsolatedWorld:
    """Manages a CDP isolated execution context for DOM reads (sync).

    Produces clean Error.stack traces (no 'eval at evaluate :302:')
    and is invisible to querySelector monkey-patches in the main world.
    Context ID is invalidated on navigation and auto-recreated on next call.
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
            self._create_world()

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
                    return None
                return result.get("result", {}).get("value")
            except Exception:
                if attempt == 0:
                    self._context_id = None
                    try:
                        self._create_world()
                    except Exception:
                        return None
                    continue
                return None
        return None

    def invalidate(self) -> None:
        """Mark context as stale — call after navigation."""
        self._context_id = None

    def get_cdp_session(self) -> Any:
        """Get the underlying CDP session (reused for Input.dispatchKeyEvent)."""
        return self._ensure_cdp()


class _AsyncIsolatedWorld:
    """Manages a CDP isolated execution context for DOM reads (async).

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
            await self._create_world()

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
                    return None
                return result.get("result", {}).get("value")
            except Exception:
                if attempt == 0:
                    self._context_id = None
                    try:
                        await self._create_world()
                    except Exception:
                        return None
                    continue
                return None
        return None

    def invalidate(self) -> None:
        """Mark context as stale — call after navigation."""
        self._context_id = None

    async def get_cdp_session(self) -> Any:
        """Get the underlying CDP session (reused for Input.dispatchKeyEvent)."""
        return await self._ensure_cdp()


# ============================================================================
# Cursor state
# ============================================================================

class _CursorState:
    __slots__ = ("x", "y", "initialized")

    def __init__(self) -> None:
        self.x: float = 0
        self.y: float = 0
        self.initialized: bool = False


# ============================================================================
# Stealth DOM queries — isolated world with evaluate fallback
# ============================================================================

def _is_input_element(page: Any, selector: str) -> bool:
    """Check if selector is an input element. Uses CDP isolated world when available."""
    world: Optional[_SyncIsolatedWorld] = getattr(page, '_stealth_world', None)
    if world is not None:
        try:
            escaped = json.dumps(selector)
            result = world.evaluate(
                f"(() => {{"
                f"  const el = document.querySelector({escaped});"
                f"  if (!el) return false;"
                f"  const tag = el.tagName.toLowerCase();"
                f"  return tag === 'input' || tag === 'textarea'"
                f"    || el.getAttribute('contenteditable') === 'true';"
                f"}})()"
            )
            return bool(result)
        except Exception:
            pass

    # Fallback: page.evaluate (detectable — should only happen if CDP fails)
    try:
        return page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (!el) return false;
                const tag = el.tagName.toLowerCase();
                return tag === 'input' || tag === 'textarea'
                    || el.getAttribute('contenteditable') === 'true';
            }""",
            selector,
        )
    except Exception:
        return False


async def _async_is_input_element(page: Any, selector: str) -> bool:
    """Check if selector is an input element (async). Uses CDP isolated world when available."""
    world: Optional[_AsyncIsolatedWorld] = getattr(page, '_stealth_world', None)
    if world is not None:
        try:
            escaped = json.dumps(selector)
            result = await world.evaluate(
                f"(() => {{"
                f"  const el = document.querySelector({escaped});"
                f"  if (!el) return false;"
                f"  const tag = el.tagName.toLowerCase();"
                f"  return tag === 'input' || tag === 'textarea'"
                f"    || el.getAttribute('contenteditable') === 'true';"
                f"}})()"
            )
            return bool(result)
        except Exception:
            pass

    try:
        return await page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                if (!el) return false;
                const tag = el.tagName.toLowerCase();
                return tag === 'input' || tag === 'textarea'
                    || el.getAttribute('contenteditable') === 'true';
            }""",
            selector,
        )
    except Exception:
        return False


def _is_selector_focused(page: Any, selector: str) -> bool:
    """Check if the element matching selector is currently focused.
    Uses CDP isolated world when available."""
    world: Optional[_SyncIsolatedWorld] = getattr(page, '_stealth_world', None)
    if world is not None:
        try:
            escaped = json.dumps(selector)
            result = world.evaluate(
                f"(() => {{"
                f"  const el = document.querySelector({escaped});"
                f"  return el === document.activeElement;"
                f"}})()"
            )
            return bool(result)
        except Exception:
            pass

    try:
        return page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                return el === document.activeElement;
            }""",
            selector,
        )
    except Exception:
        return False


async def _async_is_selector_focused(page: Any, selector: str) -> bool:
    """Check if the element matching selector is currently focused (async).
    Uses CDP isolated world when available."""
    world: Optional[_AsyncIsolatedWorld] = getattr(page, '_stealth_world', None)
    if world is not None:
        try:
            escaped = json.dumps(selector)
            result = await world.evaluate(
                f"(() => {{"
                f"  const el = document.querySelector({escaped});"
                f"  return el === document.activeElement;"
                f"}})()"
            )
            return bool(result)
        except Exception:
            pass

    try:
        return await page.evaluate(
            """(sel) => {
                const el = document.querySelector(sel);
                return el === document.activeElement;
            }""",
            selector,
        )
    except Exception:
        return False


# ============================================================================
# Locator class-level patching (sync)
# ============================================================================

_locator_sync_patched = False


def _patch_locator_class_sync():
    """Patch all Locator interaction methods to go through humanized page methods."""
    global _locator_sync_patched
    if _locator_sync_patched:
        return
    _locator_sync_patched = True

    from playwright.sync_api._generated import Locator

    _orig_fill = Locator.fill
    _orig_click = Locator.click
    _orig_type = Locator.type
    _orig_dblclick = Locator.dblclick
    _orig_hover = Locator.hover
    _orig_check = Locator.check
    _orig_uncheck = Locator.uncheck
    _orig_set_checked = Locator.set_checked
    _orig_select_option = Locator.select_option
    _orig_press = Locator.press
    _orig_press_sequentially = Locator.press_sequentially
    _orig_tap = Locator.tap
    _orig_drag_to = Locator.drag_to
    _orig_clear = Locator.clear
    _orig_scroll_into_view = getattr(Locator, 'scroll_into_view_if_needed', None)

    def _get_selector(self):
        return self._impl_obj._selector

    def _is_humanized(self):
        return hasattr(self.page, '_original')

    def _get_cfg(self):
        return getattr(self.page, '_human_cfg', None)

    # Forward only options the page-level humanized methods understand
    # (timeout, human_config). Other Locator-specific kwargs (force, trial,
    # noWaitAfter, ...) are silently dropped — the humanized path doesn't
    # consult them.
    def _forward_kwargs(kwargs):
        out = {}
        if "timeout" in kwargs:
            out["timeout"] = kwargs["timeout"]
        if "human_config" in kwargs:
            out["human_config"] = kwargs["human_config"]
        return out

    def _humanized_fill(self, value, **kwargs):
        if _is_humanized(self):
            self.page.fill(_get_selector(self), value, **_forward_kwargs(kwargs))
        else:
            _orig_fill(self, value, **kwargs)

    def _humanized_click(self, **kwargs):
        if _is_humanized(self):
            self.page.click(_get_selector(self), **_forward_kwargs(kwargs))
        else:
            _orig_click(self, **kwargs)

    def _humanized_type(self, text, **kwargs):
        if _is_humanized(self):
            self.page.type(_get_selector(self), text, **_forward_kwargs(kwargs))
        else:
            _orig_type(self, text, **kwargs)

    def _humanized_dblclick(self, **kwargs):
        if _is_humanized(self):
            self.page.dblclick(_get_selector(self), **_forward_kwargs(kwargs))
        else:
            _orig_dblclick(self, **kwargs)

    def _humanized_hover(self, **kwargs):
        if _is_humanized(self):
            self.page.hover(_get_selector(self), **_forward_kwargs(kwargs))
        else:
            _orig_hover(self, **kwargs)

    def _humanized_scroll_into_view_if_needed(self, **kwargs):
        if _is_humanized(self):
            page = self.page
            cfg = _get_cfg(self)
            cursor = getattr(page, '_human_cursor', None)
            raw = getattr(page, '_human_raw_mouse', None)
            call_cfg = merge_config(cfg, kwargs.get("human_config")) if cfg else None
            if call_cfg is None or cursor is None or raw is None:
                if _orig_scroll_into_view is not None:
                    native_kwargs = {k: v for k, v in kwargs.items() if k != "human_config"}
                    return _orig_scroll_into_view(self, **native_kwargs)
                return
            timeout = kwargs.get("timeout", 30000)
            try:
                _, nx, ny = human_scroll_into_view(
                    page, raw,
                    lambda: self.bounding_box(timeout=timeout),
                    cursor.x, cursor.y, call_cfg,
                )
                cursor.x = nx
                cursor.y = ny
            except Exception:
                if _orig_scroll_into_view is not None:
                    native_kwargs = {k: v for k, v in kwargs.items() if k != "human_config"}
                    _orig_scroll_into_view(self, **native_kwargs)
        elif _orig_scroll_into_view is not None:
            _orig_scroll_into_view(self, **kwargs)

    def _humanized_check(self, **kwargs):
        if _is_humanized(self):
            cfg = _get_cfg(self)
            if cfg and cfg.idle_between_actions:
                raw = type("_R", (), {"move": self.page._original.mouse_move})()
                human_idle(raw, rand(cfg.idle_between_duration[0], cfg.idle_between_duration[1]), 0, 0, cfg)
            checked = self.is_checked()
            if not checked:
                self.page.click(_get_selector(self))
        else:
            _orig_check(self, **kwargs)

    def _humanized_uncheck(self, **kwargs):
        if _is_humanized(self):
            cfg = _get_cfg(self)
            if cfg and cfg.idle_between_actions:
                raw = type("_R", (), {"move": self.page._original.mouse_move})()
                human_idle(raw, rand(cfg.idle_between_duration[0], cfg.idle_between_duration[1]), 0, 0, cfg)
            checked = self.is_checked()
            if checked:
                self.page.click(_get_selector(self))
        else:
            _orig_uncheck(self, **kwargs)

    def _humanized_set_checked(self, checked, **kwargs):
        if _is_humanized(self):
            current = self.is_checked()
            if current != checked:
                self.page.click(_get_selector(self))
        else:
            _orig_set_checked(self, checked, **kwargs)

    def _humanized_select_option(self, value=None, **kwargs):
        if _is_humanized(self):
            selector = _get_selector(self)
            self.page.hover(selector)
            sleep_ms(rand(100, 300))
            _orig_select_option(self, value, **kwargs)
        else:
            _orig_select_option(self, value, **kwargs)

    def _humanized_press(self, key, **kwargs):
        if _is_humanized(self):
            selector = _get_selector(self)
            if not _is_selector_focused(self.page, selector):
                self.page.click(selector)
            sleep_ms(rand(50, 150))
            self.page.keyboard.press(key)
        else:
            _orig_press(self, key, **kwargs)

    def _humanized_press_sequentially(self, text, **kwargs):
        if _is_humanized(self):
            selector = _get_selector(self)
            if not _is_selector_focused(self.page, selector):
                self.page.click(selector)
            sleep_ms(rand(50, 150))
            self.page.keyboard.type(text)
        else:
            _orig_press_sequentially(self, text, **kwargs)

    def _humanized_tap(self, **kwargs):
        if _is_humanized(self):
            self.page.click(_get_selector(self))
        else:
            _orig_tap(self, **kwargs)

    def _humanized_drag_to(self, target, **kwargs):
        if _is_humanized(self):
            page = self.page
            originals = getattr(page, '_original', None)
            src_box = self.bounding_box()
            tgt_box = target.bounding_box()
            if src_box and tgt_box and originals:
                sx = src_box['x'] + src_box['width'] / 2
                sy = src_box['y'] + src_box['height'] / 2
                tx = tgt_box['x'] + tgt_box['width'] / 2
                ty = tgt_box['y'] + tgt_box['height'] / 2
                page.mouse.move(sx, sy)
                sleep_ms(rand(100, 200))
                originals.mouse_down()
                sleep_ms(rand(80, 150))
                page.mouse.move(tx, ty)
                sleep_ms(rand(80, 150))
                originals.mouse_up()
            else:
                _orig_drag_to(self, target, **kwargs)
        else:
            _orig_drag_to(self, target, **kwargs)

    def _humanized_clear(self, **kwargs):
        if _is_humanized(self):
            selector = _get_selector(self)
            if not _is_selector_focused(self.page, selector):
                self.page.click(selector)
            sleep_ms(rand(50, 100))
            self.page.keyboard.press(_SELECT_ALL)
            sleep_ms(rand(30, 80))
            self.page.keyboard.press("Backspace")
        else:
            _orig_clear(self, **kwargs)

    Locator.fill = _humanized_fill
    Locator.click = _humanized_click
    Locator.type = _humanized_type
    Locator.dblclick = _humanized_dblclick
    Locator.hover = _humanized_hover
    Locator.check = _humanized_check
    Locator.uncheck = _humanized_uncheck
    Locator.set_checked = _humanized_set_checked
    Locator.select_option = _humanized_select_option
    Locator.press = _humanized_press
    Locator.press_sequentially = _humanized_press_sequentially
    Locator.tap = _humanized_tap
    Locator.drag_to = _humanized_drag_to
    Locator.clear = _humanized_clear
    if _orig_scroll_into_view is not None:
        Locator.scroll_into_view_if_needed = _humanized_scroll_into_view_if_needed


# ============================================================================
# Locator class-level patching (async)
# ============================================================================

_locator_async_patched = False


def _patch_locator_class_async():
    """Patch all async Locator interaction methods to go through humanized page methods."""
    global _locator_async_patched
    if _locator_async_patched:
        return
    _locator_async_patched = True

    from playwright.async_api._generated import Locator as AsyncLocator

    _orig_fill = AsyncLocator.fill
    _orig_click = AsyncLocator.click
    _orig_type = AsyncLocator.type
    _orig_dblclick = AsyncLocator.dblclick
    _orig_hover = AsyncLocator.hover
    _orig_check = AsyncLocator.check
    _orig_uncheck = AsyncLocator.uncheck
    _orig_set_checked = AsyncLocator.set_checked
    _orig_select_option = AsyncLocator.select_option
    _orig_press = AsyncLocator.press
    _orig_press_sequentially = AsyncLocator.press_sequentially
    _orig_tap = AsyncLocator.tap
    _orig_drag_to = AsyncLocator.drag_to
    _orig_clear = AsyncLocator.clear
    _orig_scroll_into_view = getattr(AsyncLocator, 'scroll_into_view_if_needed', None)

    def _get_selector(self):
        return self._impl_obj._selector

    def _is_humanized(self):
        return hasattr(self.page, '_original')

    def _get_cfg(self):
        return getattr(self.page, '_human_cfg', None)

    def _forward_kwargs(kwargs):
        out = {}
        if "timeout" in kwargs:
            out["timeout"] = kwargs["timeout"]
        if "human_config" in kwargs:
            out["human_config"] = kwargs["human_config"]
        return out

    async def _humanized_fill(self, value, **kwargs):
        if _is_humanized(self):
            await self.page.fill(_get_selector(self), value, **_forward_kwargs(kwargs))
        else:
            await _orig_fill(self, value, **kwargs)

    async def _humanized_click(self, **kwargs):
        if _is_humanized(self):
            await self.page.click(_get_selector(self), **_forward_kwargs(kwargs))
        else:
            await _orig_click(self, **kwargs)

    async def _humanized_type(self, text, **kwargs):
        if _is_humanized(self):
            await self.page.type(_get_selector(self), text, **_forward_kwargs(kwargs))
        else:
            await _orig_type(self, text, **kwargs)

    async def _humanized_dblclick(self, **kwargs):
        if _is_humanized(self):
            await self.page.dblclick(_get_selector(self), **_forward_kwargs(kwargs))
        else:
            await _orig_dblclick(self, **kwargs)

    async def _humanized_hover(self, **kwargs):
        if _is_humanized(self):
            await self.page.hover(_get_selector(self), **_forward_kwargs(kwargs))
        else:
            await _orig_hover(self, **kwargs)

    async def _humanized_scroll_into_view_if_needed(self, **kwargs):
        if _is_humanized(self):
            page = self.page
            cfg = _get_cfg(self)
            cursor = getattr(page, '_human_cursor', None)
            raw = getattr(page, '_human_raw_mouse', None)
            call_cfg = merge_config(cfg, kwargs.get("human_config")) if cfg else None
            if call_cfg is None or cursor is None or raw is None:
                if _orig_scroll_into_view is not None:
                    native_kwargs = {k: v for k, v in kwargs.items() if k != "human_config"}
                    await _orig_scroll_into_view(self, **native_kwargs)
                return
            timeout = kwargs.get("timeout", 30000)

            async def _get_box():
                return await self.bounding_box(timeout=timeout)
            try:
                _, nx, ny = await async_human_scroll_into_view(
                    page, raw, _get_box,
                    cursor.x, cursor.y, call_cfg,
                )
                cursor.x = nx
                cursor.y = ny
            except Exception:
                if _orig_scroll_into_view is not None:
                    native_kwargs = {k: v for k, v in kwargs.items() if k != "human_config"}
                    await _orig_scroll_into_view(self, **native_kwargs)
        elif _orig_scroll_into_view is not None:
            await _orig_scroll_into_view(self, **kwargs)

    async def _humanized_check(self, **kwargs):
        if _is_humanized(self):
            cfg = _get_cfg(self)
            if cfg and cfg.idle_between_actions:
                raw = type("_R", (), {"move": self.page._original.mouse_move})()
                await async_human_idle(
                    raw,
                    rand(cfg.idle_between_duration[0], cfg.idle_between_duration[1]),
                    0, 0, cfg,
                )
            checked = await self.is_checked()
            if not checked:
                await self.page.click(_get_selector(self))
        else:
            await _orig_check(self, **kwargs)

    async def _humanized_uncheck(self, **kwargs):
        if _is_humanized(self):
            cfg = _get_cfg(self)
            if cfg and cfg.idle_between_actions:
                raw = type("_R", (), {"move": self.page._original.mouse_move})()
                await async_human_idle(
                    raw,
                    rand(cfg.idle_between_duration[0], cfg.idle_between_duration[1]),
                    0, 0, cfg,
                )
            checked = await self.is_checked()
            if checked:
                await self.page.click(_get_selector(self))
        else:
            await _orig_uncheck(self, **kwargs)

    async def _humanized_set_checked(self, checked, **kwargs):
        if _is_humanized(self):
            current = await self.is_checked()
            if current != checked:
                await self.page.click(_get_selector(self))
        else:
            await _orig_set_checked(self, checked, **kwargs)

    async def _humanized_select_option(self, value=None, **kwargs):
        if _is_humanized(self):
            selector = _get_selector(self)
            await self.page.hover(selector)
            await async_sleep_ms(rand(100, 300))
            await _orig_select_option(self, value, **kwargs)
        else:
            await _orig_select_option(self, value, **kwargs)

    async def _humanized_press(self, key, **kwargs):
        if _is_humanized(self):
            selector = _get_selector(self)
            if not await _async_is_selector_focused(self.page, selector):
                await self.page.click(selector)
            await async_sleep_ms(rand(50, 150))
            await self.page.keyboard.press(key)
        else:
            await _orig_press(self, key, **kwargs)

    async def _humanized_press_sequentially(self, text, **kwargs):
        if _is_humanized(self):
            selector = _get_selector(self)
            if not await _async_is_selector_focused(self.page, selector):
                await self.page.click(selector)
            await async_sleep_ms(rand(50, 150))
            await self.page.keyboard.type(text)
        else:
            await _orig_press_sequentially(self, text, **kwargs)

    async def _humanized_tap(self, **kwargs):
        if _is_humanized(self):
            await self.page.click(_get_selector(self))
        else:
            await _orig_tap(self, **kwargs)

    async def _humanized_drag_to(self, target, **kwargs):
        if _is_humanized(self):
            page = self.page
            originals = getattr(page, '_original', None)
            src_box = await self.bounding_box()
            tgt_box = await target.bounding_box()
            if src_box and tgt_box and originals:
                sx = src_box['x'] + src_box['width'] / 2
                sy = src_box['y'] + src_box['height'] / 2
                tx = tgt_box['x'] + tgt_box['width'] / 2
                ty = tgt_box['y'] + tgt_box['height'] / 2
                await page.mouse.move(sx, sy)
                await async_sleep_ms(rand(100, 200))
                await originals.mouse_down()
                await async_sleep_ms(rand(80, 150))
                await page.mouse.move(tx, ty)
                await async_sleep_ms(rand(80, 150))
                await originals.mouse_up()
            else:
                await _orig_drag_to(self, target, **kwargs)
        else:
            await _orig_drag_to(self, target, **kwargs)

    async def _humanized_clear(self, **kwargs):
        if _is_humanized(self):
            selector = _get_selector(self)
            if not await _async_is_selector_focused(self.page, selector):
                await self.page.click(selector)
            await async_sleep_ms(rand(50, 100))
            await self.page.keyboard.press(_SELECT_ALL)
            await async_sleep_ms(rand(30, 80))
            await self.page.keyboard.press("Backspace")
        else:
            await _orig_clear(self, **kwargs)

    AsyncLocator.fill = _humanized_fill
    AsyncLocator.click = _humanized_click
    AsyncLocator.type = _humanized_type
    AsyncLocator.dblclick = _humanized_dblclick
    AsyncLocator.hover = _humanized_hover
    AsyncLocator.check = _humanized_check
    AsyncLocator.uncheck = _humanized_uncheck
    AsyncLocator.set_checked = _humanized_set_checked
    AsyncLocator.select_option = _humanized_select_option
    AsyncLocator.press = _humanized_press
    AsyncLocator.press_sequentially = _humanized_press_sequentially
    AsyncLocator.tap = _humanized_tap
    AsyncLocator.drag_to = _humanized_drag_to
    AsyncLocator.clear = _humanized_clear
    if _orig_scroll_into_view is not None:
        AsyncLocator.scroll_into_view_if_needed = _humanized_scroll_into_view_if_needed


# ============================================================================
# SYNC patching
# ============================================================================


def patch_page(page: Any, cfg: HumanConfig, cursor: _CursorState) -> None:
    """Replace page methods with human-like implementations (sync)."""
    originals = type("Originals", (), {
        "click": page.click,
        "type": page.type,
        "fill": page.fill,
        "goto": page.goto,
        "hover": page.hover,
        "dblclick": page.dblclick,
        "mouse_move": page.mouse.move,
        "mouse_click": page.mouse.click,
        "mouse_wheel": page.mouse.wheel,
        "mouse_down": page.mouse.down,
        "mouse_up": page.mouse.up,
        "keyboard_type": page.keyboard.type,
        "keyboard_down": page.keyboard.down,
        "keyboard_up": page.keyboard.up,
        "keyboard_press": page.keyboard.press,
        "keyboard_insert_text": page.keyboard.insert_text,
    })()

    page._original = originals
    page._human_cfg = cfg
    page._human_cursor = cursor

    # --- Stealth infrastructure ---
    try:
        stealth = _SyncIsolatedWorld(page)
        page._stealth_world = stealth
        cdp_session = stealth.get_cdp_session()
    except Exception:
        stealth = None
        page._stealth_world = None
        cdp_session = None
        logger.debug("Could not create CDP session — stealth features disabled")

    raw_mouse: RawMouse = type("_RawMouse", (), {
        "move": originals.mouse_move,
        "down": originals.mouse_down,
        "up": originals.mouse_up,
        "wheel": originals.mouse_wheel,
    })()

    raw_keyboard: RawKeyboard = type("_RawKeyboard", (), {
        "down": originals.keyboard_down,
        "up": originals.keyboard_up,
        "type": originals.keyboard_type,
        "insert_text": originals.keyboard_insert_text,
    })()

    page._human_raw_mouse = raw_mouse

    def _ensure_cursor_init() -> None:
        if not cursor.initialized:
            cursor.x = rand(cfg.initial_cursor_x[0], cfg.initial_cursor_x[1])
            cursor.y = rand(cfg.initial_cursor_y[0], cfg.initial_cursor_y[1])
            originals.mouse_move(cursor.x, cursor.y)
            cursor.initialized = True

    def _human_goto(url: str, **kwargs: Any) -> Any:
        response = originals.goto(url, **kwargs)
        # Invalidate isolated world after navigation (context ID becomes stale)
        if stealth is not None:
            stealth.invalidate()
        return response

    def _human_click(selector: str, **kwargs: Any) -> None:
        _ensure_cursor_init()
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        timeout = kwargs.get("timeout", 30000)
        if call_cfg.idle_between_actions:
            human_idle(raw_mouse, rand(call_cfg.idle_between_duration[0], call_cfg.idle_between_duration[1]), cursor.x, cursor.y, call_cfg)
        box, cx, cy = scroll_to_element(
            page, raw_mouse, selector, cursor.x, cursor.y, call_cfg, timeout=timeout,
        )
        cursor.x = cx
        cursor.y = cy
        is_input = _is_input_element(page, selector)
        target = click_target(box, is_input, call_cfg)
        human_move(raw_mouse, cursor.x, cursor.y, target.x, target.y, call_cfg)
        cursor.x = target.x
        cursor.y = target.y
        human_click(raw_mouse, is_input, call_cfg)

    def _human_dblclick(selector: str, **kwargs: Any) -> None:
        _ensure_cursor_init()
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        timeout = kwargs.get("timeout", 30000)
        if call_cfg.idle_between_actions:
            human_idle(raw_mouse, rand(call_cfg.idle_between_duration[0], call_cfg.idle_between_duration[1]), cursor.x, cursor.y, call_cfg)
        box, cx, cy = scroll_to_element(
            page, raw_mouse, selector, cursor.x, cursor.y, call_cfg, timeout=timeout,
        )
        cursor.x = cx
        cursor.y = cy
        is_input = _is_input_element(page, selector)
        target = click_target(box, is_input, call_cfg)
        human_move(raw_mouse, cursor.x, cursor.y, target.x, target.y, call_cfg)
        cursor.x = target.x
        cursor.y = target.y
        raw_mouse.down(click_count=2)
        sleep_ms(rand(30, 60))
        raw_mouse.up(click_count=2)

    def _human_hover(selector: str, **kwargs: Any) -> None:
        _ensure_cursor_init()
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        timeout = kwargs.get("timeout", 30000)
        if call_cfg.idle_between_actions:
            human_idle(raw_mouse, rand(call_cfg.idle_between_duration[0], call_cfg.idle_between_duration[1]), cursor.x, cursor.y, call_cfg)
        box, cx, cy = scroll_to_element(
            page, raw_mouse, selector, cursor.x, cursor.y, call_cfg, timeout=timeout,
        )
        cursor.x = cx
        cursor.y = cy
        target = click_target(box, False, call_cfg)
        human_move(raw_mouse, cursor.x, cursor.y, target.x, target.y, call_cfg)
        cursor.x = target.x
        cursor.y = target.y

    def _human_type(selector: str, text: str, **kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        sleep_ms(rand_range(call_cfg.field_switch_delay))
        # Forward kwargs so timeout / human_config also propagate to the click
        # that focuses the field.
        _human_click(selector, **kwargs)
        sleep_ms(rand(100, 250))
        human_type(page, raw_keyboard, text, call_cfg, cdp_session=cdp_session)

    def _human_fill(selector: str, value: str, **kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        sleep_ms(rand_range(call_cfg.field_switch_delay))
        _human_click(selector, **kwargs)
        sleep_ms(rand(100, 250))
        originals.keyboard_press(_SELECT_ALL)
        sleep_ms(rand(30, 80))
        originals.keyboard_press("Backspace")
        sleep_ms(rand(50, 150))
        human_type(page, raw_keyboard, value, call_cfg, cdp_session=cdp_session)

    def _human_check(selector: str, **kwargs: Any) -> None:
        try:
            checked = page.is_checked(selector)
        except Exception:
            checked = False
        if not checked:
            _human_click(selector)

    def _human_uncheck(selector: str, **kwargs: Any) -> None:
        try:
            checked = page.is_checked(selector)
        except Exception:
            checked = True
        if checked:
            _human_click(selector)

    def _human_select_option(selector: str, value: Any = None, **kwargs: Any) -> Any:
        _human_hover(selector)
        sleep_ms(rand(100, 300))
        return originals.click(selector)

    def _human_press(selector: str, key: str, **kwargs: Any) -> None:
        if not _is_selector_focused(page, selector):
            _human_click(selector)
        sleep_ms(rand(50, 150))
        originals.keyboard_press(key)

    def _human_mouse_move(x: float, y: float, **kwargs: Any) -> None:
        _ensure_cursor_init()
        human_move(raw_mouse, cursor.x, cursor.y, x, y, cfg)
        cursor.x = x
        cursor.y = y

    def _human_mouse_click(x: float, y: float, **kwargs: Any) -> None:
        _ensure_cursor_init()
        human_move(raw_mouse, cursor.x, cursor.y, x, y, cfg)
        cursor.x = x
        cursor.y = y
        human_click(raw_mouse, False, cfg)

    def _human_keyboard_type(text: str, **kwargs: Any) -> None:
        human_type(page, raw_keyboard, text, cfg, cdp_session=cdp_session)

    page.goto = _human_goto
    page.click = _human_click
    page.dblclick = _human_dblclick
    page.hover = _human_hover
    page.type = _human_type
    page.fill = _human_fill
    page.check = _human_check
    page.uncheck = _human_uncheck
    page.press = _human_press
    page.mouse.move = _human_mouse_move
    page.mouse.click = _human_mouse_click
    page.keyboard.type = _human_keyboard_type
    # --- Patch Frame-level methods (for sub-frames) ---
    _patch_frames_sync(page, cfg, cursor, raw_mouse, raw_keyboard, originals)

    # --- Patch ElementHandle selectors (query_selector, query_selector_all, wait_for_selector) ---
    _patch_page_element_handles_sync(page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session)

    # Initialize cursor immediately so it doesn't visibly jump from (0,0)
    cursor.x = rand(cfg.initial_cursor_x[0], cfg.initial_cursor_x[1])
    cursor.y = rand(cfg.initial_cursor_y[0], cfg.initial_cursor_y[1])
    try:
        originals.mouse_move(cursor.x, cursor.y)
        cursor.initialized = True
    except Exception:
        pass

    # --- Patch Locator class (class-level, runs once) ---
    _patch_locator_class_sync()


# ============================================================================
# SYNC ElementHandle patching
# ============================================================================


def _is_input_element_handle_sync(el: Any) -> bool:
    """Check if an ElementHandle is an input/textarea/contenteditable (sync)."""
    try:
        return el.evaluate(
            """(node) => {
                const tag = node.tagName ? node.tagName.toLowerCase() : '';
                return tag === 'input' || tag === 'textarea'
                    || node.getAttribute && node.getAttribute('contenteditable') === 'true';
            }"""
        )
    except Exception:
        return False


def _patch_single_element_handle_sync(
    el: Any, page: Any, cfg: HumanConfig, cursor: _CursorState,
    raw_mouse: RawMouse, raw_keyboard: RawKeyboard, originals: Any,
    stealth: Any, cdp_session: Any,
) -> None:
    """Patch all interaction methods on a sync Playwright ElementHandle."""
    if getattr(el, '_human_patched', False):
        return
    el._human_patched = True

    # Save originals
    _orig_click = el.click
    _orig_dblclick = el.dblclick
    _orig_hover = el.hover
    _orig_type = el.type
    _orig_fill = el.fill
    _orig_press = el.press
    _orig_select_option = el.select_option
    _orig_check = el.check
    _orig_uncheck = el.uncheck
    _orig_set_checked = getattr(el, 'set_checked', None)
    _orig_tap = el.tap
    _orig_focus = el.focus
    _orig_scroll_into_view = getattr(el, 'scroll_into_view_if_needed', None)

    # Nested selectors
    _orig_qs = el.query_selector
    _orig_qsa = el.query_selector_all
    _orig_wfs = el.wait_for_selector

    def _patched_qs(selector: str, **kwargs: Any) -> Any:
        child = _orig_qs(selector, **kwargs)
        if child is not None:
            _patch_single_element_handle_sync(
                child, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session
            )
        return child

    def _patched_qsa(selector: str, **kwargs: Any) -> Any:
        children = _orig_qsa(selector, **kwargs)
        for child in children:
            _patch_single_element_handle_sync(
                child, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session
            )
        return children

    def _patched_wfs(selector: str, **kwargs: Any) -> Any:
        child = _orig_wfs(selector, **kwargs)
        if child is not None:
            _patch_single_element_handle_sync(
                child, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session
            )
        return child

    el.query_selector = _patched_qs
    el.query_selector_all = _patched_qsa
    el.wait_for_selector = _patched_wfs

    # Helper: move cursor to element. Accepts optional ``call_cfg`` so per-call
    # ``human_config`` overrides on type/fill carry through to mouse timing.
    # Also scrolls into view first so off-screen elements don't silently fall
    # back to the unpatched native method (#129, #172 follow-up).
    def _move_to_element(call_cfg: HumanConfig = cfg):
        if not cursor.initialized:
            cursor.x = rand(call_cfg.initial_cursor_x[0], call_cfg.initial_cursor_x[1])
            cursor.y = rand(call_cfg.initial_cursor_y[0], call_cfg.initial_cursor_y[1])
            originals.mouse_move(cursor.x, cursor.y)
            cursor.initialized = True

        # Scroll into view first — best-effort. If the element can't be located
        # we fall through to bounding_box() below which returns None and lets
        # the caller fall back to the original Playwright method.
        try:
            _, nx, ny = human_scroll_into_view(
                page, raw_mouse, lambda: el.bounding_box(),
                cursor.x, cursor.y, call_cfg,
            )
            cursor.x = nx
            cursor.y = ny
        except Exception:
            pass

        box = el.bounding_box()
        if not box:
            return None

        is_inp = _is_input_element_handle_sync(el)
        target = click_target(box, is_inp, call_cfg)

        if call_cfg.idle_between_actions:
            human_idle(raw_mouse, rand(call_cfg.idle_between_duration[0], call_cfg.idle_between_duration[1]), cursor.x, cursor.y, call_cfg)

        human_move(raw_mouse, cursor.x, cursor.y, target.x, target.y, call_cfg)
        cursor.x = target.x
        cursor.y = target.y
        return {'box': box, 'is_inp': is_inp}

    # --- el.click() ---
    def _human_el_click(**kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        info = _move_to_element(call_cfg)
        if info is None:
            return _orig_click(**kwargs)
        human_click(raw_mouse, info['is_inp'], call_cfg)

    # --- el.dblclick() ---
    def _human_el_dblclick(**kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        info = _move_to_element(call_cfg)
        if info is None:
            return _orig_dblclick(**kwargs)
        raw_mouse.down(click_count=2)
        sleep_ms(rand(30, 60))
        raw_mouse.up(click_count=2)

    # --- el.hover() ---
    def _human_el_hover(**kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        info = _move_to_element(call_cfg)
        if info is None:
            return _orig_hover(**kwargs)
        # Just move, no click

    # --- el.type() ---
    def _human_el_type(text: str, **kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        info = _move_to_element(call_cfg)
        if info is None:
            return _orig_type(text, **kwargs)
        human_click(raw_mouse, info['is_inp'], call_cfg)
        sleep_ms(rand(100, 250))
        human_type(page, raw_keyboard, text, call_cfg, cdp_session=cdp_session)

    # --- el.fill() ---
    def _human_el_fill(value: str, **kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        info = _move_to_element(call_cfg)
        if info is None:
            return _orig_fill(value, **kwargs)
        human_click(raw_mouse, info['is_inp'], call_cfg)
        sleep_ms(rand(100, 250))
        originals.keyboard_press(_SELECT_ALL)
        sleep_ms(rand(30, 80))
        originals.keyboard_press("Backspace")
        sleep_ms(rand(50, 150))
        human_type(page, raw_keyboard, value, call_cfg, cdp_session=cdp_session)

    # --- el.scroll_into_view_if_needed() ---
    # Playwright's native version snaps the page — a strong bot signal.
    # Replace with the same accelerate → cruise → decelerate → overshoot wheel
    # sequence used by page.click(). Falls back to the native method if the
    # element is detached or scrolling fails.
    def _human_el_scroll_into_view_if_needed(**kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        if not cursor.initialized:
            cursor.x = rand(call_cfg.initial_cursor_x[0], call_cfg.initial_cursor_x[1])
            cursor.y = rand(call_cfg.initial_cursor_y[0], call_cfg.initial_cursor_y[1])
            try:
                originals.mouse_move(cursor.x, cursor.y)
                cursor.initialized = True
            except Exception:
                pass
        try:
            _, nx, ny = human_scroll_into_view(
                page, raw_mouse, lambda: el.bounding_box(),
                cursor.x, cursor.y, call_cfg,
            )
            cursor.x = nx
            cursor.y = ny
        except Exception:
            if _orig_scroll_into_view is not None:
                native_kwargs = {k: v for k, v in kwargs.items() if k != "human_config"}
                _orig_scroll_into_view(**native_kwargs)

    # --- el.press() ---
    def _human_el_press(key: str, **kwargs: Any) -> None:
        sleep_ms(rand(20, 60))
        originals.keyboard_down(key)
        sleep_ms(rand_range(cfg.key_hold))
        originals.keyboard_up(key)

    # --- el.select_option() ---
    def _human_el_select_option(value: Any = None, **kwargs: Any) -> Any:
        info = _move_to_element()
        if info is None:
            return _orig_select_option(value, **kwargs)
        human_click(raw_mouse, False, cfg)
        sleep_ms(rand(100, 300))
        return _orig_select_option(value, **kwargs)

    # --- el.check() ---
    def _human_el_check(**kwargs: Any) -> None:
        try:
            if el.is_checked():
                return
        except Exception:
            pass
        info = _move_to_element()
        if info is None:
            return _orig_check(**kwargs)
        human_click(raw_mouse, info['is_inp'], cfg)

    # --- el.uncheck() ---
    def _human_el_uncheck(**kwargs: Any) -> None:
        try:
            if not el.is_checked():
                return
        except Exception:
            pass
        info = _move_to_element()
        if info is None:
            return _orig_uncheck(**kwargs)
        human_click(raw_mouse, info['is_inp'], cfg)

    # --- el.set_checked() ---
    def _human_el_set_checked(checked: bool, **kwargs: Any) -> None:
        try:
            current = el.is_checked()
            if current == checked:
                return
        except Exception:
            pass
        info = _move_to_element()
        if info is None and _orig_set_checked:
            return _orig_set_checked(checked, **kwargs)
        if info:
            human_click(raw_mouse, info['is_inp'], cfg)

    # --- el.tap() ---
    def _human_el_tap(**kwargs: Any) -> None:
        info = _move_to_element()
        if info is None:
            return _orig_tap(**kwargs)
        human_click(raw_mouse, info['is_inp'], cfg)

    # --- el.focus() ---
    # FIX: move cursor humanly but use programmatic focus (no click side-effects).
    # Stock Playwright el.focus() never clicks — it just calls element.focus() in JS.
    # Clicking would trigger onclick, submit forms, navigate links, etc.
    def _human_el_focus() -> None:
        _move_to_element()  # human-like cursor movement (Bézier)
        _orig_focus()       # programmatic focus, no click side-effects

    el.click = _human_el_click
    el.dblclick = _human_el_dblclick
    el.hover = _human_el_hover
    el.type = _human_el_type
    el.fill = _human_el_fill
    el.press = _human_el_press
    el.select_option = _human_el_select_option
    el.check = _human_el_check
    el.uncheck = _human_el_uncheck
    if _orig_set_checked is not None:
        el.set_checked = _human_el_set_checked
    el.tap = _human_el_tap
    el.focus = _human_el_focus
    if _orig_scroll_into_view is not None:
        el.scroll_into_view_if_needed = _human_el_scroll_into_view_if_needed


def _patch_page_element_handles_sync(
    page: Any, cfg: HumanConfig, cursor: _CursorState,
    raw_mouse: RawMouse, raw_keyboard: RawKeyboard, originals: Any,
    stealth: Any, cdp_session: Any,
) -> None:
    """Patch page.query_selector, query_selector_all, wait_for_selector to return humanized ElementHandles (sync)."""
    _orig_qs = page.query_selector
    _orig_qsa = page.query_selector_all
    _orig_wfs = page.wait_for_selector

    def _patched_qs(selector: str, **kwargs: Any) -> Any:
        el = _orig_qs(selector, **kwargs)
        if el is not None:
            _patch_single_element_handle_sync(
                el, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session
            )
        return el

    def _patched_qsa(selector: str, **kwargs: Any) -> Any:
        els = _orig_qsa(selector, **kwargs)
        for el in els:
            _patch_single_element_handle_sync(
                el, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session
            )
        return els

    def _patched_wfs(selector: str, **kwargs: Any) -> Any:
        el = _orig_wfs(selector, **kwargs)
        if el is not None:
            _patch_single_element_handle_sync(
                el, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session
            )
        return el

    page.query_selector = _patched_qs
    page.query_selector_all = _patched_qsa
    page.wait_for_selector = _patched_wfs


def _patch_frames_sync(
    page: Any, cfg: HumanConfig, cursor: _CursorState,
    raw_mouse: RawMouse, raw_keyboard: RawKeyboard, originals: Any,
) -> None:
    for frame in _iter_frames(page):
        _patch_single_frame_sync(frame, page, cfg, cursor, raw_mouse, raw_keyboard, originals)

    orig_main_frame = getattr(page, "_original_main_frame", None)
    if orig_main_frame is None:
        try:
            _orig_goto = originals.goto

            def _frame_aware_goto(url: str, **kwargs: Any) -> Any:
                response = _orig_goto(url, **kwargs)
                # Invalidate isolated world after navigation
                stealth_world = getattr(page, '_stealth_world', None)
                if stealth_world is not None:
                    stealth_world.invalidate()
                for frame in _iter_frames(page):
                    if not getattr(frame, "_human_patched", False):
                        _patch_single_frame_sync(frame, page, cfg, cursor, raw_mouse, raw_keyboard, originals)
                return response

            page.goto = _frame_aware_goto
            page._original_main_frame = True
        except Exception:
            pass


def _patch_single_frame_sync(
    frame: Any, page: Any, cfg: HumanConfig, cursor: _CursorState,
    raw_mouse: RawMouse, raw_keyboard: RawKeyboard, originals: Any,
) -> None:
    if getattr(frame, "_human_patched", False):
        return
    frame._human_patched = True

    _orig_frame_select_option = frame.select_option
    _orig_frame_drag_and_drop = getattr(frame, 'drag_and_drop', None)

    def _frame_click(selector: str, **kwargs: Any) -> None:
        page.click(selector)

    def _frame_dblclick(selector: str, **kwargs: Any) -> None:
        page.dblclick(selector)

    def _frame_hover(selector: str, **kwargs: Any) -> None:
        page.hover(selector)

    def _frame_type(selector: str, text: str, **kwargs: Any) -> None:
        page.type(selector, text)

    def _frame_fill(selector: str, value: str, **kwargs: Any) -> None:
        page.fill(selector, value)

    def _frame_check(selector: str, **kwargs: Any) -> None:
        page.check(selector)

    def _frame_uncheck(selector: str, **kwargs: Any) -> None:
        page.uncheck(selector)

    def _frame_select_option(selector: str, value: Any = None, **kwargs: Any) -> Any:
        page.hover(selector)
        sleep_ms(rand(100, 300))
        return _orig_frame_select_option(selector, value, **kwargs)

    def _frame_press(selector: str, key: str, **kwargs: Any) -> None:
        page.press(selector, key)

    def _frame_clear(selector: str, **kwargs: Any) -> None:
        if not _is_selector_focused(page, selector):
            page.click(selector)
        sleep_ms(rand(50, 100))
        originals.keyboard_press(_SELECT_ALL)
        sleep_ms(rand(30, 80))
        originals.keyboard_press("Backspace")

    def _frame_drag_and_drop(source: str, target: str, **kwargs: Any) -> None:
        try:
            src_box = frame.locator(source).bounding_box()
            tgt_box = frame.locator(target).bounding_box()
        except Exception:
            src_box = tgt_box = None
        if src_box and tgt_box:
            sx = src_box['x'] + src_box['width'] / 2
            sy = src_box['y'] + src_box['height'] / 2
            tx = tgt_box['x'] + tgt_box['width'] / 2
            ty = tgt_box['y'] + tgt_box['height'] / 2
            page.mouse.move(sx, sy)
            sleep_ms(rand(100, 200))
            originals.mouse_down()
            sleep_ms(rand(80, 150))
            page.mouse.move(tx, ty)
            sleep_ms(rand(80, 150))
            originals.mouse_up()
        elif _orig_frame_drag_and_drop:
            _orig_frame_drag_and_drop(source, target, **kwargs)

    frame.click = _frame_click
    frame.dblclick = _frame_dblclick
    frame.hover = _frame_hover
    frame.type = _frame_type
    frame.fill = _frame_fill
    frame.check = _frame_check
    frame.uncheck = _frame_uncheck
    frame.select_option = _frame_select_option
    frame.press = _frame_press
    frame.clear = _frame_clear
    frame.drag_and_drop = _frame_drag_and_drop

    # --- Patch frame-level ElementHandle selectors ---
    stealth_world = getattr(page, '_stealth_world', None)
    cdp_session = None
    if stealth_world is not None:
        try:
            cdp_session = stealth_world.get_cdp_session()
        except Exception:
            pass
    _patch_frame_element_handles_sync(
        frame, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth_world, cdp_session
    )


def _patch_frame_element_handles_sync(
    frame: Any, page: Any, cfg: HumanConfig, cursor: _CursorState,
    raw_mouse: RawMouse, raw_keyboard: RawKeyboard, originals: Any,
    stealth: Any, cdp_session: Any,
) -> None:
    """Patch frame.query_selector, query_selector_all, wait_for_selector (sync)."""
    _orig_qs = frame.query_selector
    _orig_qsa = frame.query_selector_all
    _orig_wfs = frame.wait_for_selector

    def _patched_qs(selector: str, **kwargs: Any) -> Any:
        el = _orig_qs(selector, **kwargs)
        if el is not None:
            _patch_single_element_handle_sync(
                el, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session
            )
        return el

    def _patched_qsa(selector: str, **kwargs: Any) -> Any:
        els = _orig_qsa(selector, **kwargs)
        for el in els:
            _patch_single_element_handle_sync(
                el, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session
            )
        return els

    def _patched_wfs(selector: str, **kwargs: Any) -> Any:
        el = _orig_wfs(selector, **kwargs)
        if el is not None:
            _patch_single_element_handle_sync(
                el, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session
            )
        return el

    frame.query_selector = _patched_qs
    frame.query_selector_all = _patched_qsa
    frame.wait_for_selector = _patched_wfs



def _iter_frames(page: Any):
    try:
        main = page.main_frame
        yield main
        for child in main.child_frames:
            yield child
    except Exception:
        pass


def patch_context(context: Any, cfg: HumanConfig) -> None:
    cursor = _CursorState()
    for page in context.pages:
        patch_page(page, cfg, cursor)
    context.on("page", lambda p: patch_page(p, cfg, _CursorState()) if not hasattr(p, '_original') else None)

    orig_new_page = context.new_page

    def _patched_new_page(**kwargs: Any) -> Any:
        page = orig_new_page(**kwargs)
        if not hasattr(page, '_original'):
            patch_page(page, cfg, _CursorState())
        return page

    context.new_page = _patched_new_page


def patch_browser(browser: Any, cfg: HumanConfig) -> None:
    for context in browser.contexts:
        patch_context(context, cfg)

    orig_new_context = browser.new_context

    def _patched_new_context(**kwargs: Any) -> Any:
        context = orig_new_context(**kwargs)
        patch_context(context, cfg)
        return context

    browser.new_context = _patched_new_context

    orig_new_page = browser.new_page

    def _patched_new_page(**kwargs: Any) -> Any:
        page = orig_new_page(**kwargs)
        if not hasattr(page, '_original'):
            patch_page(page, cfg, _CursorState())
        return page

    browser.new_page = _patched_new_page


# ============================================================================
# ASYNC patching
# ============================================================================


def patch_page_async(page: Any, cfg: HumanConfig, cursor: _CursorState) -> None:
    """Replace page methods with human-like implementations (async)."""
    originals = type("Originals", (), {
        "click": page.click,
        "type": page.type,
        "fill": page.fill,
        "goto": page.goto,
        "hover": page.hover,
        "dblclick": page.dblclick,
        "mouse_move": page.mouse.move,
        "mouse_click": page.mouse.click,
        "mouse_wheel": page.mouse.wheel,
        "mouse_down": page.mouse.down,
        "mouse_up": page.mouse.up,
        "keyboard_type": page.keyboard.type,
        "keyboard_down": page.keyboard.down,
        "keyboard_up": page.keyboard.up,
        "keyboard_press": page.keyboard.press,
        "keyboard_insert_text": page.keyboard.insert_text,
    })()

    page._original = originals
    page._human_cfg = cfg
    page._human_cursor = cursor

    # --- Stealth infrastructure (lazy-initialized, async) ---
    stealth = _AsyncIsolatedWorld(page)
    page._stealth_world = stealth
    cdp_session_holder: list[Any] = [None]  # mutable container for closure
    page._cdp_session_holder = cdp_session_holder  # expose for frame-level patching

    async def _ensure_cdp() -> Any:
        if cdp_session_holder[0] is None:
            try:
                cdp_session_holder[0] = await stealth.get_cdp_session()
            except Exception:
                logger.debug("Could not create async CDP session")
        return cdp_session_holder[0]

    raw_mouse: AsyncRawMouse = type("_AsyncRawMouse", (), {
        "move": originals.mouse_move,
        "down": originals.mouse_down,
        "up": originals.mouse_up,
        "wheel": originals.mouse_wheel,
    })()

    raw_keyboard: AsyncRawKeyboard = type("_AsyncRawKeyboard", (), {
        "down": originals.keyboard_down,
        "up": originals.keyboard_up,
        "type": originals.keyboard_type,
        "insert_text": originals.keyboard_insert_text,
    })()

    page._human_raw_mouse = raw_mouse

    async def _ensure_cursor_init() -> None:
        if not cursor.initialized:
            cursor.x = rand(cfg.initial_cursor_x[0], cfg.initial_cursor_x[1])
            cursor.y = rand(cfg.initial_cursor_y[0], cfg.initial_cursor_y[1])
            await originals.mouse_move(cursor.x, cursor.y)
            cursor.initialized = True

    async def _human_goto(url: str, **kwargs: Any) -> Any:
        response = await originals.goto(url, **kwargs)
        # Invalidate isolated world after navigation
        stealth.invalidate()
        return response

    async def _human_click(selector: str, **kwargs: Any) -> None:
        await _ensure_cursor_init()
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        timeout = kwargs.get("timeout", 30000)
        if call_cfg.idle_between_actions:
            await async_human_idle(raw_mouse, rand(call_cfg.idle_between_duration[0], call_cfg.idle_between_duration[1]), cursor.x, cursor.y, call_cfg)
        box, cx, cy = await async_scroll_to_element(
            page, raw_mouse, selector, cursor.x, cursor.y, call_cfg, timeout=timeout,
        )
        cursor.x = cx
        cursor.y = cy
        is_input = await _async_is_input_element(page, selector)
        target = click_target(box, is_input, call_cfg)
        await async_human_move(raw_mouse, cursor.x, cursor.y, target.x, target.y, call_cfg)
        cursor.x = target.x
        cursor.y = target.y
        await async_human_click(raw_mouse, is_input, call_cfg)

    async def _human_dblclick(selector: str, **kwargs: Any) -> None:
        await _ensure_cursor_init()
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        timeout = kwargs.get("timeout", 30000)
        if call_cfg.idle_between_actions:
            await async_human_idle(raw_mouse, rand(call_cfg.idle_between_duration[0], call_cfg.idle_between_duration[1]), cursor.x, cursor.y, call_cfg)
        box, cx, cy = await async_scroll_to_element(
            page, raw_mouse, selector, cursor.x, cursor.y, call_cfg, timeout=timeout,
        )
        cursor.x = cx
        cursor.y = cy
        is_input = await _async_is_input_element(page, selector)
        target = click_target(box, is_input, call_cfg)
        await async_human_move(raw_mouse, cursor.x, cursor.y, target.x, target.y, call_cfg)
        cursor.x = target.x
        cursor.y = target.y
        await raw_mouse.down(click_count=2)
        await async_sleep_ms(rand(30, 60))
        await raw_mouse.up(click_count=2)

    async def _human_hover(selector: str, **kwargs: Any) -> None:
        await _ensure_cursor_init()
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        timeout = kwargs.get("timeout", 30000)
        if call_cfg.idle_between_actions:
            await async_human_idle(raw_mouse, rand(call_cfg.idle_between_duration[0], call_cfg.idle_between_duration[1]), cursor.x, cursor.y, call_cfg)
        box, cx, cy = await async_scroll_to_element(
            page, raw_mouse, selector, cursor.x, cursor.y, call_cfg, timeout=timeout,
        )
        cursor.x = cx
        cursor.y = cy
        target = click_target(box, False, call_cfg)
        await async_human_move(raw_mouse, cursor.x, cursor.y, target.x, target.y, call_cfg)
        cursor.x = target.x
        cursor.y = target.y

    async def _human_type(selector: str, text: str, **kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        await async_sleep_ms(rand_range(call_cfg.field_switch_delay))
        await _human_click(selector, **kwargs)
        await async_sleep_ms(rand(100, 250))
        cdp = await _ensure_cdp()
        await async_human_type(page, raw_keyboard, text, call_cfg, cdp_session=cdp)

    async def _human_fill(selector: str, value: str, **kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        await async_sleep_ms(rand_range(call_cfg.field_switch_delay))
        await _human_click(selector, **kwargs)
        await async_sleep_ms(rand(100, 250))
        await originals.keyboard_press(_SELECT_ALL)
        await async_sleep_ms(rand(30, 80))
        await originals.keyboard_press("Backspace")
        await async_sleep_ms(rand(50, 150))
        cdp = await _ensure_cdp()
        await async_human_type(page, raw_keyboard, value, call_cfg, cdp_session=cdp)

    async def _human_check(selector: str, **kwargs: Any) -> None:
        try:
            checked = await page.is_checked(selector)
        except Exception:
            checked = False
        if not checked:
            await _human_click(selector)

    async def _human_uncheck(selector: str, **kwargs: Any) -> None:
        try:
            checked = await page.is_checked(selector)
        except Exception:
            checked = True
        if checked:
            await _human_click(selector)

    async def _human_press(selector: str, key: str, **kwargs: Any) -> None:
        if not await _async_is_selector_focused(page, selector):
            await _human_click(selector)
        await async_sleep_ms(rand(50, 150))
        await originals.keyboard_press(key)

    async def _human_mouse_move(x: float, y: float, **kwargs: Any) -> None:
        await _ensure_cursor_init()
        await async_human_move(raw_mouse, cursor.x, cursor.y, x, y, cfg)
        cursor.x = x
        cursor.y = y

    async def _human_mouse_click(x: float, y: float, **kwargs: Any) -> None:
        await _ensure_cursor_init()
        await async_human_move(raw_mouse, cursor.x, cursor.y, x, y, cfg)
        cursor.x = x
        cursor.y = y
        await async_human_click(raw_mouse, False, cfg)

    async def _human_keyboard_type(text: str, **kwargs: Any) -> None:
        cdp = await _ensure_cdp()
        await async_human_type(page, raw_keyboard, text, cfg, cdp_session=cdp)

    page.goto = _human_goto
    page.click = _human_click
    page.dblclick = _human_dblclick
    page.hover = _human_hover
    page.type = _human_type
    page.fill = _human_fill
    page.check = _human_check
    page.uncheck = _human_uncheck
    page.press = _human_press
    page.mouse.move = _human_mouse_move
    page.mouse.click = _human_mouse_click
    page.keyboard.type = _human_keyboard_type

    # --- Patch Frame-level methods (for sub-frames) ---
    _patch_frames_async(page, cfg, cursor, raw_mouse, raw_keyboard, originals)

    # --- Patch ElementHandle selectors (query_selector, query_selector_all, wait_for_selector) ---
    _patch_page_element_handles_async(page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session_holder)

    # --- Patch async Locator class (class-level, runs once) ---
    _patch_locator_class_async()


# ============================================================================
# ASYNC ElementHandle patching
# ============================================================================


async def _async_is_input_element_handle(el: Any) -> bool:
    """Check if an ElementHandle is an input/textarea/contenteditable (async)."""
    try:
        return await el.evaluate(
            """(node) => {
                const tag = node.tagName ? node.tagName.toLowerCase() : '';
                return tag === 'input' || tag === 'textarea'
                    || node.getAttribute && node.getAttribute('contenteditable') === 'true';
            }"""
        )
    except Exception:
        return False


def _patch_single_element_handle_async(
    el: Any, page: Any, cfg: HumanConfig, cursor: _CursorState,
    raw_mouse: AsyncRawMouse, raw_keyboard: AsyncRawKeyboard, originals: Any,
    stealth: Any, cdp_session_holder: Any,
) -> None:
    """Patch all interaction methods on an async Playwright ElementHandle."""
    if getattr(el, '_human_patched', False):
        return
    el._human_patched = True

    # Save originals
    _orig_click = el.click
    _orig_dblclick = el.dblclick
    _orig_hover = el.hover
    _orig_type = el.type
    _orig_fill = el.fill
    _orig_press = el.press
    _orig_select_option = el.select_option
    _orig_check = el.check
    _orig_uncheck = el.uncheck
    _orig_set_checked = getattr(el, 'set_checked', None)
    _orig_tap = el.tap
    _orig_focus = el.focus
    _orig_scroll_into_view = getattr(el, 'scroll_into_view_if_needed', None)

    # Nested selectors
    _orig_qs = el.query_selector
    _orig_qsa = el.query_selector_all
    _orig_wfs = el.wait_for_selector

    async def _patched_qs(selector: str, **kwargs: Any) -> Any:
        child = await _orig_qs(selector, **kwargs)
        if child is not None:
            _patch_single_element_handle_async(
                child, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session_holder
            )
        return child

    async def _patched_qsa(selector: str, **kwargs: Any) -> Any:
        children = await _orig_qsa(selector, **kwargs)
        for child in children:
            _patch_single_element_handle_async(
                child, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session_holder
            )
        return children

    async def _patched_wfs(selector: str, **kwargs: Any) -> Any:
        child = await _orig_wfs(selector, **kwargs)
        if child is not None:
            _patch_single_element_handle_async(
                child, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session_holder
            )
        return child

    el.query_selector = _patched_qs
    el.query_selector_all = _patched_qsa
    el.wait_for_selector = _patched_wfs

    # Helper: move cursor to element (async). Accepts optional ``call_cfg`` so
    # per-call ``human_config`` overrides on type/fill carry through to mouse
    # timing. Also scrolls into view first so off-screen elements work
    # (#129, #172 follow-up).
    async def _move_to_element(call_cfg: HumanConfig = cfg):
        if not cursor.initialized:
            cursor.x = rand(call_cfg.initial_cursor_x[0], call_cfg.initial_cursor_x[1])
            cursor.y = rand(call_cfg.initial_cursor_y[0], call_cfg.initial_cursor_y[1])
            await originals.mouse_move(cursor.x, cursor.y)
            cursor.initialized = True

        # Scroll into view first — best-effort.
        async def _get_box():
            return await el.bounding_box()
        try:
            _, nx, ny = await async_human_scroll_into_view(
                page, raw_mouse, _get_box,
                cursor.x, cursor.y, call_cfg,
            )
            cursor.x = nx
            cursor.y = ny
        except Exception:
            pass

        box = await el.bounding_box()
        if not box:
            return None

        is_inp = await _async_is_input_element_handle(el)
        target = click_target(box, is_inp, call_cfg)

        if call_cfg.idle_between_actions:
            await async_human_idle(raw_mouse, rand(call_cfg.idle_between_duration[0], call_cfg.idle_between_duration[1]), cursor.x, cursor.y, call_cfg)

        await async_human_move(raw_mouse, cursor.x, cursor.y, target.x, target.y, call_cfg)
        cursor.x = target.x
        cursor.y = target.y
        return {'box': box, 'is_inp': is_inp}

    async def _get_cdp():
        if cdp_session_holder[0] is None:
            try:
                cdp_session_holder[0] = await stealth.get_cdp_session()
            except Exception:
                pass
        return cdp_session_holder[0]

    # --- el.click() ---
    async def _human_el_click(**kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        info = await _move_to_element(call_cfg)
        if info is None:
            return await _orig_click(**kwargs)
        await async_human_click(raw_mouse, info['is_inp'], call_cfg)

    # --- el.dblclick() ---
    async def _human_el_dblclick(**kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        info = await _move_to_element(call_cfg)
        if info is None:
            return await _orig_dblclick(**kwargs)
        await raw_mouse.down(click_count=2)
        await async_sleep_ms(rand(30, 60))
        await raw_mouse.up(click_count=2)

    # --- el.hover() ---
    async def _human_el_hover(**kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        info = await _move_to_element(call_cfg)
        if info is None:
            return await _orig_hover(**kwargs)

    # --- el.type() ---
    async def _human_el_type(text: str, **kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        info = await _move_to_element(call_cfg)
        if info is None:
            return await _orig_type(text, **kwargs)
        await async_human_click(raw_mouse, info['is_inp'], call_cfg)
        await async_sleep_ms(rand(100, 250))
        cdp = await _get_cdp()
        await async_human_type(page, raw_keyboard, text, call_cfg, cdp_session=cdp)

    # --- el.fill() ---
    async def _human_el_fill(value: str, **kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        info = await _move_to_element(call_cfg)
        if info is None:
            return await _orig_fill(value, **kwargs)
        await async_human_click(raw_mouse, info['is_inp'], call_cfg)
        await async_sleep_ms(rand(100, 250))
        await originals.keyboard_press(_SELECT_ALL)
        await async_sleep_ms(rand(30, 80))
        await originals.keyboard_press("Backspace")
        await async_sleep_ms(rand(50, 150))
        cdp = await _get_cdp()
        await async_human_type(page, raw_keyboard, value, call_cfg, cdp_session=cdp)

    # --- el.scroll_into_view_if_needed() ---
    async def _human_el_scroll_into_view_if_needed(**kwargs: Any) -> None:
        call_cfg = merge_config(cfg, kwargs.get("human_config"))
        if not cursor.initialized:
            cursor.x = rand(call_cfg.initial_cursor_x[0], call_cfg.initial_cursor_x[1])
            cursor.y = rand(call_cfg.initial_cursor_y[0], call_cfg.initial_cursor_y[1])
            try:
                await originals.mouse_move(cursor.x, cursor.y)
                cursor.initialized = True
            except Exception:
                pass

        async def _get_box():
            return await el.bounding_box()
        try:
            _, nx, ny = await async_human_scroll_into_view(
                page, raw_mouse, _get_box,
                cursor.x, cursor.y, call_cfg,
            )
            cursor.x = nx
            cursor.y = ny
        except Exception:
            if _orig_scroll_into_view is not None:
                native_kwargs = {k: v for k, v in kwargs.items() if k != "human_config"}
                await _orig_scroll_into_view(**native_kwargs)

    # --- el.press() ---
    async def _human_el_press(key: str, **kwargs: Any) -> None:
        await async_sleep_ms(rand(20, 60))
        await originals.keyboard_down(key)
        await async_sleep_ms(rand_range(cfg.key_hold))
        await originals.keyboard_up(key)

    # --- el.select_option() ---
    async def _human_el_select_option(value: Any = None, **kwargs: Any) -> Any:
        info = await _move_to_element()
        if info is None:
            return await _orig_select_option(value, **kwargs)
        await async_human_click(raw_mouse, False, cfg)
        await async_sleep_ms(rand(100, 300))
        return await _orig_select_option(value, **kwargs)

    # --- el.check() ---
    async def _human_el_check(**kwargs: Any) -> None:
        try:
            if await el.is_checked():
                return
        except Exception:
            pass
        info = await _move_to_element()
        if info is None:
            return await _orig_check(**kwargs)
        await async_human_click(raw_mouse, info['is_inp'], cfg)

    # --- el.uncheck() ---
    async def _human_el_uncheck(**kwargs: Any) -> None:
        try:
            if not await el.is_checked():
                return
        except Exception:
            pass
        info = await _move_to_element()
        if info is None:
            return await _orig_uncheck(**kwargs)
        await async_human_click(raw_mouse, info['is_inp'], cfg)

    # --- el.set_checked() ---
    async def _human_el_set_checked(checked: bool, **kwargs: Any) -> None:
        try:
            current = await el.is_checked()
            if current == checked:
                return
        except Exception:
            pass
        info = await _move_to_element()
        if info is None and _orig_set_checked:
            return await _orig_set_checked(checked, **kwargs)
        if info:
            await async_human_click(raw_mouse, info['is_inp'], cfg)

    # --- el.tap() ---
    async def _human_el_tap(**kwargs: Any) -> None:
        info = await _move_to_element()
        if info is None:
            return await _orig_tap(**kwargs)
        await async_human_click(raw_mouse, info['is_inp'], cfg)

    # --- el.focus() ---
    # FIX: move cursor humanly but use programmatic focus (no click side-effects).
    # Stock Playwright el.focus() never clicks — it just calls element.focus() in JS.
    # Clicking would trigger onclick, submit forms, navigate links, etc.
    async def _human_el_focus() -> None:
        await _move_to_element()  # human-like cursor movement (Bézier)
        await _orig_focus()       # programmatic focus, no click side-effects

    el.click = _human_el_click
    el.dblclick = _human_el_dblclick
    el.hover = _human_el_hover
    el.type = _human_el_type
    el.fill = _human_el_fill
    el.press = _human_el_press
    el.select_option = _human_el_select_option
    el.check = _human_el_check
    el.uncheck = _human_el_uncheck
    if _orig_set_checked is not None:
        el.set_checked = _human_el_set_checked
    el.tap = _human_el_tap
    el.focus = _human_el_focus
    if _orig_scroll_into_view is not None:
        el.scroll_into_view_if_needed = _human_el_scroll_into_view_if_needed


def _patch_page_element_handles_async(
    page: Any, cfg: HumanConfig, cursor: _CursorState,
    raw_mouse: AsyncRawMouse, raw_keyboard: AsyncRawKeyboard, originals: Any,
    stealth: Any, cdp_session_holder: Any,
) -> None:
    """Patch page.query_selector, query_selector_all, wait_for_selector to return humanized ElementHandles (async)."""
    _orig_qs = page.query_selector
    _orig_qsa = page.query_selector_all
    _orig_wfs = page.wait_for_selector

    async def _patched_qs(selector: str, **kwargs: Any) -> Any:
        el = await _orig_qs(selector, **kwargs)
        if el is not None:
            _patch_single_element_handle_async(
                el, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session_holder
            )
        return el

    async def _patched_qsa(selector: str, **kwargs: Any) -> Any:
        els = await _orig_qsa(selector, **kwargs)
        for el in els:
            _patch_single_element_handle_async(
                el, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session_holder
            )
        return els

    async def _patched_wfs(selector: str, **kwargs: Any) -> Any:
        el = await _orig_wfs(selector, **kwargs)
        if el is not None:
            _patch_single_element_handle_async(
                el, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session_holder
            )
        return el

    page.query_selector = _patched_qs
    page.query_selector_all = _patched_qsa
    page.wait_for_selector = _patched_wfs


def _patch_frames_async(
    page: Any, cfg: HumanConfig, cursor: _CursorState,
    raw_mouse: AsyncRawMouse, raw_keyboard: AsyncRawKeyboard, originals: Any,
) -> None:
    for frame in _iter_frames(page):
        _patch_single_frame_async(frame, page, cfg, cursor, raw_mouse, raw_keyboard, originals)

    orig_main_frame = getattr(page, "_original_main_frame", None)
    if orig_main_frame is None:
        try:
            _orig_goto = originals.goto

            async def _frame_aware_goto(url: str, **kwargs: Any) -> Any:
                response = await _orig_goto(url, **kwargs)
                # Invalidate isolated world after navigation
                stealth_world = getattr(page, '_stealth_world', None)
                if stealth_world is not None:
                    stealth_world.invalidate()
                for frame in _iter_frames(page):
                    if not getattr(frame, "_human_patched", False):
                        _patch_single_frame_async(frame, page, cfg, cursor, raw_mouse, raw_keyboard, originals)
                return response

            page.goto = _frame_aware_goto
            page._original_main_frame = True
        except Exception:
            pass


def _patch_single_frame_async(
    frame: Any, page: Any, cfg: HumanConfig, cursor: _CursorState,
    raw_mouse: AsyncRawMouse, raw_keyboard: AsyncRawKeyboard, originals: Any,
) -> None:
    if getattr(frame, "_human_patched", False):
        return
    frame._human_patched = True

    _orig_frame_select_option = frame.select_option
    _orig_frame_drag_and_drop = getattr(frame, 'drag_and_drop', None)

    async def _frame_click(selector: str, **kwargs: Any) -> None:
        await page.click(selector)

    async def _frame_dblclick(selector: str, **kwargs: Any) -> None:
        await page.dblclick(selector)

    async def _frame_hover(selector: str, **kwargs: Any) -> None:
        await page.hover(selector)

    async def _frame_type(selector: str, text: str, **kwargs: Any) -> None:
        await page.type(selector, text)

    async def _frame_fill(selector: str, value: str, **kwargs: Any) -> None:
        await page.fill(selector, value)

    async def _frame_check(selector: str, **kwargs: Any) -> None:
        await page.check(selector)

    async def _frame_uncheck(selector: str, **kwargs: Any) -> None:
        await page.uncheck(selector)

    async def _frame_select_option(selector: str, value: Any = None, **kwargs: Any) -> Any:
        await page.hover(selector)
        await async_sleep_ms(rand(100, 300))
        return await _orig_frame_select_option(selector, value, **kwargs)

    async def _frame_press(selector: str, key: str, **kwargs: Any) -> None:
        await page.press(selector, key)

    async def _frame_clear(selector: str, **kwargs: Any) -> None:
        if not await _async_is_selector_focused(page, selector):
            await page.click(selector)
        await async_sleep_ms(rand(50, 100))
        await originals.keyboard_press(_SELECT_ALL)
        await async_sleep_ms(rand(30, 80))
        await originals.keyboard_press("Backspace")

    async def _frame_drag_and_drop(source: str, target: str, **kwargs: Any) -> None:
        try:
            src_box = await frame.locator(source).bounding_box()
            tgt_box = await frame.locator(target).bounding_box()
        except Exception:
            src_box = tgt_box = None
        if src_box and tgt_box:
            sx = src_box['x'] + src_box['width'] / 2
            sy = src_box['y'] + src_box['height'] / 2
            tx = tgt_box['x'] + tgt_box['width'] / 2
            ty = tgt_box['y'] + tgt_box['height'] / 2
            await page.mouse.move(sx, sy)
            await async_sleep_ms(rand(100, 200))
            await originals.mouse_down()
            await async_sleep_ms(rand(80, 150))
            await page.mouse.move(tx, ty)
            await async_sleep_ms(rand(80, 150))
            await originals.mouse_up()
        elif _orig_frame_drag_and_drop:
            await _orig_frame_drag_and_drop(source, target, **kwargs)

    frame.click = _frame_click
    frame.dblclick = _frame_dblclick
    frame.hover = _frame_hover
    frame.type = _frame_type
    frame.fill = _frame_fill
    frame.check = _frame_check
    frame.uncheck = _frame_uncheck
    frame.select_option = _frame_select_option
    frame.press = _frame_press
    frame.clear = _frame_clear
    frame.drag_and_drop = _frame_drag_and_drop

    # --- Patch frame-level ElementHandle selectors (async) ---
    stealth_world = getattr(page, '_stealth_world', None)
    cdp_session_holder = getattr(page, '_cdp_session_holder', [None])
    _patch_frame_element_handles_async(
        frame, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth_world, cdp_session_holder
    )


def _patch_frame_element_handles_async(
    frame: Any, page: Any, cfg: HumanConfig, cursor: _CursorState,
    raw_mouse: AsyncRawMouse, raw_keyboard: AsyncRawKeyboard, originals: Any,
    stealth: Any, cdp_session_holder: Any,
) -> None:
    """Patch frame.query_selector, query_selector_all, wait_for_selector (async)."""
    _orig_qs = frame.query_selector
    _orig_qsa = frame.query_selector_all
    _orig_wfs = frame.wait_for_selector

    async def _patched_qs(selector: str, **kwargs: Any) -> Any:
        el = await _orig_qs(selector, **kwargs)
        if el is not None:
            _patch_single_element_handle_async(
                el, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session_holder
            )
        return el

    async def _patched_qsa(selector: str, **kwargs: Any) -> Any:
        els = await _orig_qsa(selector, **kwargs)
        for el in els:
            _patch_single_element_handle_async(
                el, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session_holder
            )
        return els

    async def _patched_wfs(selector: str, **kwargs: Any) -> Any:
        el = await _orig_wfs(selector, **kwargs)
        if el is not None:
            _patch_single_element_handle_async(
                el, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, cdp_session_holder
            )
        return el

    frame.query_selector = _patched_qs
    frame.query_selector_all = _patched_qsa
    frame.wait_for_selector = _patched_wfs



def patch_context_async(context: Any, cfg: HumanConfig) -> None:
    cursor = _CursorState()
    for page in context.pages:
        patch_page_async(page, cfg, cursor)
    context.on("page", lambda p: patch_page_async(p, cfg, _CursorState()) if not hasattr(p, '_original') else None)

    orig_new_page = context.new_page

    async def _patched_new_page(**kwargs: Any) -> Any:
        page = await orig_new_page(**kwargs)
        if not hasattr(page, '_original'):
            patch_page_async(page, cfg, _CursorState())
        return page

    context.new_page = _patched_new_page


def patch_browser_async(browser: Any, cfg: HumanConfig) -> None:
    for context in browser.contexts:
        patch_context_async(context, cfg)

    orig_new_context = browser.new_context

    async def _patched_new_context(**kwargs: Any) -> Any:
        context = await orig_new_context(**kwargs)
        patch_context_async(context, cfg)
        return context

    browser.new_context = _patched_new_context

    orig_new_page = browser.new_page

    async def _patched_new_page(**kwargs: Any) -> Any:
        page = await orig_new_page(**kwargs)
        if not hasattr(page, '_original'):
            patch_page_async(page, cfg, _CursorState())
        return page

    browser.new_page = _patched_new_page
