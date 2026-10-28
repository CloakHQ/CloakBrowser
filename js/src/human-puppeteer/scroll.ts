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

function isInViewportX(bounds: ElementBounds, viewportWidth: number): boolean {
  return bounds.x >= 0 && bounds.x + bounds.width <= viewportWidth;
}

/**
 * CSS pixels one wheel notch scrolls on `platform` (navigator.platform):
 * Chrome scrolls 100 px per notch on Windows (3 lines of 33.3 px), 40 on
 * macOS and 120 on Linux, and reports `wheelDelta` 120 per notch. CDP always
 * reports one notch per wheel event, so whole-notch events are the only ones
 * whose `deltaY` and `wheelDeltaY` agree.
 */
export function notchPxFor(platform: string, cfg: HumanConfig): number {
  if (cfg.scroll_notch_px && cfg.scroll_notch_px > 0) return cfg.scroll_notch_px;
  const p = (platform || '').toLowerCase();
  if (p.startsWith('mac')) return 40;
  if (p.startsWith('win')) return 100;
  return 120;
}

/** Notch size of `page`'s persona (cached per page). */
const notchCache = new WeakMap<object, string>();
export async function pageNotchPx(page: Page, cfg: HumanConfig): Promise<number> {
  let plat = notchCache.get(page);
  if (plat === undefined) {
    try {
      const stealth = (page as any)._stealth;
      plat = String(stealth ? await stealth.evaluate('navigator.platform') : await page.evaluate(() => navigator.platform)) || '';
    } catch { plat = ''; }
    notchCache.set(page, plat);
  }
  return notchPxFor(plat, cfg);
}

/**
 * Turn the wheel by about `delta` px in whole notches of `notch` px: flicks
 * of a few notches, quicker inside a flick, with a short pause between
 * flicks. Returns the distance actually wheeled (a whole number of notches).
 */
export async function smoothWheel(
  raw: RawMouse,
  delta: number,
  cfg: HumanConfig,
  axis: 'x' | 'y' = 'y',
  notch = 100,
): Promise<number> {
  const sign = delta > 0 ? 1 : -1;
  const notches = Math.round(Math.abs(delta) / notch);
  let flick = randIntRange([2, 5]);
  for (let i = 0; i < notches; i++) {
    const d = notch * sign;
    if (axis === 'x') await raw.wheel(d, 0);
    else await raw.wheel(0, d);
    if (i === notches - 1) break;
    if (--flick <= 0) {
      flick = randIntRange([2, 5]);
      await sleep(randRange(cfg.scroll_pause_slow) + rand(40, 120));
    } else {
      await sleep(randRange(cfg.scroll_pause_fast));
    }
  }
  return notches * notch * sign;
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
  // Headed launches default to null defaultViewport so the page tracks the real
  // OS window; page.viewport() is then null. Fall back to the live window
  // dimensions so humanize works headed (the stealth-relevant mode).
  let viewport = page.viewport();
  if (!viewport) {
    viewport = await page.evaluate(
      () => ({ width: window.innerWidth, height: window.innerHeight }),
    );
  }
  if (!viewport || !viewport.height) throw new Error('Viewport size not available');

  const notch = await pageNotchPx(page, cfg);
  const yPass = await scrollYIntoView(raw, getBox, viewport, cursorX, cursorY, cfg, notch);
  return scrollXIntoView(raw, getBox, yPass.box, viewport, yPass.cursorX, yPass.cursorY, cfg, notch);
}

/** Vertical pass: bring the box into ``scroll_target_zone``. */
async function scrollYIntoView(
  raw: RawMouse,
  getBox: () => Promise<ElementBounds | null>,
  viewport: { width: number; height: number },
  cursorX: number,
  cursorY: number,
  cfg: HumanConfig,
  notch: number,
): Promise<{ box: ElementBounds; cursorX: number; cursorY: number }> {
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

  // Wheel in whole notches, re-measuring between flicks, until the element
  // sits in the target zone (or the page stops moving).
  const targetY = viewport.height * rand(cfg.scroll_target_zone[0], cfg.scroll_target_zone[1]);
  let overshot = false;
  let stalled = 0;
  for (let round = 0; round < 40 && stalled < 2; round++) {
    const distance = box.y + box.height / 2 - targetY;
    if (Math.abs(distance) < notch / 2 || isInViewport(box, viewport.height, cfg)) break;
    const direction = distance > 0 ? 1 : -1;
    const flick = Math.min(Math.round(Math.abs(distance) / notch), randIntRange([2, 5]));
    const beforeY = box.y;
    await smoothWheel(raw, flick * notch * direction, cfg, 'y', notch);
    await sleep(randRange(cfg.scroll_pause_slow));
    const nb = await getBox();
    if (!nb) break;
    box = nb;
    stalled = Math.abs(box.y - beforeY) < 1 ? stalled + 1 : 0;
    if (!overshot && Math.random() < cfg.scroll_overshoot_chance &&
        Math.abs(box.y + box.height / 2 - targetY) < notch * 2) {
      // Optional overshoot + correction, in whole notches.
      overshot = true;
      const over = Math.max(1, Math.round(randRange(cfg.scroll_overshoot_px) / notch));
      await smoothWheel(raw, over * notch * direction, cfg, 'y', notch);
      await sleep(randRange(cfg.scroll_settle_delay));
      await smoothWheel(raw, -over * notch * direction, cfg, 'y', notch);
      await sleep(rand(100, 250));
      box = (await getBox()) ?? box;
    }
  }

  await sleep(randRange(cfg.scroll_settle_delay));

  box = await getBox();
  if (!box) throw new Error('Element lost after scrolling into view');

  return { box, cursorX, cursorY };
}

/**
 * Horizontal pass: bring the box inside the viewport width (#521).
 *
 * Only containment is checked here, not ``scroll_target_zone``: the zone is a
 * vertical reading position, and horizontal overflow is the exception.
 */
async function scrollXIntoView(
  raw: RawMouse,
  getBox: () => Promise<ElementBounds | null>,
  box: ElementBounds,
  viewport: { width: number; height: number },
  cursorX: number,
  cursorY: number,
  cfg: HumanConfig,
  notch: number,
): Promise<{ box: ElementBounds; cursorX: number; cursorY: number }> {
  if (isInViewportX(box, viewport.width)) {
    return { box, cursorX, cursorY };
  }

  const distanceToScroll = box.x + box.width / 2 - viewport.width / 2;
  // A box wider than the viewport is never contained; once centred, skip the near-zero wheel.
  if (Math.abs(distanceToScroll) < 1) {
    return { box, cursorX, cursorY };
  }

  const scrollAreaX = Math.round(viewport.width * rand(0.3, 0.7));
  const scrollAreaY = Math.round(viewport.height * rand(0.3, 0.7));
  await humanMove(raw, cursorX, cursorY, scrollAreaX, scrollAreaY, cfg);
  cursorX = scrollAreaX;
  cursorY = scrollAreaY;
  await sleep(randRange(cfg.scroll_pre_move_delay));

  await smoothWheel(raw, distanceToScroll, cfg, 'x', notch);
  await sleep(randRange(cfg.scroll_settle_delay));

  const finalBox = await getBox();
  if (!finalBox) throw new Error('Element lost after scrolling into view');
  return { box: finalBox, cursorX, cursorY };
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
