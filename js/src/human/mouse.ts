/**
 * cloakbrowser-human — Human-like mouse movement and clicking.
 */

import { HumanConfig, rand, randRange, randIntRange, sleep } from './config.js';

// ---------------------------------------------------------------------------
// Raw interface — original Playwright methods, bypassing the wrapper
// ---------------------------------------------------------------------------

export interface RawMouse {
  move: (x: number, y: number) => Promise<void>;
  down: (options?: any) => Promise<void>;
  up: (options?: any) => Promise<void>;
  wheel: (deltaX: number, deltaY: number) => Promise<void>;
}

export interface RawKeyboard {
  down: (key: string) => Promise<void>;
  up: (key: string) => Promise<void>;
  type: (text: string) => Promise<void>;
  insertText: (text: string) => Promise<void>;
}

// ---------------------------------------------------------------------------
// Easing
// ---------------------------------------------------------------------------

function easeInOut(t: number): number {
  return t < 0.5
    ? 4 * t * t * t
    : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

// ---------------------------------------------------------------------------
// Bezier
// ---------------------------------------------------------------------------

interface Point {
  x: number;
  y: number;
}

function bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: number): Point {
  const u = 1 - t;
  const uu = u * u;
  const uuu = uu * u;
  const tt = t * t;
  const ttt = tt * t;
  return {
    x: uuu * p0.x + 3 * uu * t * p1.x + 3 * u * tt * p2.x + ttt * p3.x,
    y: uuu * p0.y + 3 * uu * t * p1.y + 3 * u * tt * p2.y + ttt * p3.y,
  };
}

function randomControlPoints(start: Point, end: Point): [Point, Point] {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const dist = Math.hypot(dx, dy);
  const px = -dy / (dist || 1);
  const py = dx / (dist || 1);
  const bias1 = rand(-0.3, 0.3) * dist;
  const bias2 = rand(-0.3, 0.3) * dist;
  return [
    { x: start.x + dx * 0.25 + px * bias1, y: start.y + dy * 0.25 + py * bias1 },
    { x: start.x + dx * 0.75 + px * bias2, y: start.y + dy * 0.75 + py * bias2 },
  ];
}

// ---------------------------------------------------------------------------
// Human mouse movement
// ---------------------------------------------------------------------------

export async function humanMove(
  raw: RawMouse,
  startX: number,
  startY: number,
  endX: number,
  endY: number,
  cfg: HumanConfig,
): Promise<void> {
  const dist = Math.hypot(endX - startX, endY - startY);
  if (dist < 1) return;

  const steps = Math.max(
    cfg.mouse_min_steps,
    Math.min(cfg.mouse_max_steps, Math.round(dist / cfg.mouse_steps_divisor)),
  );

  const start: Point = { x: startX, y: startY };
  const end: Point = { x: endX, y: endY };
  const [cp1, cp2] = randomControlPoints(start, end);

  let burstCounter = 0;
  const burstSize = randIntRange(cfg.mouse_burst_size);

  for (let i = 0; i <= steps; i++) {
    const progress = i / steps;
    const easedT = easeInOut(progress);
    const pt = bezier(start, cp1, cp2, end, easedT);

    const wobbleAmp = Math.sin(Math.PI * progress) * cfg.mouse_wobble_max;
    const wx = pt.x + (Math.random() - 0.5) * 2 * wobbleAmp;
    const wy = pt.y + (Math.random() - 0.5) * 2 * wobbleAmp;

    await raw.move(Math.round(wx), Math.round(wy));

    burstCounter++;
    if (burstCounter >= burstSize && i < steps) {
      await sleep(randRange(cfg.mouse_burst_pause));
      burstCounter = 0;
    }
  }

  if (Math.random() < cfg.mouse_overshoot_chance) {
    const overshootDist = randRange(cfg.mouse_overshoot_px);
    const angle = Math.atan2(endY - startY, endX - startX);
    const ovX = Math.round(endX + Math.cos(angle) * overshootDist);
    const ovY = Math.round(endY + Math.sin(angle) * overshootDist);
    await raw.move(ovX, ovY);
    await sleep(rand(30, 70));
    const corrX = Math.round(endX + (Math.random() - 0.5) * 4);
    const corrY = Math.round(endY + (Math.random() - 0.5) * 4);
    await raw.move(corrX, corrY);
  }
}

// ---------------------------------------------------------------------------
// Human click
// ---------------------------------------------------------------------------

export function clickTarget(
  box: { x: number; y: number; width: number; height: number },
  isInput: boolean,
  cfg: HumanConfig,
): Point {
  if (isInput) {
    const xFrac = randRange(cfg.click_input_x_range);
    const yFrac = rand(0.30, 0.70);
    return {
      x: Math.round(box.x + box.width * xFrac),
      y: Math.round(box.y + box.height * yFrac),
    };
  }
  const xFrac = rand(0.35, 0.65);
  const yFrac = rand(0.35, 0.65);
  return {
    x: Math.round(box.x + box.width * xFrac),
    y: Math.round(box.y + box.height * yFrac),
  };
}

export async function humanClick(
  raw: RawMouse,
  isInput: boolean,
  cfg: HumanConfig,
): Promise<void> {
  const aimDelay = isInput
    ? randRange(cfg.click_aim_delay_input)
    : randRange(cfg.click_aim_delay_button);
  await sleep(aimDelay);

  const holdTime = isInput
    ? randRange(cfg.click_hold_input)
    : randRange(cfg.click_hold_button);
  await raw.down();
  await sleep(holdTime);
  await raw.up();
}

// ---------------------------------------------------------------------------
// Human idle / drift
// ---------------------------------------------------------------------------

export async function humanIdle(
  raw: RawMouse,
  seconds: number,
  cx: number,
  cy: number,
  cfg: HumanConfig,
): Promise<void> {
  const endTime = Date.now() + seconds * 1000;
  let x = cx;
  let y = cy;
  while (Date.now() < endTime) {
    const dx = (Math.random() - 0.5) * 2 * cfg.idle_drift_px;
    const dy = (Math.random() - 0.5) * 2 * cfg.idle_drift_px;
    x += dx;
    y += dy;
    await raw.move(Math.round(x), Math.round(y));
    await sleep(randRange(cfg.idle_pause_range));
  }
}
