"""Human-like behavioral layer for cloakbrowser.

Activated via humanize=True in launch() / launch_async().
Patches page methods to use Bezier mouse curves, realistic typing, and smooth scrolling.

Supports both sync and async Playwright APIs.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from .config import HumanConfig, HumanPreset, resolve_config
from .config import rand, rand_range, sleep_ms, async_sleep_ms
from .mouse import RawMouse, human_move, human_click, click_target, human_idle
from .keyboard import RawKeyboard, human_type
from .scroll import scroll_to_element
from .mouse_async import AsyncRawMouse, async_human_move, async_human_click, async_human_idle
from .keyboard_async import AsyncRawKeyboard, async_human_type
from .scroll_async import async_scroll_to_element

_SELECT_ALL = "Meta+a" if sys.platform == "darwin" else "Control+a"

__all__ = [
    "patch_browser", "patch_context", "patch_page",
    "patch_browser_async", "patch_context_async", "patch_page_async",
    "HumanConfig", "resolve_config",
    "human_move", "human_click", "click_target", "human_idle",
    "human_type", "scroll_to_element",
]

logger = logging.getLogger("cloakbrowser.human")

class _CursorState:
    __slots__ = ("x", "y", "initialized")

    def __init__(self) -> None:
        self.x: float = 0
        self.y: float = 0
        self.initialized: bool = False


def _is_input_element(page: Any, selector: str) -> bool:
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
    """Check if the element matching selector is currently focused."""
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
    """Check if the element matching selector is currently focused (async)."""
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

    def _get_selector(self):
        return self._impl_obj._selector

    def _is_humanized(self):
        return hasattr(self.page, '_original')

    def _get_cfg(self):
        return getattr(self.page, '_human_cfg', None)

    def _humanized_fill(self, value, **kwargs):
        if _is_humanized(self):
            self.page.fill(_get_selector(self), value)
        else:
            _orig_fill(self, value, **kwargs)

    def _humanized_click(self, **kwargs):
        if _is_humanized(self):
            self.page.click(_get_selector(self))
        else:
            _orig_click(self, **kwargs)

    def _humanized_type(self, text, **kwargs):
        if _is_humanized(self):
            self.page.type(_get_selector(self), text)
        else:
            _orig_type(self, text, **kwargs)

    def _humanized_dblclick(self, **kwargs):
        if _is_humanized(self):
            self.page.dblclick(_get_selector(self))
        else:
            _orig_dblclick(self, **kwargs)

    def _humanized_hover(self, **kwargs):
        if _is_humanized(self):
            self.page.hover(_get_selector(self))
        else:
            _orig_hover(self, **kwargs)

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
            # Only click if not already focused — avoids redundant mouse moves
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

    def _get_selector(self):
        return self._impl_obj._selector

    def _is_humanized(self):
        return hasattr(self.page, '_original')

    def _get_cfg(self):
        return getattr(self.page, '_human_cfg', None)

    async def _humanized_fill(self, value, **kwargs):
        if _is_humanized(self):
            await self.page.fill(_get_selector(self), value)
        else:
            await _orig_fill(self, value, **kwargs)

    async def _humanized_click(self, **kwargs):
        if _is_humanized(self):
            await self.page.click(_get_selector(self))
        else:
            await _orig_click(self, **kwargs)

    async def _humanized_type(self, text, **kwargs):
        if _is_humanized(self):
            await self.page.type(_get_selector(self), text)
        else:
            await _orig_type(self, text, **kwargs)

    async def _humanized_dblclick(self, **kwargs):
        if _is_humanized(self):
            await self.page.dblclick(_get_selector(self))
        else:
            await _orig_dblclick(self, **kwargs)

    async def _humanized_hover(self, **kwargs):
        if _is_humanized(self):
            await self.page.hover(_get_selector(self))
        else:
            await _orig_hover(self, **kwargs)

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

    def _ensure_cursor_init() -> None:
        if not cursor.initialized:
            cursor.x = rand(cfg.initial_cursor_x[0], cfg.initial_cursor_x[1])
            cursor.y = rand(cfg.initial_cursor_y[0], cfg.initial_cursor_y[1])
            originals.mouse_move(cursor.x, cursor.y)
            cursor.initialized = True

    def _human_goto(url: str, **kwargs: Any) -> Any:
        response = originals.goto(url, **kwargs)
        return response

    def _human_click(selector: str, **kwargs: Any) -> None:
        _ensure_cursor_init()
        if cfg.idle_between_actions:
            human_idle(raw_mouse, rand(cfg.idle_between_duration[0], cfg.idle_between_duration[1]), cursor.x, cursor.y, cfg)
        box, cx, cy = scroll_to_element(
            page, raw_mouse, selector, cursor.x, cursor.y, cfg
        )
        cursor.x = cx
        cursor.y = cy
        is_input = _is_input_element(page, selector)
        target = click_target(box, is_input, cfg)
        human_move(raw_mouse, cursor.x, cursor.y, target.x, target.y, cfg)
        cursor.x = target.x
        cursor.y = target.y
        human_click(raw_mouse, is_input, cfg)

    def _human_dblclick(selector: str, **kwargs: Any) -> None:
        _ensure_cursor_init()
        if cfg.idle_between_actions:
            human_idle(raw_mouse, rand(cfg.idle_between_duration[0], cfg.idle_between_duration[1]), cursor.x, cursor.y, cfg)
        box, cx, cy = scroll_to_element(
            page, raw_mouse, selector, cursor.x, cursor.y, cfg
        )
        cursor.x = cx
        cursor.y = cy
        is_input = _is_input_element(page, selector)
        target = click_target(box, is_input, cfg)
        human_move(raw_mouse, cursor.x, cursor.y, target.x, target.y, cfg)
        cursor.x = target.x
        cursor.y = target.y
        raw_mouse.down(click_count=2)
        sleep_ms(rand(30, 60))
        raw_mouse.up(click_count=2)

    def _human_hover(selector: str, **kwargs: Any) -> None:
        _ensure_cursor_init()
        if cfg.idle_between_actions:
            human_idle(raw_mouse, rand(cfg.idle_between_duration[0], cfg.idle_between_duration[1]), cursor.x, cursor.y, cfg)
        box, cx, cy = scroll_to_element(
            page, raw_mouse, selector, cursor.x, cursor.y, cfg
        )
        cursor.x = cx
        cursor.y = cy
        target = click_target(box, False, cfg)
        human_move(raw_mouse, cursor.x, cursor.y, target.x, target.y, cfg)
        cursor.x = target.x
        cursor.y = target.y

    def _human_type(selector: str, text: str, **kwargs: Any) -> None:
        sleep_ms(rand_range(cfg.field_switch_delay))
        _human_click(selector)
        sleep_ms(rand(100, 250))
        human_type(page, raw_keyboard, text, cfg)

    def _human_fill(selector: str, value: str, **kwargs: Any) -> None:
        sleep_ms(rand_range(cfg.field_switch_delay))
        _human_click(selector)
        sleep_ms(rand(100, 250))
        originals.keyboard_press(_SELECT_ALL)
        sleep_ms(rand(30, 80))
        originals.keyboard_press("Backspace")
        sleep_ms(rand(50, 150))
        human_type(page, raw_keyboard, value, cfg)

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
        human_type(page, raw_keyboard, text, cfg)

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

    # Save originals for methods that need fallback
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

    async def _ensure_cursor_init() -> None:
        if not cursor.initialized:
            cursor.x = rand(cfg.initial_cursor_x[0], cfg.initial_cursor_x[1])
            cursor.y = rand(cfg.initial_cursor_y[0], cfg.initial_cursor_y[1])
            await originals.mouse_move(cursor.x, cursor.y)
            cursor.initialized = True

    async def _human_goto(url: str, **kwargs: Any) -> Any:
        response = await originals.goto(url, **kwargs)
        return response

    async def _human_click(selector: str, **kwargs: Any) -> None:
        await _ensure_cursor_init()
        if cfg.idle_between_actions:
            await async_human_idle(raw_mouse, rand(cfg.idle_between_duration[0], cfg.idle_between_duration[1]), cursor.x, cursor.y, cfg)
        box, cx, cy = await async_scroll_to_element(
            page, raw_mouse, selector, cursor.x, cursor.y, cfg
        )
        cursor.x = cx
        cursor.y = cy
        is_input = await _async_is_input_element(page, selector)
        target = click_target(box, is_input, cfg)
        await async_human_move(raw_mouse, cursor.x, cursor.y, target.x, target.y, cfg)
        cursor.x = target.x
        cursor.y = target.y
        await async_human_click(raw_mouse, is_input, cfg)

    async def _human_dblclick(selector: str, **kwargs: Any) -> None:
        await _ensure_cursor_init()
        if cfg.idle_between_actions:
            await async_human_idle(raw_mouse, rand(cfg.idle_between_duration[0], cfg.idle_between_duration[1]), cursor.x, cursor.y, cfg)
        box, cx, cy = await async_scroll_to_element(
            page, raw_mouse, selector, cursor.x, cursor.y, cfg
        )
        cursor.x = cx
        cursor.y = cy
        is_input = await _async_is_input_element(page, selector)
        target = click_target(box, is_input, cfg)
        await async_human_move(raw_mouse, cursor.x, cursor.y, target.x, target.y, cfg)
        cursor.x = target.x
        cursor.y = target.y
        await raw_mouse.down(click_count=2)
        await async_sleep_ms(rand(30, 60))
        await raw_mouse.up(click_count=2)

    async def _human_hover(selector: str, **kwargs: Any) -> None:
        await _ensure_cursor_init()
        if cfg.idle_between_actions:
            await async_human_idle(raw_mouse, rand(cfg.idle_between_duration[0], cfg.idle_between_duration[1]), cursor.x, cursor.y, cfg)
        box, cx, cy = await async_scroll_to_element(
            page, raw_mouse, selector, cursor.x, cursor.y, cfg
        )
        cursor.x = cx
        cursor.y = cy
        target = click_target(box, False, cfg)
        await async_human_move(raw_mouse, cursor.x, cursor.y, target.x, target.y, cfg)
        cursor.x = target.x
        cursor.y = target.y

    async def _human_type(selector: str, text: str, **kwargs: Any) -> None:
        await async_sleep_ms(rand_range(cfg.field_switch_delay))
        await _human_click(selector)
        await async_sleep_ms(rand(100, 250))
        await async_human_type(page, raw_keyboard, text, cfg)

    async def _human_fill(selector: str, value: str, **kwargs: Any) -> None:
        await async_sleep_ms(rand_range(cfg.field_switch_delay))
        await _human_click(selector)
        await async_sleep_ms(rand(100, 250))
        await originals.keyboard_press(_SELECT_ALL)
        await async_sleep_ms(rand(30, 80))
        await originals.keyboard_press("Backspace")
        await async_sleep_ms(rand(50, 150))
        await async_human_type(page, raw_keyboard, value, cfg)

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
        await async_human_type(page, raw_keyboard, text, cfg)

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

    # --- Patch async Locator class (class-level, runs once) ---
    _patch_locator_class_async()


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
