"""PerimeterX (PX) Captcha auto-solver for cloakbrowser.

Activated via bypass_px=True in launch() / launch_async().
Automatically detects and solves PerimeterX "Press & Hold" challenges
on ALL pages in the browser, regardless of how navigation happens.

Background monitoring starts as soon as a page is created and continuously
polls the page for PX UI. When detected, it solves automatically.

Architecture:
    - detect/     : Individual detection strategies (keyword, DOM, script, URL, globals)
    - solve/      : Individual solving strategies (hold button, hold container)
    - site/       : Site-specific handler configurations (Walmart, iFood)
    - engine.py   : PxEngine orchestrates detect → solve pipeline

Usage:
    from cloakbrowser import launch
    browser = launch(bypass_px=True)
    page = browser.new_page()
    page.goto("https://target-site.com")  # PX solved automatically if encountered
    # Background monitor keeps watching — any PX that appears later is also solved.

Advanced:
    from cloakbrowser.pxbypass import PxEngine
    from cloakbrowser.pxbypass.config import PxConfig
    from cloakbrowser.pxbypass.site import WalmartHandler

    engine = PxEngine(PxConfig(max_attempts=5))
    engine.register_handler(WalmartHandler())

    handler, result = engine.detect(page)
    if result.detected:
        engine.solve(page, handler, result)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .engine import PxEngine, _patch_methods_for_px_polling
from .config import PxConfig
from .detect.base import DetectResult
from .solve.base import SolveResult
from .detect import (
    BaseDetector, DetectPxByKeyword, DetectPxByDomElement,
    DetectPxByScriptSrc, DetectPxByUrlPattern, DetectPxByGlobals,
    CompositeDetector, DetectMode,
)
from .solve import (
    BaseSolver, SolveByHoldButton, SolveByHoldContainer, CompositeSolver,
)
from .site import SiteHandler, WalmartHandler, IfoodHandler

logger = logging.getLogger("cloakbrowser.pxbypass")

# Default engine instance for quick use
_default_engine: PxEngine | None = None


def _get_engine(cfg: PxConfig | None = None) -> PxEngine:
    """Get or create the default PxEngine singleton."""
    global _default_engine
    if _default_engine is None or cfg is not None:
        engine = PxEngine(cfg or PxConfig())
        if not engine._site_handlers:  # Only register if empty
            engine.register_handler(WalmartHandler())
            engine.register_handler(IfoodHandler())
        if cfg is None:
            _default_engine = engine
        return engine
    return _default_engine


# ---------------------------------------------------------------------------
# Backward-compatible public API (same signatures as original detector.py)
# ---------------------------------------------------------------------------


def detect_px(page: Any) -> str | None:
    """Detect if the current page has a PerimeterX challenge.

    Args:
        page: Playwright Page object.

    Returns:
        'perimeterx' if PX challenge is detected, None otherwise.
    """
    engine = _get_engine()
    handler, result = engine.detect(page)
    if result.detected:
        logger.debug("PX detected via %s (confidence=%.2f)",
                     handler.name if handler else "generic", result.confidence)
        return "perimeterx"
    return None


def solve_px(page: Any, cfg: PxConfig | None = None) -> bool:
    """Try to solve a PX challenge on the current page.

    Args:
        page: Playwright Page object.
        cfg: Optional PxConfig override.

    Returns:
        True if solved, False if failed.
    """
    engine = _get_engine(cfg)
    handler, result = engine.detect(page)
    if not result.detected:
        return True  # No PX to solve
    return engine.solve(page, handler, result).solved


def patch_browser(browser: Any, cfg: PxConfig | None = None) -> None:
    """Patch browser to auto-solve PX on new pages (sync).

    Every page created from this browser (via new_page() or
    context.new_page()) will have background PX monitoring enabled.

    Args:
        browser: Playwright Browser object.
        cfg: Optional PxConfig override.
    """
    if cfg is None:
        cfg = PxConfig()

    _original_new_page = browser.new_page
    _original_new_context = browser.new_context

    def _patched_new_page(**kwargs: Any) -> Any:
        page = _original_new_page(**kwargs)
        _patch_page(page, cfg)
        return page

    def _patched_new_context(**kwargs: Any) -> Any:
        context = _original_new_context(**kwargs)
        _original_cx_page = context.new_page

        def _patched_cx_new_page(**pk: Any) -> Any:
            page = _original_cx_page(**pk)
            _patch_page(page, cfg)
            return page

        context.new_page = _patched_cx_new_page
        return context

    browser.new_page = _patched_new_page
    browser.new_context = _patched_new_context
    logger.debug("PX bypass patched on browser (sync)")


def patch_browser_async(browser: Any, cfg: PxConfig | None = None) -> None:
    """Patch browser to auto-solve PX on new pages (async).

    Every page created from this browser (via new_page() or
    context.new_page()) will have background PX monitoring enabled.

    Args:
        browser: Playwright Browser object (async API).
        cfg: Optional PxConfig override.
    """
    if cfg is None:
        cfg = PxConfig()

    _original_new_page = browser.new_page
    _original_new_context = browser.new_context

    async def _patched_new_page(**kwargs: Any) -> Any:
        page = await _original_new_page(**kwargs)
        await _patch_page_async(page, cfg)
        return page

    async def _patched_new_context(**kwargs: Any) -> Any:
        context = await _original_new_context(**kwargs)
        _original_cx_page = context.new_page

        async def _patched_cx_new_page(**pk: Any) -> Any:
            page = await _original_cx_page(**pk)
            await _patch_page_async(page, cfg)
            return page

        context.new_page = _patched_cx_new_page
        return context

    browser.new_page = _patched_new_page
    browser.new_context = _patched_new_context
    logger.debug("PX bypass patched on browser (async)")


def patch_page(page: Any, cfg: PxConfig) -> None:
    """Patch a single page to auto-solve PX (sync).

    Args:
        page: Playwright Page object.
        cfg: PxConfig instance.
    """
    _patch_page(page, cfg)


async def patch_page_async(page: Any, cfg: PxConfig) -> None:
    """Patch a single page to auto-solve PX (async).

    Args:
        page: Playwright Page object (async API).
        cfg: PxConfig instance.
    """
    await _patch_page_async(page, cfg)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _patch_page(page: Any, cfg: PxConfig) -> None:
    """Internal: patch page for sync API.

    Injects a MutationObserver into the page that watches for
    PX challenge elements. When detected, fires a Python callback
    that runs detection and solving — all on the main thread.

    Also patches goto() for a quick initial detection after navigation.

    NOTE: Playwright's sync API uses greenlets and is NOT thread-safe.
    We do NOT start a background thread for polling. Instead we rely on:
    - MutationObserver JS (with JS-side setInterval polling every 1.5s)
    - goto() patch for immediate post-navigation check
    - load event handler with delayed checks (3s, 10s)
    - frameattached handler for dynamically injected iframes
    """
    if getattr(page, '_px_patched', False):
        return
    page._px_patched = True

    engine = _get_engine(cfg)
    page._px_cfg = cfg

    # Inject JS MutationObserver — watches DOM for PX elements
    engine.install_observer(page)
    # Make the sync API poll on ordinary Playwright calls immediately. Waiting
    # for a later load callback can miss challenges already present when goto()
    # returns (and leaves wait_for_px_solved unavailable to the caller).
    _patch_methods_for_px_polling(page, engine)

    # Also patch goto() for a quick initial detection after navigation
    _original_goto = page.goto

    def _patched_goto(url: str, **kwargs: Any) -> Any:
        response = _original_goto(url, **kwargs)
        if cfg.enabled:
            try:
                engine._on_page_load(page)
            except Exception as exc:
                logger.debug("PX navigate check failed (non-fatal): %s", exc)
        return response

    page.goto = _patched_goto

    logger.debug("PX bypass patched on page (sync)")


async def _patch_page_async(page: Any, cfg: PxConfig) -> None:
    """Internal: patch page for async API.

    Injects MutationObserver + patches goto() + starts background monitor.

    Args:
        page: Playwright Page object (async API).
        cfg: PxConfig instance.
    """
    if getattr(page, '_px_patched', False):
        return
    page._px_patched = True

    engine = _get_engine(cfg)
    page._px_cfg = cfg

    # Inject JS MutationObserver — async variant
    await engine.install_observer_async(page)

    # Also patch goto() for a quick initial detection after navigation
    _original_goto = page.goto

    async def _patched_goto(url: str, **kwargs: Any) -> Any:
        response = await _original_goto(url, **kwargs)
        if cfg.enabled:
            try:
                await engine._on_page_load_async(page)
            except Exception as exc:
                logger.debug("PX navigate check failed (non-fatal): %s", exc)
        return response

    page.goto = _patched_goto

    # Start background monitoring asyncio task (same event loop — thread-safe)
    _start_bg_monitor_async(page, engine, cfg)

    logger.debug("PX bypass patched on page (async) with background monitor")


# ---------------------------------------------------------------------------
# Background monitoring (async only — sync API relies on JS-side setInterval)
# ---------------------------------------------------------------------------


def _start_bg_monitor_async(page: Any, engine: PxEngine, cfg: PxConfig) -> None:
    """Start an asyncio background task that periodically polls for PX.

    Only call this from async API — runs in the same event loop as Playwright,
    so it is thread-safe.
    """
    if getattr(page, '_px_bg_monitor_started', False):
        return
    page._px_bg_monitor_started = True
    page._px_bg_closed = False

    async def _monitor_loop() -> None:
        while not getattr(page, '_px_bg_closed', False):
            try:
                # Check if page is still alive
                try:
                    await page.evaluate("1+1")
                except Exception:
                    page._px_bg_closed = True
                    break

                if cfg.enabled:
                    await engine.check_and_solve_async(page)
            except Exception:
                pass
            await asyncio.sleep(cfg.monitor_interval)

    asyncio.ensure_future(_monitor_loop())

    # Patch page.close to stop the monitor
    _orig_close = page.close

    async def _patched_close(*args: Any, **kwargs: Any) -> Any:
        page._px_bg_closed = True
        return await _orig_close(*args, **kwargs)

    page.close = _patched_close


__all__ = [
    # Core
    "PxEngine", "PxConfig", "DetectResult", "SolveResult",
    # Detection
    "BaseDetector", "DetectPxByKeyword", "DetectPxByDomElement",
    "DetectPxByScriptSrc", "DetectPxByUrlPattern", "DetectPxByGlobals",
    "CompositeDetector", "DetectMode",
    # Solving
    "BaseSolver", "SolveByHoldButton", "SolveByHoldContainer", "CompositeSolver",
    # Sites
    "SiteHandler", "WalmartHandler", "IfoodHandler",
    # Backward compat
    "detect_px", "solve_px",
    "patch_browser", "patch_browser_async",
    "patch_page", "patch_page_async",
]
