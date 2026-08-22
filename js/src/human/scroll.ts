/**
 * cloakbrowser-human — Human-like scrolling via mouse wheel events.
 *
 * Selector geometry and live DOM scroll state are read only through the CDP
 * isolated world. ElementHandle callers may still supply their own exact box.
 */

import type { Page } from 'playwright-core';
import { type HumanConfig, rand, randRange, randIntRange, sleep } from './config.js';
import { type RawMouse, humanMove } from './mouse.js';
import {
  buildBoxJs, evalParsed, getWorld, OK, NOT_FOUND, UNSUPPORTED,
  EVALUATION_FAILED, VIEWPORT_JS, StealthEvaluationError,
  StealthWorldUnavailableError, UnsupportedHumanizeSelectorError,
} from './stealthDom.js';

export interface ElementBounds {
  x: number;
  y: number;
  width: number;
  height: number;
  targetId?: number;
}

export interface SelectorBounds extends ElementBounds {
  targetId: number;
  gen: number;
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

const SCROLL_JS =
  '(() => { const e = document.scrollingElement || document.documentElement;' +
  ' return { y: window.scrollY, maxY: Math.max(0, e.scrollHeight - e.clientHeight) }; })()';

async function readScrollState(page: Page): Promise<{ y: number; maxY: number }> {
  const world = getWorld(page);
  if (!world) throw new StealthWorldUnavailableError();
  try {
    const state = await world.evaluate(SCROLL_JS);
    if (
      !state || typeof state !== 'object' ||
      typeof state.y !== 'number' || typeof state.maxY !== 'number'
    ) {
      throw new StealthEvaluationError('<scroll-state>');
    }
    return state;
  } catch (error) {
    if (error instanceof StealthEvaluationError) throw error;
    throw new StealthEvaluationError('<scroll-state>');
  }
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

export async function humanScrollIntoView<T extends ElementBounds>(
  page: Page,
  raw: RawMouse,
  getBox: () => Promise<T | null>,
  cursorX: number,
  cursorY: number,
  cfg: HumanConfig,
): Promise<{ box: T; cursorX: number; cursorY: number; didScroll: boolean }> {
  let viewport = page.viewportSize();
  if (!viewport) {
    const world = getWorld(page);
    if (!world) throw new StealthWorldUnavailableError();
    try {
      viewport = await world.evaluate(VIEWPORT_JS);
    } catch {
      throw new StealthEvaluationError('<viewport>');
    }
  }
  if (!viewport || !viewport.height) throw new Error('Viewport size not available');

  let box = await getBox();
  if (!box) throw new Error('Element not found while scrolling into view');

  if (isInViewport(box, viewport.height, cfg)) {
    return { box, cursorX, cursorY, didScroll: false };
  }

  const fullyVisible = box.y >= 0 && box.y + box.height <= viewport.height;
  if (fullyVisible) {
    const zoneMid = viewport.height * (cfg.scroll_target_zone[0] + cfg.scroll_target_zone[1]) / 2;
    const needUp = box.y + box.height / 2 < zoneMid;
    const { y, maxY } = await readScrollState(page);
    if (needUp ? y <= 0 : y >= maxY) {
      return { box, cursorX, cursorY, didScroll: false };
    }
  }

  const scrollAreaX = Math.round(viewport.width * rand(0.3, 0.7));
  const scrollAreaY = Math.round(viewport.height * rand(0.3, 0.7));
  await humanMove(raw, cursorX, cursorY, scrollAreaX, scrollAreaY, cfg);
  cursorX = scrollAreaX;
  cursorY = scrollAreaY;
  await sleep(randRange(cfg.scroll_pre_move_delay));

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
      const nextBox = await getBox();
      if (nextBox) box = nextBox;
      if (nextBox && isInViewport(nextBox, viewport.height, cfg)) break;
    }
    if (scrolled >= absDistance * 1.1) break;
  }

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

  const finalBox = await getBox();
  if (!finalBox) throw new Error('Element lost after scrolling into view');
  return { box: finalBox, cursorX, cursorY, didScroll: true };
}

export async function scrollToElement(
  page: Page,
  raw: RawMouse,
  selector: string,
  cursorX: number,
  cursorY: number,
  cfg: HumanConfig,
  timeout: number = 30000,
): Promise<{ box: SelectorBounds; cursorX: number; cursorY: number; didScroll: boolean }> {
  return humanScrollIntoView(
    page,
    raw,
    () => getElementBox(page, selector, timeout),
    cursorX,
    cursorY,
    cfg,
  );
}

export async function getElementBox(
  page: Page,
  selector: string,
  timeout: number = 30000,
): Promise<SelectorBounds | null> {
  const world = getWorld(page);
  if (!world) throw new StealthWorldUnavailableError();

  const deadline = Date.now() + Math.max(0, timeout);
  let result = await evalParsed(world, buildBoxJs(selector));
  while (
    (result.status === NOT_FOUND || result.status === EVALUATION_FAILED) &&
    Date.now() < deadline
  ) {
    await sleep(50);
    result = await evalParsed(world, buildBoxJs(selector));
  }

  const { status, data } = result;
  if (status === OK && data?.box && Number.isInteger(data.targetId) && Number.isInteger(data.gen)) {
    return { ...data.box, targetId: data.targetId, gen: data.gen };
  }
  if (status === NOT_FOUND) return null;
  if (status === UNSUPPORTED) throw new UnsupportedHumanizeSelectorError(selector);
  throw new StealthEvaluationError(selector);
}
