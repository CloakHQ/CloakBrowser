"""PerimeterX "Press & Hold" challenge solver.

Implements automatic detection and solving of PerimeterX
"Press & Hold" / "Pressione e segure" / "Activate and hold"
challenges using human-like mouse movements and hold timing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import (
    PxConfig,
    PX_TEXT_MARKERS,
    PX_HOLD_BUTTON_LABELS,
)
from .detector import is_px_visible, is_px_block_page

logger = logging.getLogger("cloakbrowser.pxbypass.solver")

# ---------------------------------------------------------------------------
# JS snippets
# ---------------------------------------------------------------------------

# JS: find hold button text in main document / iframe modal (iFood variant)
_PICK_HOLD_BUTTON_JS = """
() => {
  const btnLabels = ['pressione e segure', 'press and hold', 'press & hold', 'activate and hold'];
  const instructionRe = /antes de continuarmos|confirmar que você|não um bot|thank you/i;

  function scoreHoldButton(el) {
    const t = (el.innerText || '').trim();
    const r = el.getBoundingClientRect();
    if (r.width < 70 || r.height < 22 || r.height > 90) return -1;
    if (instructionRe.test(t)) return -1;
    if (['P', 'H1', 'H2', 'H3'].includes(el.tagName) && t.length > 40) return -1;
    const tLow = t.toLowerCase();
    let s = -1;
    if (btnLabels.some((l) => tLow === l)) s = 200;
    else if (btnLabels.some((l) => tLow.includes(l)) && t.length <= 40) s = 80;
    else return -1;
    if (el.getAttribute('role') === 'button' || el.tagName === 'BUTTON') s += 60;
    if (el.tagName === 'DIV' || el.tagName === 'A') s += 15;
    return s;
  }

  function scanDoc(doc) {
    let best = null; let bestScore = -1;
    for (const el of doc.querySelectorAll('button, [role="button"], a, div, span')) {
      const s = scoreHoldButton(el);
      if (s > bestScore) { bestScore = s; best = el; }
    }
    if (!best) return null;
    const r = best.getBoundingClientRect();
    return { x: r.left + r.width/2, y: r.top + r.height/2, w: r.width, h: r.height,
             text: (best.innerText||'').slice(0,40), tag: best.tagName, source: 'px-hold-button' };
  }

  // iFood variant: modal iframe
  var modal = document.getElementById('px-captcha-modal');
  if (modal && modal.contentDocument) {
    var ir = modal.getBoundingClientRect();
    var hit = scanDoc(modal.contentDocument);
    if (hit) { hit.x += ir.left; hit.y += ir.top; return hit; }
  }
  return scanDoc(document);
}
"""

# JS: get PX captcha container position (Walmart cloud variant - safe, no cross-origin access)
_GET_PX_CONTAINER_POSITION_JS = """
(function() {
  // Try iframe first
  var pxCaptcha = document.getElementById('px-captcha');
  if (!pxCaptcha) return null;
  // Use the container div - it's always visible even when iframe is display:none
  try {
    var r = pxCaptcha.getBoundingClientRect();
    if (!r || typeof r.width === 'undefined') return null;
    // Only valid if the container has some size
    if (r.width < 10 || r.height < 10) return null;
    return {
      x: r.left + r.width / 2,
      y: r.top + r.height / 2,
      w: r.width,
      h: r.height,
      source: 'px-container'
    };
  } catch(e) {
    return null;
  }
})()
"""

# ---------------------------------------------------------------------------
# Hold target dataclass
# ---------------------------------------------------------------------------

from dataclasses import dataclass


@dataclass
class HoldTarget:
    """Position of the hold button in viewport coordinates."""
    x: float
    y: float
    width: float
    height: float
    source: str = ""


# ---------------------------------------------------------------------------
# Human mouse movement (sync)
# ---------------------------------------------------------------------------


def _human_move_to(page: Any, tx: float, ty: float) -> None:
    """Move mouse to target with a human-like Bezier trajectory (sync)."""
    import math
    vp = page.viewport_size or {"width": 1280, "height": 720}
    sx = random.uniform(vp["width"] * 0.2, vp["width"] * 0.8)
    sy = random.uniform(vp["height"] * 0.2, vp["height"] * 0.8)
    steps = random.randint(10, 18)

    page.mouse.move(sx, sy)
    time.sleep(random.uniform(0.08, 0.2))
    for i in range(1, steps + 1):
        t_val = i / steps
        ease = t_val * t_val * (3 - 2 * t_val)
        cx = sx + (tx - sx) * ease + random.uniform(-2.5, 2.5)
        cy = sy + (ty - sy) * ease + random.uniform(-2.5, 2.5)
        page.mouse.move(cx, cy)
        time.sleep(random.uniform(0.015, 0.04))
    page.mouse.move(tx, ty)
    time.sleep(random.uniform(0.05, 0.12))


async def _async_human_move_to(page: Any, tx: float, ty: float) -> None:
    """Move mouse to target with a human-like Bezier trajectory (async)."""
    import math
    vp = page.viewport_size or {"width": 1280, "height": 720}
    sx = random.uniform(vp["width"] * 0.2, vp["width"] * 0.8)
    sy = random.uniform(vp["height"] * 0.2, vp["height"] * 0.8)
    steps = random.randint(10, 18)

    await page.mouse.move(sx, sy)
    await asyncio.sleep(random.uniform(0.08, 0.2))
    for i in range(1, steps + 1):
        t_val = i / steps
        ease = t_val * t_val * (3 - 2 * t_val)
        cx = sx + (tx - sx) * ease + random.uniform(-2.5, 2.5)
        cy = sy + (ty - sy) * ease + random.uniform(-2.5, 2.5)
        await page.mouse.move(cx, cy)
        await asyncio.sleep(random.uniform(0.015, 0.04))
    await page.mouse.move(tx, ty)
    await asyncio.sleep(random.uniform(0.05, 0.12))


# ---------------------------------------------------------------------------
# Target finding: hold button text → container position → iframe position
# ---------------------------------------------------------------------------


def _find_hold_target(page: Any) -> HoldTarget | None:
    """Locate the PX target using multi-strategy approach (sync).

    Priority:
      1. Playwright exact text locator (same-origin buttons)
      2. JS button scorer (iframe modal variants like iFood)
      3. PX container bounding rect (cloud cross-origin variants like Walmart)

    Returns:
        HoldTarget with viewport coordinates, or None if not found.
    """
    # Strategy 1: Playwright exact text locator
    try:
        for label in PX_HOLD_BUTTON_LABELS:
            try:
                loc = page.get_by_text(label, exact=True).first
                if loc.count() and loc.is_visible():
                    box = loc.bounding_box()
                    if box and box["width"] >= 70 and box["height"] >= 22:
                        return HoldTarget(
                            x=box["x"] + box["width"] / 2,
                            y=box["y"] + box["height"] / 2,
                            width=box["width"], height=box["height"],
                            source=f"playwright:{label[:12]}",
                        )
            except Exception:
                continue
    except Exception:
        pass

    # Strategy 2: JS button scorer
    try:
        raw: dict[str, Any] | None = page.evaluate(_PICK_HOLD_BUTTON_JS)
        if raw and raw.get("w") and raw["w"] >= 70:
            return HoldTarget(
                x=float(raw["x"]), y=float(raw["y"]),
                width=float(raw["w"]), height=float(raw["h"]),
                source=f"js:{raw.get('source', 'px-btn')}",
            )
    except Exception:
        pass

    # Strategy 3: PX container position (Walmart cloud variant)
    try:
        raw = page.evaluate(_GET_PX_CONTAINER_POSITION_JS)
        if raw and raw.get("w") and raw["w"] >= 70:
            logger.debug("Found PX target via container position: %.0fx%.0f at (%.0f,%.0f)",
                         raw["w"], raw["h"], raw["x"], raw["y"])
            return HoldTarget(
                x=float(raw["x"]), y=float(raw["y"]),
                width=float(raw["w"]), height=float(raw["h"]),
                source=f"container:{raw.get('source', 'px-container')}",
            )
    except Exception as exc:
        logger.debug("Container position lookup failed: %s", exc)

    return None


async def _async_find_hold_target(page: Any) -> HoldTarget | None:
    """Locate the PX target (async version)."""
    try:
        for label in PX_HOLD_BUTTON_LABELS:
            try:
                loc = page.get_by_text(label, exact=True).first
                if await loc.count() and await loc.is_visible():
                    box = await loc.bounding_box()
                    if box and box["width"] >= 70 and box["height"] >= 22:
                        return HoldTarget(
                            x=box["x"] + box["width"] / 2,
                            y=box["y"] + box["height"] / 2,
                            width=box["width"], height=box["height"],
                            source=f"playwright:{label[:12]}",
                        )
            except Exception:
                continue
    except Exception:
        pass

    try:
        raw: dict[str, Any] | None = await page.evaluate(_PICK_HOLD_BUTTON_JS)
        if raw and raw.get("w") and raw["w"] >= 70:
            return HoldTarget(
                x=float(raw["x"]), y=float(raw["y"]),
                width=float(raw["w"]), height=float(raw["h"]),
                source=f"js:{raw.get('source', 'px-btn')}",
            )
    except Exception:
        pass

    try:
        raw = await page.evaluate(_GET_PX_CONTAINER_POSITION_JS)
        if raw and raw.get("w") and raw["w"] >= 70:
            return HoldTarget(
                x=float(raw["x"]), y=float(raw["y"]),
                width=float(raw["w"]), height=float(raw["h"]),
                source=f"container:{raw.get('source', 'px-container')}",
            )
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Press & Hold simulation
# ---------------------------------------------------------------------------


def _simulate_press_and_hold(
    page: Any,
    target: HoldTarget,
    cfg: PxConfig,
    attempt: int = 0,
) -> None:
    """Simulate a human press-and-hold on the target element (sync)."""
    hold_sec = random.uniform(cfg.hold_min, cfg.hold_max)
    tx = target.x + random.uniform(-target.width * 0.06, target.width * 0.06)
    ty = target.y + random.uniform(-target.height * 0.05, target.height * 0.05)

    logger.info(
        "PX hold attempt %d: moving to (%.0f, %.0f) via %s, holding %.1fs",
        attempt, tx, ty, target.source, hold_sec,
    )

    _human_move_to(page, tx, ty)
    time.sleep(random.uniform(0.06, 0.14))
    page.mouse.down(button="left")

    elapsed = 0.0
    while elapsed < hold_sec:
        chunk = random.uniform(0.12, 0.32)
        time.sleep(chunk)
        elapsed += chunk
        try:
            page.mouse.move(
                tx + random.uniform(-3.5, 3.5),
                ty + random.uniform(-2.5, 2.5),
            )
        except Exception:
            pass

    time.sleep(random.uniform(0.05, 0.15))
    page.mouse.up(button="left")
    logger.info("PX hold attempt %d: mouse.up after %.1fs", attempt, hold_sec)


async def _async_simulate_press_and_hold(
    page: Any,
    target: HoldTarget,
    cfg: PxConfig,
    attempt: int = 0,
) -> None:
    """Simulate a human press-and-hold on the target element (async)."""
    hold_sec = random.uniform(cfg.hold_min, cfg.hold_max)
    tx = target.x + random.uniform(-target.width * 0.06, target.width * 0.06)
    ty = target.y + random.uniform(-target.height * 0.05, target.height * 0.05)

    logger.info(
        "PX hold attempt %d: moving to (%.0f, %.0f) via %s, holding %.1fs",
        attempt, tx, ty, target.source, hold_sec,
    )

    await _async_human_move_to(page, tx, ty)
    await asyncio.sleep(random.uniform(0.06, 0.14))
    await page.mouse.down(button="left")

    elapsed = 0.0
    while elapsed < hold_sec:
        chunk = random.uniform(0.12, 0.32)
        await asyncio.sleep(chunk)
        elapsed += chunk
        try:
            await page.mouse.move(
                tx + random.uniform(-3.5, 3.5),
                ty + random.uniform(-2.5, 2.5),
            )
        except Exception:
            pass

    await asyncio.sleep(random.uniform(0.05, 0.15))
    await page.mouse.up(button="left")
    logger.info("PX hold attempt %d: mouse.up after %.1fs", attempt, hold_sec)


def _wait_px_cleared(page: Any, timeout: float) -> bool:
    """Wait for PX challenge UI to disappear (sync)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not is_px_visible(page):
            return True
        time.sleep(0.5)
    return not is_px_visible(page)


async def _async_wait_px_cleared(page: Any, timeout: float) -> bool:
    """Wait for PX challenge UI to disappear (async)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if not is_px_visible(page):
            return True
        await asyncio.sleep(0.5)
    return not is_px_visible(page)


# ---------------------------------------------------------------------------
# Main solver entry points
# ---------------------------------------------------------------------------


def attempt_px_solve(page: Any, cfg: PxConfig) -> bool:
    """Attempt to solve a PerimeterX challenge on the current page (sync).

    Args:
        page: Playwright Page object.
        cfg: PxConfig with solving parameters.

    Returns:
        True if the challenge was solved successfully. False if failed.
    """
    if not cfg.enabled:
        return True

    if not is_px_visible(page):
        logger.debug("No PX challenge visible, skipping solve")
        return True

    logger.info("PerimeterX challenge detected, attempting to solve...")

    if cfg.reload_if_hidden and is_px_block_page(page):
        logger.info("PX block page detected, reloading to load challenge...")
        try:
            page.reload(wait_until="load", timeout=90000)
        except Exception:
            page.reload(wait_until="domcontentloaded", timeout=90000)
        time.sleep(random.uniform(2.5, 4.5))

    # Wait for a target to appear
    target = None
    for _ in range(int(cfg.button_wait_timeout / 0.5)):
        if is_px_visible(page):
            target = _find_hold_target(page)
            if target is not None:
                break
        time.sleep(0.5)

    if target is None:
        logger.warning("PX hold target did not appear within timeout")
        return False

    # Perform press-and-hold attempts
    for attempt in range(1, cfg.max_attempts + 1):
        if not is_px_visible(page):
            logger.info("PX cleared before attempt %d", attempt)
            return True

        current_target = _find_hold_target(page)
        if current_target is None:
            current_target = target  # reuse last known position
            time.sleep(random.uniform(0.5, 1.0))

        try:
            _simulate_press_and_hold(page, current_target, cfg, attempt=attempt)
        except Exception as exc:
            logger.warning("Attempt %d failed: %s", attempt, exc)
            continue

        if _wait_px_cleared(page, cfg.post_wait):
            logger.info("PX solved after %d attempt(s)", attempt)
            if cfg.checker is not None:
                checker: Callable[[Any], bool] = cfg.checker
                check_deadline = time.monotonic() + cfg.app_ready_timeout
                while time.monotonic() < check_deadline:
                    if checker(page):
                        return True
                    time.sleep(0.8)
                logger.warning("Checker did not pass within timeout")
                return False
            return True

        logger.warning("Attempt %d: PX still visible", attempt)

    logger.error("All %d attempts failed", cfg.max_attempts)
    return False


async def async_attempt_px_solve(page: Any, cfg: PxConfig) -> bool:
    """Attempt to solve a PerimeterX challenge (async).

    Args:
        page: Playwright Page object (async API).
        cfg: PxConfig with solving parameters.

    Returns:
        True if solved, False if failed.
    """
    if not cfg.enabled:
        return True
    if not is_px_visible(page):
        logger.debug("No PX visible, skipping")
        return True

    logger.info("PX detected, solving...")

    if cfg.reload_if_hidden and is_px_block_page(page):
        logger.info("Reloading...")
        try:
            await page.reload(wait_until="load", timeout=90000)
        except Exception:
            await page.reload(wait_until="domcontentloaded", timeout=90000)
        await asyncio.sleep(random.uniform(2.5, 4.5))

    target = None
    for _ in range(int(cfg.button_wait_timeout / 0.5)):
        if is_px_visible(page):
            target = await _async_find_hold_target(page)
            if target is not None:
                break
        await asyncio.sleep(0.5)
    if target is None:
        logger.warning("Target not found")
        return False

    for attempt in range(1, cfg.max_attempts + 1):
        if not is_px_visible(page):
            return True
        current = await _async_find_hold_target(page) or target
        try:
            await _async_simulate_press_and_hold(page, current, cfg, attempt=attempt)
        except Exception as exc:
            logger.warning("Attempt %d failed: %s", attempt, exc)
            continue
        if await _async_wait_px_cleared(page, cfg.post_wait):
            logger.info("Solved after %d attempt(s)", attempt)
            if cfg.checker is not None:
                checker: Callable[[Any], bool] = cfg.checker
                loop = asyncio.get_running_loop()
                deadline = loop.time() + cfg.app_ready_timeout
                while loop.time() < deadline:
                    if checker(page):
                        return True
                    await asyncio.sleep(0.8)
                return False
            return True

    return False