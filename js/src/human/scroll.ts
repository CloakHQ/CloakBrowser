/**
 * cloakbrowser-human — Human-like scrolling via mouse wheel events.
 */

import type { Page } from 'playwright-core';
import { HumanConfig, rand, randRange, randIntRange, sleep } from './config.js';
import { RawMouse, humanMove } from './mouse.js';
import { buildBoxJs, evalParsed, getWorld, OK, NOT_FOUND, UNSUPPORTED, VIEWPORT_JS } from './stealthDom.js';

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

async function smoothWheel(raw: RawMouse, delta: number, cfg: HumanConfig): Promise<void> {
  const absD = Math.abs(delta);
  const sign = delta > 0 ? 1 : -1;
  let sent = 0;
  while (sent < absD) {
    const stepSize = rand(20, 40);
    const chunk = Math.min(stepSize, absD - sent);
    await raw.wheel(0, Math.round(chunk) * sign);
    sent += chunk;
    await sleep(rand(8, 20));
  }
}

/**
 * Humanized scrolling that takes an arbitrary ``getBox`` callable.
 *
 * Used by both ``scrollToElement`` (selector-based) and the ElementHandle
 * ``scrollIntoViewIfNeeded`` patch so the same accelerate → cruise →
 * decelerate → overshoot behavior runs everywhere.
 */
export async function humanScrollIntoView(
  page: Page,
  raw: RawMouse,
  getBox: () => Promise<ElementBounds | null>,
  cursorX: number,
  cursorY: number,
  cfg: HumanConfig,
): Promise<{ box: ElementBounds; cursorX: number; cursorY: number; didScroll: boolean }> {
  // Headed launches default to no_viewport so the page tracks the real OS
  // window; page.viewportSize() is then null. Fall back to the live window
  // dimensions so humanize works headed (the stealth-relevant mode).
  let viewport = page.viewportSize();
  if (!viewport) {
    // Read the live window dimensions through the isolated world, consistent with
    // the other geometry reads here.
    const world = getWorld(page);
    if (world) {
      try { viewport = await world.evaluate(VIEWPORT_JS); } catch { /* fall back below */ }
    }
    if (!viewport) {
      viewport = await page.evaluate(
        () => ({ width: window.innerWidth, height: window.innerHeight }),
      );
    }
  }
  if (!viewport || !viewport.height) throw new Error('Viewport size not available');

  let box = await getBox();
  if (!box) throw new Error('Element not found while scrolling into view');

  if (isInViewport(box, viewport.height, cfg)) {
    return { box, cursorX, cursorY, didScroll: false };
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

  // Scroll loop: accelerate → cruise → decelerate
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

    // Check visibility every 3 steps
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

  // Settle
  await sleep(randRange(cfg.scroll_settle_delay));

  box = await getBox();
  if (!box) throw new Error('Element lost after scrolling into view');

  return { box, cursorX, cursorY, didScroll: true };
}

/**
 * Selector-based humanized scroll.
 *
 * ``timeout`` is forwarded to Playwright's ``boundingBox({ timeout })`` so
 * callers like ``page.click('#x', { timeout: 5000 })`` can wait longer for
 * slow-loading elements (#172). Default matches Playwright's 30000ms when not specified.
 *
 * Returns `{ box, cursorX, cursorY, didScroll }`.
 */
export async function scrollToElement(
  page: Page,
  raw: RawMouse,
  selector: string,
  cursorX: number,
  cursorY: number,
  cfg: HumanConfig,
  timeout?: number,
): Promise<{ box: ElementBounds; cursorX: number; cursorY: number; didScroll: boolean }> {
  return humanScrollIntoView(
    page, raw,
    () => getElementBox(page, selector, timeout),
    cursorX, cursorY, cfg,
  );
}

export async function getElementBox(
  page: Page,
  selector: string,
  timeout: number = 30000,
): Promise<ElementBounds | null> {
  // Read geometry through the isolated world when available; a not-found is retried
  // briefly in-world (SPA re-renders) and only an unsupported selector reaches
  // Playwright's boundingBox.
  const world = getWorld(page);
  if (world) {
    let { status, data } = await evalParsed(world, buildBoxJs(selector));
    if (status === OK) return data.box;
    if (status === NOT_FOUND) {
      const deadline = Date.now() + Math.min(timeout, 2000);
      while (Date.now() < deadline) {
        await sleep(50);
        ({ status, data } = await evalParsed(world, buildBoxJs(selector)));
        if (status === OK) return data.box;
        if (status === UNSUPPORTED) break;
      }
      if (status !== UNSUPPORTED) return null;
    }
    // UNSUPPORTED -> Playwright fallback below
  }
  const el = page.locator(selector).first();
  try {
    const box = await el.boundingBox({ timeout: Math.max(1, timeout) });
    return box;
  } catch {
    return null;
  }
}
