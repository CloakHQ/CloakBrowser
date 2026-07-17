"""PxEngine: orchestrates detection → solving for PerimeterX challenges.

Auto-detects the PX variant using site-specific handlers and generic
detectors, then selects the best solving strategy.

Key improvements over v1:
- Cross-origin iframe PX detection via Playwright frame traversal
- Delayed detection window after goto (3s + 10s retries)
- Frame-attached listener for dynamically injected PX iframes
- CDP-level frame scanning when main-world JS can't cross origins
- Three-layer detection: JS observer → frame poll → Python fallback
- Async-compatible solving with proper await support
- Unified visibility checking across engine and solvers
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .config import PxConfig
from .detect.base import BaseDetector, DetectResult
from .detect.composite import CompositeDetector
from .detect.keyword import DetectPxByKeyword
from .detect.dom_element import DetectPxByDomElement
from .solve.base import BaseSolver, SolveResult
from .solve.composite import CompositeSolver
from .solve.press_hold_button import SolveByHoldButton
from .solve.press_hold_container import SolveByHoldContainer
from .site.base import SiteHandler

logger = logging.getLogger("cloakbrowser.pxbypass.engine")

# ---------------------------------------------------------------------------
# JS helpers — injected into the main page
# ---------------------------------------------------------------------------

# Checks main-page DOM for PX elements AND tries to probe child iframes.
# This JS runs in the main page context, so same-origin iframes are accessible.
# Cross-origin iframes are handled by Python-level frame traversal below.
_PX_UI_WATCHER_JS = """() => {
  function checkDoc(doc) {
    var px = doc.getElementById('px-captcha');
    if (px) { var r = px.getBoundingClientRect(); if (r.width > 10 && r.height > 10) return true; }
    px = doc.getElementById('px-captcha-modal');
    if (px) { var r = px.getBoundingClientRect(); if (r.width > 10 && r.height > 10) return true; }
    var el = doc.querySelector('[data-px-captcha]');
    if (el) { var r = el.getBoundingClientRect(); if (r.width > 10 && r.height > 10) return true; }
    el = doc.querySelector('.px-challenge');
    if (el) { var r = el.getBoundingClientRect(); if (r.width > 10 && r.height > 10) return true; }
    // Same-origin iframes
    try {
      for (var i = 0; i < doc.querySelectorAll('iframe').length; i++) {
        var ifr = doc.querySelectorAll('iframe')[i];
        try {
          var iDoc = ifr.contentDocument || ifr.contentWindow.document;
          if (iDoc) {
            var r2 = iDoc.getElementById('px-captcha');
            if (r2) { var rb = r2.getBoundingClientRect(); if (rb.width > 10 && rb.height > 10) return true; }
            var r3 = iDoc.getElementById('px-captcha-modal');
            if (r3) { var rb = r3.getBoundingClientRect(); if (rb.width > 10 && rb.height > 10) return true; }
          }
        } catch(e) {}
      }
    } catch(e) {}
    return false;
  }

  if (checkDoc(document)) return true;
  // Check body text for challenge markers
  var body = (document.body ? document.body.innerText : '') || '';
  if (body) {
    var t = body.toLowerCase();
    if (t.includes('activate and hold') || t.includes('press and hold')
        || t.includes('pressione e segure') || t.includes('robot or human')
        || t.includes('verifica') || t.includes('px-captcha')
        || t.includes('perimeterx') || t.includes('antes de continuarmos'))
      return true;
  }
  return false;
}"""

# MutationObserver that also watches for <iframe> insertion.
# This JS has a TWO-LEVEL detection approach:
#   1. MutationObserver fires on DOM changes
#   2. setInterval(1500) polls regardless (catches cross-origin, visibility changes)
# When PX is found, call __pxNotify() which is the Python exposed binding.
# NOTE: __pxNotify() returns a promise (from Playwright binding). We do NOT
# await it — it's fire-and-forget from JS perspective. The Python callback
# will run when the Playwright event loop processes it.
_PX_MUTATION_OBSERVER_JS = """() => {
  if (window.__pxObserverInstalled) return;
  window.__pxObserverInstalled = true;

  function pxCheckAndNotify() {
    if (window.__pxSolving) return;
    var found = !!(document.getElementById('px-captcha'));
    if (!found) found = !!(document.getElementById('px-captcha-modal'));
    if (!found) found = !!(document.querySelector('[data-px-captcha], .px-challenge'));
    // Check body text
    if (!found && document.body) {
      var t = (document.body.innerText || '').toLowerCase();
      found = t.includes('activate and hold') || t.includes('press and hold')
           || t.includes('pressione e segure') || t.includes('robot or human')
           || t.includes('px-captcha') || t.includes('antes de continuarmos');
    }
    if (found && window.__pxNotify) {
      window.__pxSolving = true;
      window.__pxNotify();
    }
  }

  var observer = new MutationObserver(function(mutations) {
    pxCheckAndNotify();
  });
  if (document.body) {
    observer.observe(document.body, { childList: true, subtree: true, characterData: true });
  } else {
    document.addEventListener('DOMContentLoaded', function() {
      observer.observe(document.body, { childList: true, subtree: true, characterData: true });
      pxCheckAndNotify();
    });
  }
  // Poll every 1.5 seconds as fallback (catches cross-origin iframe injection,
  // visibility-only changes that MutationObserver misses)
  setInterval(pxCheckAndNotify, 1500);
}"""


# ---------------------------------------------------------------------------
# Python helpers — Playwright-level frame traversal
# ---------------------------------------------------------------------------

def _check_px_on_all_frames(page: Any) -> bool:
    """Walk ALL frames (including cross-origin) and check for PX elements.

    Playwright's page.frames includes child frames regardless of origin.
    This catches PX challenges rendered in cross-origin iframes (Walmart, etc.)
    that the JS MutationObserver running in the main page cannot see.

    Returns True if PX challenge UI is detected.
    """
    for frame in page.frames:
        if frame == page.main_frame:
            continue  # already checked via _PX_UI_WATCHER_JS
        try:
            found = frame.evaluate("""() => {
                var px = document.getElementById('px-captcha');
                if (px) { var r = px.getBoundingClientRect(); return r.width > 10 && r.height > 10; }
                px = document.getElementById('px-captcha-modal');
                if (px) { var r = px.getBoundingClientRect(); return r.width > 10 && r.height > 10; }
                var el = document.querySelector('[data-px-captcha], .px-challenge');
                if (el) { var r = el.getBoundingClientRect(); return r.width > 10 && r.height > 10; }
                // keyword check
                var body = (document.body ? document.body.innerText : '') || '';
                if (body) {
                  var t = body.toLowerCase();
                  return t.includes('activate and hold') || t.includes('press and hold')
                      || t.includes('pressione e segure') || t.includes('robot or human')
                      || t.includes('px-captcha') || t.includes('antes de continuarmos');
                }
                return false;
            }""")
            if found:
                logger.debug("PX detected in child frame: %s", frame.url[:120])
                return True
        except Exception:
            pass  # cross-origin frame without access — skip
    return False


def _detect_px_on_all_frames(page: Any) -> DetectResult:
    """Return evidence when PX is rendered only inside a child frame."""
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            if frame.evaluate(_PX_UI_WATCHER_JS):
                return DetectResult(
                    detected=True,
                    confidence=0.9,
                    evidence={"frame_url": frame.url[:200]},
                )
        except Exception:
            pass
    return DetectResult()


async def _check_px_on_all_frames_async(page: Any) -> bool:
    """Async version of _check_px_on_all_frames."""
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            found = await frame.evaluate("""() => {
                var px = document.getElementById('px-captcha');
                if (px) { var r = px.getBoundingClientRect(); return r.width > 10 && r.height > 10; }
                px = document.getElementById('px-captcha-modal');
                if (px) { var r = px.getBoundingClientRect(); return r.width > 10 && r.height > 10; }
                var el = document.querySelector('[data-px-captcha], .px-challenge');
                if (el) { var r = el.getBoundingClientRect(); return r.width > 10 && r.height > 10; }
                var body = (document.body ? document.body.innerText : '') || '';
                if (body) {
                  var t = body.toLowerCase();
                  return t.includes('activate and hold') || t.includes('press and hold')
                      || t.includes('pressione e segure') || t.includes('robot or human')
                      || t.includes('px-captcha') || t.includes('antes de continuarmos');
                }
                return false;
            }""")
            if found:
                logger.debug("PX detected in child frame (async): %s", frame.url[:120])
                return True
        except Exception:
            pass
    return False


async def _detect_px_on_all_frames_async(page: Any) -> DetectResult:
    """Async variant of :func:`_detect_px_on_all_frames`."""
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            if await frame.evaluate(_PX_UI_WATCHER_JS):
                return DetectResult(
                    detected=True,
                    confidence=0.9,
                    evidence={"frame_url": frame.url[:200]},
                )
        except Exception:
            pass
    return DetectResult()


class PxEngine:
    """Orchestrates detection and solving of PerimeterX challenges.

    Detection uses three layers:
    1. MutationObserver injected into main page (catches same-origin PX)
    2. Python-level Playwright frame traversal (catches cross-origin iframe PX)
    3. Method-patching on page objects (catches PX appearing during idle loops)
    """

    def __init__(self, cfg: PxConfig | None = None):
        self.cfg = cfg or PxConfig()
        self._site_handlers: list[SiteHandler] = []
        self._detect_only = False

    def register_handler(self, handler: SiteHandler) -> None:
        """Register a site-specific handler."""
        self._site_handlers.append(handler)
        self._site_handlers.sort(key=lambda h: h.priority, reverse=True)

    @property
    def generic_detector(self) -> BaseDetector:
        """Fallback detector used when no site handler matches."""
        # Script/global presence only proves the PX SDK is installed.  Most
        # protected applications load it on every normal page, so treating the
        # SDK itself as an active captcha causes permanent false positives.
        # Active challenge detection must come from visible text/DOM or frame UI.
        return CompositeDetector([
            DetectPxByKeyword(),
            DetectPxByDomElement(),
        ])

    @property
    def generic_solver(self) -> BaseSolver:
        """Fallback solver used when no site handler matches."""
        return CompositeSolver([
            SolveByHoldButton(),
            SolveByHoldContainer(),
        ])

    def detect(self, page: Any) -> tuple[SiteHandler | None, DetectResult]:
        """Detect PX challenge and identify the best handler.

        Tries site-specific handlers that match the current page URL,
        then falls back to generic detection.

        Args:
            page: Playwright Page object.

        Returns:
            (handler, result) — handler may be None if no specific site matches.
        """
        # Try site-specific handlers that match the current URL
        for handler in self._site_handlers:
            if not handler.match_url(page):
                continue
            result = handler.detect(page)
            if result.detected and result.confidence >= 0.3:
                logger.debug("Site handler '%s' matched (confidence=%.2f)",
                             handler.name, result.confidence)
                return handler, result

        # Fallback: generic detection
        generic_result = self.generic_detector.detect(page)
        if generic_result.detected:
            logger.debug("Generic detector matched (confidence=%.2f)",
                         generic_result.confidence)
            return None, generic_result

        frame_result = _detect_px_on_all_frames(page)
        if frame_result.detected:
            logger.debug("PX detected from child-frame evidence")
            return None, frame_result

        return None, DetectResult()

    async def detect_async(self, page: Any) -> tuple[SiteHandler | None, DetectResult]:
        """Async Playwright variant of :meth:`detect`."""
        for handler in self._site_handlers:
            if not handler.match_url(page):
                continue
            result = await handler.detect_async(page)
            if result.detected and result.confidence >= 0.3:
                logger.debug(
                    "Site handler '%s' matched async (confidence=%.2f)",
                    handler.name,
                    result.confidence,
                )
                return handler, result

        generic_result = await self.generic_detector.detect_async(page)
        if generic_result.detected:
            return None, generic_result

        frame_result = await _detect_px_on_all_frames_async(page)
        if frame_result.detected:
            return None, frame_result
        return None, DetectResult()

    def solve(self, page: Any, handler: SiteHandler | None,
              detect_result: DetectResult) -> SolveResult:
        """Solve the detected PX challenge."""
        if not self.cfg.enabled:
            return SolveResult(method="PxEngine", error="disabled")

        if handler is not None:
            logger.info("Using site handler '%s' for solving", handler.name)
            return handler.solve(page, self.cfg, detect_result)

        logger.info("Using generic solver")
        return self.generic_solver.solve(page, self.cfg, detect_result)

    async def solve_async(self, page: Any, handler: SiteHandler | None,
                          detect_result: DetectResult) -> SolveResult:
        """Solve the detected PX challenge (async).

        Uses solver's async solve method if available. Falls back to sync solve.
        """
        if not self.cfg.enabled:
            return SolveResult(method="PxEngine", error="disabled")

        solver: BaseSolver
        if handler is not None:
            logger.info("Using site handler '%s' for solving (async)", handler.name)
            solver = handler.build_solver()
        else:
            logger.info("Using generic solver (async)")
            solver = self.generic_solver

        return await solver.async_solve(page, self.cfg, detect_result)

    # -----------------------------------------------------------------------
    # Core detection with three-layer fallback
    # -----------------------------------------------------------------------

    def _is_px_visible(self, page: Any) -> bool:
        """Check if PX UI is visible — three-layer approach.

        1. JS main-page check (fast, works for same-origin + text)
        2. Python frame traversal (catches cross-origin iframe PX)
        """
        try:
            if page.evaluate(_PX_UI_WATCHER_JS):
                return True
        except Exception:
            pass

        # Layer 2: walk all child frames via Playwright
        try:
            if _check_px_on_all_frames(page):
                return True
        except Exception:
            pass

        return False

    async def _is_px_visible_async(self, page: Any) -> bool:
        """Async version of _is_px_visible."""
        try:
            if await page.evaluate(_PX_UI_WATCHER_JS):
                return True
        except Exception:
            pass

        try:
            if await _check_px_on_all_frames_async(page):
                return True
        except Exception:
            pass

        return False

    def check_and_solve(self, page: Any) -> bool:
        """Check if PX is present and solve it (one-shot).

        Uses a page-level `_px_is_solving` flag to prevent concurrent solve
        attempts — multiple background polls or callbacks stacking up would
        otherwise simulate overlapping press-and-hold, wasting time and
        potentially interfering with each other.

        Returns True if no PX found or PX solved successfully.
        Returns False if PX present but solving failed.
        """
        if not self.cfg.enabled:
            return True

        if not self._is_px_visible(page):
            return True

        # Guard: skip if already solving (concurrent press-and-hold would
        # interfere — multiple threads/tasks all holding at the same time
        # never let the browser process a clean mouse-up)
        if getattr(page, '_px_is_solving', False):
            logger.debug("PX solve already in progress, skipping")
            return False

        page._px_is_solving = True
        try:
            handler, result = self.detect(page)
            if not result.detected:
                return True

            logger.info("PX detected (confidence=%.2f), solving...", result.confidence)
            solve_result = self.solve(page, handler, result)

            if solve_result.solved:
                logger.info("PX solved via %s in %.1fs",
                            solve_result.method, solve_result.duration)
            else:
                logger.warning("PX solve failed via %s: %s",
                               solve_result.method, solve_result.error)
            return solve_result.solved
        finally:
            page._px_is_solving = False

    async def check_and_solve_async(self, page: Any) -> bool:
        """Async version of check_and_solve with concurrency guard."""
        if not self.cfg.enabled:
            return True

        if not await self._is_px_visible_async(page):
            return True

        if getattr(page, '_px_is_solving', False):
            logger.debug("PX solve already in progress (async), skipping")
            return False

        page._px_is_solving = True
        try:
            handler, result = await self.detect_async(page)
            if not result.detected:
                return True

            logger.info("PX detected (async, confidence=%.2f), solving...", result.confidence)
            solve_result = await self.solve_async(page, handler, result)

            if solve_result.solved:
                logger.info("PX solved via %s (async) in %.1fs",
                            solve_result.method, solve_result.duration)
            else:
                logger.warning("PX solve failed via %s (async): %s",
                               solve_result.method, solve_result.error)
            return solve_result.solved
        finally:
            page._px_is_solving = False

    # -----------------------------------------------------------------------
    # Observer installation (sync)
    # -----------------------------------------------------------------------

    def install_observer(self, page: Any) -> None:
        """Inject MutationObserver into the page and expose Python callback."""
        if getattr(page, '_px_observer_installed', False):
            return
        page._px_observer_installed = True

        page.expose_binding(
            "__pxNotify",
            lambda _source, *args: self._on_px_detected(page),
        )
        page.on("load", lambda *args: self._on_page_load(page))
        # Listen for new iframes being attached
        page.on("frameattached", lambda f: self._on_frame_attached(page, f))
        self._reinject_observer(page)

    def _reinject_observer(self, page: Any) -> None:
        try:
            page.evaluate(_PX_MUTATION_OBSERVER_JS)
        except Exception:
            pass

    def _on_page_load(self, page: Any) -> None:
        """Called when page fires 'load' event."""
        self._reinject_observer(page)
        # Quick check right after load
        try:
            self.check_and_solve(page)
        except Exception as exc:
            logger.debug("PX check after load failed (non-fatal): %s", exc)

        # Patch commonly-used page properties/methods to trigger PX checks.
        # This is needed because Playwright's sync API uses greenlets and
        # pending callbacks (from expose_binding via __pxNotify) are only
        # processed when a Playwright API call is actively made. During
        # user code like "while True: time.sleep(1)", callbacks pile up.
        _patch_methods_for_px_polling(page, self)

    def _on_frame_attached(self, page: Any, frame: Any) -> None:
        """Called when a new frame is attached — could be a PX iframe."""
        try:
            self.check_and_solve(page)
        except Exception:
            pass

    def _on_px_detected(self, page: Any) -> None:
        """Called from JS __pxNotify binding — PX detected on browser side."""
        try:
            self.check_and_solve(page)
        except Exception as exc:
            logger.debug("PX solve failed (non-fatal): %s", exc)
        finally:
            try:
                page.evaluate("window.__pxSolving = false")
            except Exception:
                pass

    # -----------------------------------------------------------------------
    # Observer installation (async)
    # -----------------------------------------------------------------------

    async def install_observer_async(self, page: Any) -> None:
        """Async version of install_observer."""
        if getattr(page, '_px_observer_installed', False):
            return
        page._px_observer_installed = True

        await page.expose_binding(
            "__pxNotify",
            lambda _source, *args: self._on_px_detected_async(page),
        )
        page.on("load", lambda *args: asyncio.create_task(self._on_page_load_async(page)))
        page.on("frameattached", lambda f: asyncio.create_task(self._on_frame_attached_async(page, f)))
        await self._reinject_observer_async(page)

    async def _reinject_observer_async(self, page: Any) -> None:
        try:
            await page.evaluate(_PX_MUTATION_OBSERVER_JS)
        except Exception:
            pass

    async def _on_page_load_async(self, page: Any) -> None:
        await self._reinject_observer_async(page)
        try:
            await self.check_and_solve_async(page)
        except Exception as exc:
            logger.debug("PX check after load (async) failed: %s", exc)
        # Delayed checks via asyncio (event-loop-safe)
        async def _delayed(delay: float):
            await asyncio.sleep(delay)
            try:
                await self.check_and_solve_async(page)
            except Exception:
                pass
        asyncio.create_task(_delayed(3.0))
        asyncio.create_task(_delayed(10.0))

    async def _on_frame_attached_async(self, page: Any, frame: Any) -> None:
        try:
            await self.check_and_solve_async(page)
        except Exception:
            pass

    def _on_px_detected_async(self, page: Any) -> None:
        try:
            asyncio.create_task(self._solve_async(page))
        except Exception as exc:
            logger.debug("PX solve failed (async, non-fatal): %s", exc)

    async def _solve_async(self, page: Any) -> None:
        await self.check_and_solve_async(page)
        try:
            await page.evaluate("window.__pxSolving = false")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Sync API polling — patch page methods to trigger PX checks
# ---------------------------------------------------------------------------
# CRITICAL: Playwright's sync API uses greenlets and pending callbacks from
# expose_binding are ONLY processed when a Playwright API call is made. This
# means that during user code like:
#
#   while True:
#       time.sleep(1)  # ← no Playwright calls → __pxNotify callback stuck!
#
# the PX callback never fires in Python. The JS-side setInterval fires __pxNotify()
# correctly, but the Python callback sits in a greenlet buffer undelivered.
#
# Our solution: Patch the most commonly-used page methods to do a lightweight
# PX detection pass. This "flushes" the callback buffer whenever the user
# interacts with the page.

_PATCHED_CALLABLE_METHODS = [
    "title", "content", "evaluate", "query_selector",
    "query_selector_all", "wait_for_selector", "screenshot",
    "click", "fill",
]
# NOTE: "url" is a read-only property, not a method — skip it.
# "keyboard" and "mouse" return objects, not functions — skip them too.
# Only patch actual callables that won't raise AttributeError on setattr.


def _patch_methods_for_px_polling(page: Any, engine: PxEngine) -> None:
    """Patch common page METHODS to trigger periodic PX checks.

    Only patches callable methods — NOT read-only properties like `page.url`.
    Every call to a patched method does: original() + periodic PX check (~3s).

    Also adds a `wait_for_px_solved()` convenience method.
    """
    if getattr(page, '_px_methods_patched', False):
        return
    page._px_methods_patched = True
    page._px_last_poll_time = 0.0
    page._px_poll_interval = 3.0  # seconds between PX checks
    page._px_engine = engine

    # Patch only callable methods
    for method_name in _PATCHED_CALLABLE_METHODS:
        _patch_single_method(page, method_name)

    # Add a convenience method for the user to call manually
    def _px_wait_for_solved(timeout: float = 120.0) -> bool:
        """Wait until the current PX challenge clears after an actual solve."""
        import time as _time
        deadline = _time.monotonic() + timeout
        saw_px = False
        while _time.monotonic() < deadline:
            visible = engine._is_px_visible(page)
            if not visible:
                # If we previously saw a challenge, confirm with the full
                # detector before claiming success.  This avoids transient DOM
                # gaps while PX replaces/reloads its iframe.
                if not saw_px:
                    return True
                _time.sleep(0.2)
                _handler, result = engine.detect(page)
                if not result.detected:
                    return True
                visible = True
            saw_px = True
            try:
                if not engine.check_and_solve(page):
                    _time.sleep(0.5)
                    continue
            except Exception:
                pass
            _time.sleep(0.5)
        return not engine.detect(page)[1].detected

    page.wait_for_px_solved = _px_wait_for_solved


def _patch_single_method(page: Any, method_name: str) -> None:
    """Patch a single page METHOD to trigger PX checks periodically.

    Only patches callables — skips read-only properties.
    """
    original = getattr(page, method_name, None)
    if original is None:
        return
    # Skip if it's a property (not callable)
    if not callable(original):
        return
    # Attempt setattr — if it fails (read-only property), skip silently
    try:
        def _make_patched(orig):
            def _patched(*args: Any, **kwargs: Any) -> Any:
                result = orig(*args, **kwargs)
                _try_px_poll(page)
                return result
            return _patched
        setattr(page, method_name, _make_patched(original))
    except (AttributeError, TypeError):
        pass


def _try_px_poll(page: Any) -> None:
    """Try to check-and-solve PX if enough time has passed."""
    now = time.monotonic()
    last = getattr(page, '_px_last_poll_time', 0.0)
    interval = getattr(page, '_px_poll_interval', 3.0)
    if now - last < interval:
        return
    page._px_last_poll_time = now
    engine = getattr(page, '_px_engine', None)
    if engine is None:
        return
    try:
        engine.check_and_solve(page)
    except Exception:
        pass
