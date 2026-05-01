/**
 * cloakbrowser-human — Human-like scrolling via mouse wheel events.
 * Adapted for Puppeteer API.
 *
 * Changes from Playwright version:
 *   - page.viewport() instead of page.viewportSize()
 *   - page.$(selector) + el.boundingBox() instead of page.locator().boundingBox()
 *   - boundingBox() has no timeout param — we poll page.$() up to ``timeout`` ms
 */

import type { Page } from 'puppeteer-core';
import type { HumanConfig } from '../human/config.js';
import { rand, randRange, randIntRange, sleep } from '../human/config.js';
import { RawMouse, humanMove } from '../human/mouse.js';

interface ElementBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

function isInViewport(
  bounds: ElementBounds,
  viewportHeight: number,
  cfg: HumanConfig,
): boolean {
  const topEdge = bounds.y;
  const bottomEdge = bounds.y + bounds.height;
  const zoneTop = viewportHeight * cfg.scroll_target_zone[0];
  const zoneBottom = viewportHeight * cfg.scroll_target_zone[1];
  return topEdge >= zoneTop && bottomEdge <= zoneBottom;
}

export async function smoothWheel(
  raw: RawMouse,
  delta: number,
  cfg: HumanConfig,
  axis: 'x' | 'y' = 'y',
): Promise<void> {
  const absD = Math.abs(delta);
  const sign = delta > 0 ? 1 : -1;
  let sent = 0;
  while (sent < absD) {
    const stepSize = rand(20, 40);
    const chunk = Math.min(stepSize, absD - sent);
    const d = Math.round(chunk) * sign;
    if (axis === 'x') {
      await raw.wheel(d, 0);
    } else {
      await raw.wheel(0, d);
    }
    sent += chunk;
    await sleep(rand(8, 20));
  }
}

/**
 * Poll ``page.$(selector)`` for up to ``timeout`` ms, returning the element's
 * bounding box when found. ``timeout`` defaults to 30000ms when not specified.
 */
async function getElementBox(
  page: Page,
  selector: string,
  timeout: number = 30000,
): Promise<ElementBounds | null> {
  const start = Date.now();
  const pollInterval = 100;
  while (true) {
    try {
      const el = await page.$(selector);
      if (el) {
        const box = await el.boundingBox();
        if (box) return { x: box.x, y: box.y, width: box.width, height: box.height };
      }
    } catch { /* keep polling */ }

    if (Date.now() - start >= timeout) return null;
    await sleep(pollInterval);
  }
}

/**
 * Humanized scrolling that takes an arbitrary ``getBox`` callable.
 * Used by both ``scrollToElement`` (selector-based) and the ElementHandle
 * ``scrollIntoView`` patch.
 */
export async function humanScrollIntoView(
  page: Page,
  raw: RawMouse,
  getBox: () => Promise<ElementBounds | null>,
  cursorX: number,
  cursorY: number,
  cfg: HumanConfig,
): Promise<{ box: ElementBounds; cursorX: number; cursorY: number }> {
  const viewport = page.viewport();
  if (!viewport) throw new Error('Viewport size not available');

  let box = await getBox();
  if (!box) throw new Error('Element not found while scrolling into view');

  if (isInViewport(box, viewport.height, cfg)) {
    return { box, cursorX, cursorY };
  }

  // Move cursor into scroll area
  const scrollAreaX = Math.round(viewport.width * rand(0.3, 0.7));
  const scrollAreaY = Math.round(viewport.height * rand(0.3, 0.7));
  await humanMove(raw, cursorX, cursorY, scrollAreaX, scrollAreaY, cfg);
  cursorX = scrollAreaX;
  cursorY = scrollAreaY;
  await sleep(randRange(cfg.scroll_pre_move_delay));

  // Calculate scroll distance
  const targetY = viewport.height * rand(cfg.scroll_target_zone[0], cfg.scroll_target_zone[1]);
  const elementCenter = box.y + box.height / 2;
  const distanceToScroll = elementCenter - targetY;

  const direction = distanceToScroll > 0 ? 1 : -1;
  const absDistance = Math.abs(distanceToScroll);
  const avgDelta = (cfg.scroll_delta_base[0] + cfg.scroll_delta_base[1]) / 2;
  const totalClicks = Math.max(3, Math.ceil(absDistance / avgDelta));
  const accelSteps = randIntRange(cfg.scroll_accel_steps);
  const decelSteps = randIntRange(cfg.scroll_decel_steps);

  let scrolled = 0;

  for (let i = 0; i < totalClicks; i++) {
    let delta: number;
    let pause: number;

    if (i < accelSteps) {
      delta = rand(80, 100);
      pause = randRange(cfg.scroll_pause_slow);
    } else if (i >= totalClicks - decelSteps) {
      delta = rand(60, 90);
      pause = randRange(cfg.scroll_pause_slow);
    } else {
      delta = randRange(cfg.scroll_delta_base);
      pause = randRange(cfg.scroll_pause_fast);
    }

    delta *= 1 + (Math.random() - 0.5) * 2 * cfg.scroll_delta_variance;
    delta = Math.round(delta) * direction;

    await smoothWheel(raw, delta, cfg);
    scrolled += Math.abs(delta);
    await sleep(pause);

    if (i % 3 === 2 || i === totalClicks - 1) {
      box = await getBox();
      if (box && isInViewport(box, viewport.height, cfg)) {
        break;
      }
    }

    if (scrolled >= absDistance * 1.1) break;
  }

  // Optional overshoot + correction
  if (Math.random() < cfg.scroll_overshoot_chance) {
    const overshootPx = Math.round(randRange(cfg.scroll_overshoot_px)) * direction;
    await smoothWheel(raw, overshootPx, cfg);
    await sleep(randRange(cfg.scroll_settle_delay));

    const corrections = randIntRange([1, 2]);
    for (let c = 0; c < corrections; c++) {
      const corrDelta = Math.round(rand(40, 80)) * -direction;
      await smoothWheel(raw, corrDelta, cfg);
      await sleep(rand(100, 250));
    }
  }

  await sleep(randRange(cfg.scroll_settle_delay));

  box = await getBox();
  if (!box) throw new Error('Element lost after scrolling into view');

  return { box, cursorX, cursorY };
}

/**
 * Selector-based humanized scroll (Puppeteer).
 *
 * ``timeout`` controls how long we poll ``page.$(selector)`` before giving up,
 * so callers like ``page.click('#x', { timeout: 5000 })`` can wait longer for
 * slow-loading elements (#172). Default matches Playwright's 30000ms when not specified.
 */
export async function scrollToElement(
  page: Page,
  raw: RawMouse,
  selector: string,
  cursorX: number,
  cursorY: number,
  cfg: HumanConfig,
  timeout?: number,
): Promise<{ box: ElementBounds; cursorX: number; cursorY: number }> {
  return humanScrollIntoView(
    page, raw,
    () => getElementBox(page, selector, timeout),
    cursorX, cursorY, cfg,
  );
}
