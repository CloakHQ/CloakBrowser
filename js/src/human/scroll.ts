/**
 * cloakbrowser-human — Human-like scrolling via mouse wheel events.
 */

import type { Page } from 'playwright-core';
import { HumanConfig, rand, randRange, randIntRange, sleep } from './config.js';
import { RawMouse, humanMove } from './mouse.js';

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

export async function scrollToElement(
  page: Page,
  raw: RawMouse,
  selector: string,
  cursorX: number,
  cursorY: number,
  cfg: HumanConfig,
): Promise<{ box: ElementBounds; cursorX: number; cursorY: number }> {
  const viewport = page.viewportSize();
  if (!viewport) throw new Error('Viewport size not available');

  let box = await getElementBox(page, selector);
  if (!box) {
    await sleep(200);
    box = await getElementBox(page, selector);
    if (!box) throw new Error(`Element not found: ${selector}`);
  }

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
      box = await getElementBox(page, selector);
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

  box = await getElementBox(page, selector);
  if (!box) throw new Error(`Element lost after scrolling: ${selector}`);

  return { box, cursorX, cursorY };
}

async function getElementBox(page: Page, selector: string): Promise<ElementBounds | null> {
  const el = page.locator(selector).first();
  try {
    const box = await el.boundingBox({ timeout: 2000 });
    return box;
  } catch {
    return null;
  }
}
