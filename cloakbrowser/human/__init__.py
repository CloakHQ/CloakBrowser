"""Human-like behavioral layer for cloakbrowser.

Activated via humanize=True in launch() / launch_async().
Patches page methods to use Bezier mouse curves, realistic typing, and smooth scrolling.

Supports both sync and async Playwright APIs.
"""

from __future__ import annotations

import logging
from typing import Any

from .config import HumanConfig, HumanPreset, resolve_config
from .config import rand, rand_range, sleep_ms, async_sleep_ms
from .mouse import RawMouse, human_move, human_click, click_target, human_idle
from .keyboard import RawKeyboard, human_type
from .scroll import scroll_to_element
from .mouse_async import AsyncRawMouse, async_human_move, async_human_click, async_human_idle
from .keyboard_async import AsyncRawKeyboard, async_human_type
from .scroll_async import async_scroll_to_element

__all__ = [
    "patch_browser", "patch_context", "patch_page",
    "patch_browser_async", "patch_context_async", "patch_page_async",
    "HumanConfig", "resolve_config",
    "human_move", "human_click", "click_target", "human_idle",
    "human_type", "scroll_to_element",
]

logger = logging.getLogger("cloakbrowser.human")

_COALESCED_PATCH = """
(() => {
  if (window.__coalescedPatched) return;
  window.__coalescedPatched = true;
  const original = PointerEvent.prototype.getCoalescedEvents;
  PointerEvent.prototype.getCoalescedEvents = function() {
    const real = original.call(this);
    if (real.length <= 1) {
      const count = 1 + Math.floor(Math.random() * 3);
      const fake = [this];
      for (let i = 0; i < count; i++) {
        fake.push(new PointerEvent(this.type, {
          clientX: this.clientX + (Math.random() - 0.5) * 2,
          clientY: this.clientY + (Math.random() - 0.5) * 2,
          pointerId: this.pointerId,
          pointerType: this.pointerType,
          bubbles: false
        }));
      }
      return fake;
    }
    return real;
  };
})();
"""


def _inject_coalesced_patch(page: Any) -> None:
    try:
        page.evaluate(_COALESCED_PATCH)
    except Exception:
        pass


async def _async_inject_coalesced_patch(page: Any) -> None:
    try:
        await page.evaluate(_COALESCED_PATCH)
    except Exception:
        pass


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
        if cfg.patch_coalesced:
            _inject_coalesced_patch(page)
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

    def _human_type(selector: str, text: str, **kwargs: Any) -> None:
        sleep_ms(rand_range(cfg.field_switch_delay))
        _human_click(selector)
        sleep_ms(rand(100, 250))
        human_type(page, raw_keyboard, text, cfg)

    def _human_fill(selector: str, value: str, **kwargs: Any) -> None:
        """Intercept fill() -- redirect to humanized type() with field clearing."""
        sleep_ms(rand_range(cfg.field_switch_delay))
        _human_click(selector)
        sleep_ms(rand(100, 250))
        # Clear existing content (preserve fill() contract: clear then set)
        originals.keyboard_press("Control+a")
        sleep_ms(rand(30, 80))
        originals.keyboard_press("Backspace")
        sleep_ms(rand(50, 150))
        human_type(page, raw_keyboard, value, cfg)

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
    page.type = _human_type
    page.fill = _human_fill
    page.mouse.move = _human_mouse_move
    page.mouse.click = _human_mouse_click
    page.keyboard.type = _human_keyboard_type

    # --- Fix #3: Patch Locator API (Frame-level methods) ---
    _patch_frames_sync(page, cfg, cursor, raw_mouse, raw_keyboard, originals)


def _patch_frames_sync(
    page: Any, cfg: HumanConfig, cursor: _CursorState,
    raw_mouse: RawMouse, raw_keyboard: RawKeyboard, originals: Any,
) -> None:
    """Patch Frame.click/type/fill so Locator-based calls use humanization."""
    for frame in _iter_frames(page):
        _patch_single_frame_sync(frame, page, cfg, cursor, raw_mouse, raw_keyboard, originals)

    # Also patch frames created later via page navigation
    orig_main_frame = getattr(page, "_original_main_frame", None)
    if orig_main_frame is None:
        try:
            _orig_goto = originals.goto

            def _frame_aware_goto(url: str, **kwargs: Any) -> Any:
                response = _orig_goto(url, **kwargs)
                if cfg.patch_coalesced:
                    _inject_coalesced_patch(page)
                # Re-patch all frames after navigation
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
    """Patch a single Frame object's click/type/fill for sync humanization."""
    if getattr(frame, "_human_patched", False):
        return
    frame._human_patched = True

    orig_frame_click = frame.click
    orig_frame_type = frame.type
    orig_frame_fill = frame.fill

    def _frame_click(selector: str, **kwargs: Any) -> None:
        # Delegate to page-level human click (which handles cursor, scroll, etc.)
        page.click(selector, **kwargs)

    def _frame_type(selector: str, text: str, **kwargs: Any) -> None:
        page.type(selector, text, **kwargs)

    def _frame_fill(selector: str, value: str, **kwargs: Any) -> None:
        page.fill(selector, value, **kwargs)

    frame.click = _frame_click
    frame.type = _frame_type
    frame.fill = _frame_fill


def _iter_frames(page: Any):
    """Yield all frames from a page (main_frame + child frames)."""
    try:
        main = page.main_frame
        yield main
        for child in main.child_frames:
            yield child
    except Exception:
        pass


def patch_context(context: Any, cfg: HumanConfig) -> None:
    """Patch all existing and future pages in a context (sync)."""
    cursor = _CursorState()
    for page in context.pages:
        patch_page(page, cfg, cursor)
    context.on("page", lambda p: patch_page(p, cfg, cursor))


def patch_browser(browser: Any, cfg: HumanConfig) -> None:
    """Patch browser: all contexts, new_context, and new_page (sync)."""
    for context in browser.contexts:
        patch_context(context, cfg)

    orig_new_context = browser.new_context

    def _patched_new_context(**kwargs: Any) -> Any:
        context = orig_new_context(**kwargs)
        patch_context(context, cfg)
        return context

    browser.new_context = _patched_new_context

    def _patched_new_page(**kwargs: Any) -> Any:
        context = browser.new_context(**kwargs)
        page = context.new_page()
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
        if cfg.patch_coalesced:
            await _async_inject_coalesced_patch(page)
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

    async def _human_type(selector: str, text: str, **kwargs: Any) -> None:
        await async_sleep_ms(rand_range(cfg.field_switch_delay))
        await _human_click(selector)
        await async_sleep_ms(rand(100, 250))
        await async_human_type(page, raw_keyboard, text, cfg)

    async def _human_fill(selector: str, value: str, **kwargs: Any) -> None:
        """Intercept fill() -- redirect to humanized type() with field clearing."""
        await async_sleep_ms(rand_range(cfg.field_switch_delay))
        await _human_click(selector)
        await async_sleep_ms(rand(100, 250))
        # Clear existing content (preserve fill() contract: clear then set)
        await originals.keyboard_press("Control+a")
        await async_sleep_ms(rand(30, 80))
        await originals.keyboard_press("Backspace")
        await async_sleep_ms(rand(50, 150))
        await async_human_type(page, raw_keyboard, value, cfg)

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
    page.type = _human_type
    page.fill = _human_fill
    page.mouse.move = _human_mouse_move
    page.mouse.click = _human_mouse_click
    page.keyboard.type = _human_keyboard_type

    # --- Fix #3: Patch Locator API (Frame-level methods) ---
    _patch_frames_async(page, cfg, cursor, raw_mouse, raw_keyboard, originals)


def _patch_frames_async(
    page: Any, cfg: HumanConfig, cursor: _CursorState,
    raw_mouse: AsyncRawMouse, raw_keyboard: AsyncRawKeyboard, originals: Any,
) -> None:
    """Patch Frame.click/type/fill so Locator-based calls use humanization (async)."""
    for frame in _iter_frames(page):
        _patch_single_frame_async(frame, page, cfg, cursor, raw_mouse, raw_keyboard, originals)

    # Also patch frames created later via page navigation
    orig_main_frame = getattr(page, "_original_main_frame", None)
    if orig_main_frame is None:
        try:
            _orig_goto = originals.goto

            async def _frame_aware_goto(url: str, **kwargs: Any) -> Any:
                response = await _orig_goto(url, **kwargs)
                if cfg.patch_coalesced:
                    await _async_inject_coalesced_patch(page)
                # Re-patch all frames after navigation
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
    """Patch a single Frame object's click/type/fill for async humanization."""
    if getattr(frame, "_human_patched", False):
        return
    frame._human_patched = True

    orig_frame_click = frame.click
    orig_frame_type = frame.type
    orig_frame_fill = frame.fill

    async def _frame_click(selector: str, **kwargs: Any) -> None:
        await page.click(selector, **kwargs)

    async def _frame_type(selector: str, text: str, **kwargs: Any) -> None:
        await page.type(selector, text, **kwargs)

    async def _frame_fill(selector: str, value: str, **kwargs: Any) -> None:
        await page.fill(selector, value, **kwargs)

    frame.click = _frame_click
    frame.type = _frame_type
    frame.fill = _frame_fill


def patch_context_async(context: Any, cfg: HumanConfig) -> None:
    """Patch all existing and future pages in a context (async)."""
    cursor = _CursorState()
    for page in context.pages:
        patch_page_async(page, cfg, cursor)
    context.on("page", lambda p: patch_page_async(p, cfg, cursor))


def patch_browser_async(browser: Any, cfg: HumanConfig) -> None:
    """Patch browser: all contexts, new_context, and new_page (async)."""
    for context in browser.contexts:
        patch_context_async(context, cfg)

    orig_new_context = browser.new_context

    async def _patched_new_context(**kwargs: Any) -> Any:
        context = await orig_new_context(**kwargs)
        patch_context_async(context, cfg)
        return context

    browser.new_context = _patched_new_context

    async def _patched_new_page(**kwargs: Any) -> Any:
        context = await browser.new_context(**kwargs)
        page = await context.new_page()
        return page

    browser.new_page = _patched_new_page
