"""Wire the humanize engine into Playwright's sync and async APIs.

Patching is class-level and idempotent: Page, Frame, Locator, ElementHandle,
Mouse and Keyboard methods check whether their page was humanized
(``patch_page`` / ``patch_page_async``) and otherwise call the original
Playwright method.  Every humanized method:

* accepts exactly the arguments the original accepts (validated against the
  original signature, so typos still raise ``TypeError``) plus
  ``human_config`` for per-call overrides;
* honours Playwright's semantics for the options it accepts (``button``,
  ``click_count``, ``modifiers``, ``position``, ``trial``, ``force``,
  ``timeout`` including page defaults and ``0`` = no limit, ``strict``);
* raises Playwright ``Error`` / ``TimeoutError`` instead of silently falling
  back to Playwright's stock implementation.
"""

from __future__ import annotations

import datetime
import functools
import inspect
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from .config import HumanConfig, rand
from .engine import CursorState, Human, Target

_PATCHED = {"sync": False, "async": False}
# (class, method name) -> original function
_ORIG: Dict[Tuple[type, str], Callable[..., Any]] = {}

Handler = Callable[[Human, Any, Dict[str, Any]], Awaitable[Any]]


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _impl_page(kind: str, impl: Any) -> Any:
    if kind == "Page":
        return impl
    if kind == "Frame":
        return impl._page
    if kind in ("Locator", "ElementHandle"):
        return impl._frame._page
    if kind in ("Mouse", "Keyboard"):
        return impl._channel._object
    return None  # pragma: no cover


def _human_for(kind: str, wrapper: Any) -> Optional[Human]:
    # No try/except: on a supported Playwright the internals below always exist
    # (checked once in _check_playwright). Swallowing an AttributeError here would
    # silently run Playwright's stock action on a humanized page.
    page = _impl_page(kind, wrapper._impl_obj)
    return getattr(page, "_cloak_human", None) if page is not None else None


# Oldest Playwright whose client internals the engine relies on
# (Frame._timeout, ElementHandle._frame; both added in 1.53).
MIN_PLAYWRIGHT = (1, 53)


def _check_playwright() -> None:
    """Fail loudly on a Playwright the engine cannot drive, instead of letting a
    humanized page fall back to Playwright's stock actions."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        installed = version("playwright")
    except PackageNotFoundError:  # pragma: no cover - vendored / editable installs
        installed = "unknown"
    parts = tuple(int(x) for x in installed.split(".")[:2] if x.isdigit())
    from playwright._impl._element_handle import ElementHandle
    from playwright._impl._frame import Frame

    missing = [n for n, ok in (("Frame._timeout", hasattr(Frame, "_timeout")),
                               ("ElementHandle._frame", "_frame" in ElementHandle.__init__.__code__.co_names))
               if not ok]
    if (len(parts) == 2 and parts < MIN_PLAYWRIGHT) or missing:
        raise RuntimeError(
            f"cloakbrowser humanize requires playwright>={'.'.join(map(str, MIN_PLAYWRIGHT))} "
            f"(installed: {installed}"
            + (f"; missing internals: {', '.join(missing)}" if missing else "")
            + "). Upgrade with: pip install -U playwright"
        )


def _normalize(args: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in args.items():
        if k == "kwargs":
            continue
        if isinstance(v, datetime.timedelta):
            v = v.total_seconds() * 1000.0
        out[k] = v
    return out


def _impl(obj: Any) -> Any:
    return getattr(obj, "_impl_obj", obj)


def _select_options(a: Dict[str, Any]) -> Tuple[List[dict], List[Any]]:
    options: List[dict] = []
    value, index, label, element = a.get("value"), a.get("index"), a.get("label"), a.get("element")
    if value is not None:
        options += [{"valueOrLabel": v} for v in ([value] if isinstance(value, str) else value)]
    if index is not None:
        options += [{"index": i} for i in ([index] if isinstance(index, int) else index)]
    if label is not None:
        options += [{"label": v} for v in ([label] if isinstance(label, str) else label)]
    elements: List[Any] = []
    if element is not None:
        elements = [_impl(e) for e in (element if isinstance(element, (list, tuple)) else [element])]
    return options, elements


# ---------------------------------------------------------------------------
# targets
# ---------------------------------------------------------------------------

def _selector_target(kind: str, impl: Any, a: Dict[str, Any], key: str = "selector") -> Target:
    frame = impl.main_frame if kind == "Page" else impl
    return Target(frame, a.pop(key), strict=bool(a.get("strict")))


def _locator_target(impl: Any) -> Target:
    return Target(impl._frame, impl._selector, strict=True)


def _handle_target(impl: Any) -> Target:
    return Target(impl._frame, handle=impl)


def _target(kind: str, impl: Any, a: Dict[str, Any]) -> Target:
    if kind in ("Page", "Frame"):
        return _selector_target(kind, impl, a)
    if kind == "Locator":
        return _locator_target(impl)
    return _handle_target(impl)


# ---------------------------------------------------------------------------
# handlers: (human, impl, args) -> awaitable
# ---------------------------------------------------------------------------

def _handlers(kind: str) -> Dict[str, Handler]:
    api = kind

    async def click(h: Human, impl: Any, a: dict) -> None:
        await h.click(_target(kind, impl, a), a, api=f"{api}.click")

    async def dblclick(h: Human, impl: Any, a: dict) -> None:
        await h.click(_target(kind, impl, a), a, api=f"{api}.dblclick", click_count=2)

    async def hover(h: Human, impl: Any, a: dict) -> None:
        await h.hover(_target(kind, impl, a), a, api=f"{api}.hover")

    async def tap(h: Human, impl: Any, a: dict) -> None:
        await h.click(_target(kind, impl, a), {**a, "click_count": 1}, api=f"{api}.tap")

    async def fill(h: Human, impl: Any, a: dict) -> None:
        t = _target(kind, impl, a)
        await h.fill(t, a.pop("value"), a, api=f"{api}.fill")

    async def clear(h: Human, impl: Any, a: dict) -> None:
        await h.fill(_target(kind, impl, a), "", a, api=f"{api}.clear")

    async def type_(h: Human, impl: Any, a: dict) -> None:
        t = _target(kind, impl, a)
        await h.type(t, a.pop("text"), a, api=f"{api}.type")

    async def press_sequentially(h: Human, impl: Any, a: dict) -> None:
        t = _target(kind, impl, a)
        await h.type(t, a.pop("text"), a, api=f"{api}.press_sequentially")

    async def press(h: Human, impl: Any, a: dict) -> None:
        t = _target(kind, impl, a)
        await h.press(t, a.pop("key"), a, api=f"{api}.press")

    async def check(h: Human, impl: Any, a: dict) -> None:
        await h.set_checked(_target(kind, impl, a), True, a, api=f"{api}.check")

    async def uncheck(h: Human, impl: Any, a: dict) -> None:
        await h.set_checked(_target(kind, impl, a), False, a, api=f"{api}.uncheck")

    async def set_checked(h: Human, impl: Any, a: dict) -> None:
        t = _target(kind, impl, a)
        await h.set_checked(t, bool(a.pop("checked")), a, api=f"{api}.set_checked")

    async def select_option(h: Human, impl: Any, a: dict) -> List[str]:
        t = _target(kind, impl, a)
        options, elements = _select_options(a)
        return await h.select_option(t, options, elements, a, api=f"{api}.select_option")

    async def focus(h: Human, impl: Any, a: dict) -> None:
        await h.focus(_target(kind, impl, a), a, api=f"{api}.focus", move=kind == "ElementHandle")

    async def scroll_into_view_if_needed(h: Human, impl: Any, a: dict) -> None:
        await h.scroll_into_view_if_needed(_target(kind, impl, a), a)

    async def drag_and_drop(h: Human, impl: Any, a: dict) -> None:
        frame = impl.main_frame if kind == "Page" else impl
        strict = bool(a.get("strict"))
        src = Target(frame, a.pop("source"), strict=strict)
        dst = Target(frame, a.pop("target"), strict=strict)
        await h.drag(src, dst, a, api=f"{api}.drag_and_drop")

    async def drag_to(h: Human, impl: Any, a: dict) -> None:
        other = _impl(a.pop("target"))
        await h.drag(_locator_target(impl), _locator_target(other), a, api=f"{api}.drag_to")

    common = {
        "click": click, "dblclick": dblclick, "hover": hover, "tap": tap, "fill": fill,
        "type": type_, "press": press, "check": check, "uncheck": uncheck,
        "set_checked": set_checked, "select_option": select_option, "focus": focus,
    }
    if kind in ("Page", "Frame"):
        return {**common, "drag_and_drop": drag_and_drop}
    if kind == "Locator":
        return {**common, "clear": clear, "press_sequentially": press_sequentially,
                "drag_to": drag_to, "scroll_into_view_if_needed": scroll_into_view_if_needed}
    return {**common, "scroll_into_view_if_needed": scroll_into_view_if_needed}


async def _mouse_move(h: Human, impl: Any, a: dict) -> None:
    await h.mouse_move(a["x"], a["y"], a.get("steps"))


async def _mouse_click(h: Human, impl: Any, a: dict) -> None:
    await h.mouse_click(a["x"], a["y"], a.get("delay"), a.get("button"), a.get("click_count"))


async def _mouse_dblclick(h: Human, impl: Any, a: dict) -> None:
    await h.mouse_click(a["x"], a["y"], a.get("delay"), a.get("button"), 2)


async def _keyboard_type(h: Human, impl: Any, a: dict) -> None:
    await h.keyboard_type(a["text"], a.get("delay"))


_INPUT_HANDLERS: Dict[str, Dict[str, Handler]] = {
    "Mouse": {"move": _mouse_move, "click": _mouse_click, "dblclick": _mouse_dblclick},
    "Keyboard": {"type": _keyboard_type},
}


# ---------------------------------------------------------------------------
# class patching
# ---------------------------------------------------------------------------

def _wrap(kind: str, cls: type, name: str, handler: Handler, is_async: bool) -> None:
    orig = cls.__dict__.get(name)
    if orig is None:
        return
    _ORIG[(cls, name)] = orig
    sig = inspect.signature(orig)

    def bind(self: Any, args: tuple, kwargs: dict, human_config: Optional[dict]) -> Dict[str, Any]:
        bound = sig.bind(self, *args, **kwargs)
        a = dict(bound.arguments)
        a.pop("self", None)
        a = _normalize(a)
        a["human_config"] = human_config
        return a

    if is_async:
        @functools.wraps(orig)
        async def wrapper(self: Any, *args: Any, human_config: Optional[dict] = None, **kwargs: Any) -> Any:
            h = _human_for(kind, self)
            if h is None:
                return await orig(self, *args, **kwargs)
            return await handler(h, self._impl_obj, bind(self, args, kwargs, human_config))
    else:
        @functools.wraps(orig)
        def wrapper(self: Any, *args: Any, human_config: Optional[dict] = None, **kwargs: Any) -> Any:
            h = _human_for(kind, self)
            if h is None:
                return orig(self, *args, **kwargs)
            return self._sync(handler(h, self._impl_obj, bind(self, args, kwargs, human_config)))

    setattr(cls, name, wrapper)


def _install(api: str) -> None:
    if _PATCHED[api]:
        return
    _check_playwright()
    if api == "sync":
        from playwright.sync_api import _generated as g
    else:
        from playwright.async_api import _generated as g
    is_async = api == "async"
    for kind in ("Page", "Frame", "Locator", "ElementHandle"):
        cls = getattr(g, kind)
        for name, handler in _handlers(kind).items():
            _wrap(kind, cls, name, handler, is_async)
    for kind, table in _INPUT_HANDLERS.items():
        cls = getattr(g, kind)
        for name, handler in table.items():
            _wrap(kind, cls, name, handler, is_async)
    _PATCHED[api] = True


def original(cls: type, name: str) -> Callable[..., Any]:
    """The unpatched Playwright method ``cls.name``."""
    return _ORIG.get((cls, name)) or getattr(cls, name)


class _Originals:
    """``page._original``: raw, un-humanized Playwright calls for this page."""

    _PAGE = ("click", "type", "fill", "hover", "dblclick", "select_option", "check", "uncheck",
             "press", "tap", "focus", "set_checked", "drag_and_drop", "goto")

    def __init__(self, page: Any) -> None:
        cls, mouse, kb = type(page), page.mouse, page.keyboard
        for name in self._PAGE:
            setattr(self, name, functools.partial(original(cls, name), page))
        for name in ("move", "click", "dblclick", "wheel", "down", "up"):
            setattr(self, f"mouse_{name}", functools.partial(original(type(mouse), name), mouse))
        for name in ("type", "down", "up", "press", "insert_text"):
            setattr(self, f"keyboard_{name}", functools.partial(original(type(kb), name), kb))


class _StealthWorld:
    """``page._stealth_world``: evaluate an expression in the main frame's
    isolated world (the same world the humanize engine uses)."""

    def __init__(self, page: Any, human: Human, is_async: bool) -> None:
        self._page, self._human, self._async = page, human, is_async

    def evaluate(self, expression: str) -> Any:
        coro = self._human.worlds.evaluate(self._human.page.main_frame, expression)
        return coro if self._async else self._page._sync(coro)

    def invalidate(self) -> None:
        self._human.worlds.invalidate()


def _attach(page: Any, cfg: HumanConfig, cursor: CursorState, api: str) -> Human:
    _install(api)
    impl = page._impl_obj
    human = getattr(impl, "_cloak_human", None)
    if human is None:
        human = Human(impl, cfg, cursor)
        impl._cloak_human = human
    page._original = _Originals(page)
    page._human_cfg = cfg
    page._human_cursor = cursor
    page._stealth_world = _StealthWorld(page, human, api == "async")
    return human


def patch_page(page: Any, cfg: HumanConfig, cursor: Optional[CursorState] = None) -> None:
    """Humanize a sync Playwright page."""
    cursor = cursor if cursor is not None else CursorState()
    _attach(page, cfg, cursor, "sync")
    if not cursor.initialized:
        # Start near the address bar instead of (0, 0).
        cursor.x = rand(*cfg.initial_cursor_x)
        cursor.y = rand(*cfg.initial_cursor_y)
        try:
            page._original.mouse_move(cursor.x, cursor.y)
            cursor.initialized = True
        except Exception:  # e.g. called from an event handler; done lazily
            pass


def patch_page_async(page: Any, cfg: HumanConfig, cursor: Optional[CursorState] = None) -> None:
    """Humanize an async Playwright page (cursor is placed on first action)."""
    _attach(page, cfg, cursor if cursor is not None else CursorState(), "async")


def patch_context(context: Any, cfg: HumanConfig) -> None:
    # Install class patches before any page exists: wrappers that capture
    # bound methods at page creation (license guard) must see the humanized ones.
    _install("sync")
    cursor = CursorState()
    for page in context.pages:
        patch_page(page, cfg, cursor)
    context.on("page", lambda p: None if hasattr(p, "_original") else patch_page(p, cfg, CursorState()))
    orig_new_page = context.new_page

    def new_page(*args: Any, **kwargs: Any) -> Any:
        page = orig_new_page(*args, **kwargs)
        if not hasattr(page, "_original"):
            patch_page(page, cfg, CursorState())
        return page

    context.new_page = new_page


def patch_browser(browser: Any, cfg: HumanConfig) -> None:
    _install("sync")
    for context in browser.contexts:
        patch_context(context, cfg)
    orig_new_context, orig_new_page = browser.new_context, browser.new_page

    def new_context(*args: Any, **kwargs: Any) -> Any:
        context = orig_new_context(*args, **kwargs)
        patch_context(context, cfg)
        return context

    def new_page(*args: Any, **kwargs: Any) -> Any:
        page = orig_new_page(*args, **kwargs)
        if not hasattr(page, "_original"):
            patch_page(page, cfg, CursorState())
        return page

    browser.new_context = new_context
    browser.new_page = new_page


def patch_context_async(context: Any, cfg: HumanConfig) -> None:
    _install("async")
    cursor = CursorState()
    for page in context.pages:
        patch_page_async(page, cfg, cursor)
    context.on("page", lambda p: None if hasattr(p, "_original") else patch_page_async(p, cfg, CursorState()))
    orig_new_page = context.new_page

    async def new_page(*args: Any, **kwargs: Any) -> Any:
        page = await orig_new_page(*args, **kwargs)
        if not hasattr(page, "_original"):
            patch_page_async(page, cfg, CursorState())
        return page

    context.new_page = new_page


def patch_browser_async(browser: Any, cfg: HumanConfig) -> None:
    _install("async")
    for context in browser.contexts:
        patch_context_async(context, cfg)
    orig_new_context, orig_new_page = browser.new_context, browser.new_page

    async def new_context(*args: Any, **kwargs: Any) -> Any:
        context = await orig_new_context(*args, **kwargs)
        patch_context_async(context, cfg)
        return context

    async def new_page(*args: Any, **kwargs: Any) -> Any:
        page = await orig_new_page(*args, **kwargs)
        if not hasattr(page, "_original"):
            patch_page_async(page, cfg, CursorState())
        return page

    browser.new_context = new_context
    browser.new_page = new_page
