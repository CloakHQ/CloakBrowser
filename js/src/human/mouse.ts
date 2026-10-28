/**
 * cloakbrowser-human — Human-like mouse movement and clicking.
 */

import { HumanConfig, rand, randLognormal, randRange, sleep } from './config.js';

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

export function easeInOut(t: number): number {
  return t < 0.5
    ? 4 * t * t * t
    : 1 - Math.pow(-2 * t + 2, 3) / 2;
}

// ---------------------------------------------------------------------------
// Bezier
// ---------------------------------------------------------------------------

export interface Point {
  x: number;
  y: number;
}

export function bezier(p0: Point, p1: Point, p2: Point, p3: Point, t: number): Point {
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

export function randomControlPoints(start: Point, end: Point, curvature = 0.3): [Point, Point] {
  const dx = end.x - start.x;
  const dy = end.y - start.y;
  const dist = Math.hypot(dx, dy);
  const px = -dy / (dist || 1);
  const py = dx / (dist || 1);
  // Both control points bend the same way more often than not: a hand sweeps
  // an arc, it rarely draws an S.
  const bias1 = rand(-curvature, curvature) * dist;
  const bias2 = Math.random() < 0.8 ? bias1 * rand(0.2, 1.2) : rand(-curvature, curvature) * dist;
  return [
    { x: start.x + dx * 0.25 + px * bias1, y: start.y + dy * 0.25 + py * bias1 },
    { x: start.x + dx * 0.75 + px * bias2, y: start.y + dy * 0.75 + py * bias2 },
  ];
}

// ---------------------------------------------------------------------------
// Stroke planning (shared by the humanize engine and humanMove)
// ---------------------------------------------------------------------------
//
// A pointing movement is a fast main stroke whose speed peaks early, then a
// slow approach to the target, often finished by a short corrective stroke
// (Meyer's optimised sub-movements; Plamondon's log-normal strokes). How long
// it takes grows with log2 of the distance (Fitts' law) and varies a lot from
// one move to the next. A mouse reports its position at a steady rate and
// only when it actually moved.

/** One planned pointer event: position and ms since the previous one. */
export type MovePoint = [x: number, y: number, dt: number];

export const FRAME_MS = 1000 / 60; // pointer events arrive about once per display frame
const PEAK: [number, number] = [0.22, 0.38]; // where the speed peaks (fraction of the stroke time)

/** Smooth 0->1 distance curve whose speed peaks at `peak` of the time
 * (a time-warped minimum-jerk profile: fast early, long slow tail). */
function progressCurve(peak: number): (t: number) => number {
  const k = Math.log(0.5) / Math.log(peak); // u = t**k puts the mid point at peak
  return (t: number) => {
    const u = Math.pow(t, k);
    return u * u * u * (10 - 15 * u + 6 * u * u);
  };
}

/** Milliseconds for a `dist` px stroke (Fitts' law, log-normal spread). */
export function strokeDuration(dist: number, cfg: HumanConfig): number {
  const median = cfg.mouse_time_base + cfg.mouse_time_per_bit * Math.log2(1 + dist / 8);
  return Math.max(FRAME_MS * 2, randLognormal(median, cfg.mouse_time_spread));
}

/** Points of one stroke; the last point is exactly (ex, ey). Consecutive
 * points always differ by a pixel or more (a mouse does not report a move
 * without movement). */
export function planStroke(sx: number, sy: number, ex: number, ey: number, cfg: HumanConfig,
  duration?: number): MovePoint[] {
  const dist = Math.hypot(ex - sx, ey - sy);
  if (dist < 0.5) return [];
  const total = duration ?? strokeDuration(dist, cfg);
  const n = Math.max(1, Math.trunc(Math.max(cfg.mouse_min_steps, Math.min(cfg.mouse_max_steps, Math.round(total / FRAME_MS)))));
  const start = { x: sx, y: sy }, end = { x: ex, y: ey };
  const [cp1, cp2] = randomControlPoints(start, end, 0.12);
  const curve = progressCurve(rand(PEAK[0], PEAK[1]));
  // Low-frequency sideways drift (a hand is not a ruler), zero at both ends.
  const ux = (ex - sx) / dist, uy = (ey - sy) / dist;
  const amp = Math.min(cfg.mouse_wobble_max, dist * 0.02) * rand(-1, 1);
  const waves = rand(0.5, 1.5), phase = rand(0, Math.PI);
  const out: MovePoint[] = [];
  let lx = sx, ly = sy, tPrev = 0;
  for (let i = 1; i <= n; i++) {
    // Frame timing jitters a little; the final event lands on the target.
    const t = Math.min(1, (i + (i < n ? rand(-0.2, 0.2) : 0)) / n);
    let x: number, y: number;
    if (i === n) {
      x = ex; y = ey;
      if (Math.abs(x - lx) < 1 && Math.abs(y - ly) < 1) {
        if (!out.length) break; // already there (sub-pixel move): nothing to report
        // The last frame already got there: land exactly on it instead.
        const [, , pdt] = out.pop()!;
        out.push([x, y, pdt + (t - tPrev) * total]);
        break;
      }
    } else {
      const p = bezier(start, cp1, cp2, end, curve(t));
      const w = amp * Math.sin(Math.PI * t) * Math.sin(phase + 2 * Math.PI * waves * t);
      x = Math.round(p.x - uy * w); y = Math.round(p.y + ux * w);
      if (Math.abs(x - lx) < 1 && Math.abs(y - ly) < 1) continue;
    }
    out.push([x, y, (t - tPrev) * total]);
    tPrev = t; lx = x; ly = y;
  }
  return out;
}

/** A whole move: main stroke, and sometimes a miss near the target plus a
 * short corrective stroke onto it. */
export function planMove(sx: number, sy: number, ex: number, ey: number, cfg: HumanConfig): MovePoint[] {
  const dist = Math.hypot(ex - sx, ey - sy);
  if (dist < 0.5) return [];
  if (dist > 40 && Math.random() < cfg.mouse_overshoot_chance) {
    // Land a little past (or short of) the target, slightly off-line.
    const ang = Math.atan2(ey - sy, ex - sx) + rand(-0.25, 0.25);
    let miss = dist * rand(0.01, 0.05) + randRange(cfg.mouse_overshoot_px);
    if (Math.random() < 0.3) miss = -miss; // undershoot
    const mx = Math.round(ex + Math.cos(ang) * miss), my = Math.round(ey + Math.sin(ang) * miss);
    const pts = planStroke(sx, sy, mx, my, cfg);
    const corr = Math.hypot(ex - mx, ey - my);
    const pause = rand(40, 140);
    const tail = planStroke(mx, my, ex, ey, cfg,
      Math.max(FRAME_MS * 2, randLognormal(90 + 25 * Math.log2(1 + corr), 0.3)));
    if (tail.length) tail[0] = [tail[0][0], tail[0][1], tail[0][2] + pause];
    return pts.concat(tail);
  }
  return planStroke(sx, sy, ex, ey, cfg);
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
  let clock = Date.now();
  for (const [x, y, dt] of planMove(startX, startY, endX, endY, cfg)) {
    clock += dt;
    const wait = clock - Date.now();
    if (wait > 0) await sleep(wait);
    await raw.move(x, y);
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

export function humanIdle(
  raw: RawMouse,
  cx: number,
  cy: number,
  cfg: HumanConfig,
): Promise<void>;
export function humanIdle(
  raw: RawMouse,
  seconds: number,
  cx: number,
  cy: number,
  cfg: HumanConfig,
): Promise<void>;
export async function humanIdle(
  raw: RawMouse,
  secondsOrCx: number,
  cxOrCy: number,
  cyOrCfg: number | HumanConfig,
  maybeCfg?: HumanConfig,
): Promise<void> {
  const hasExplicitSeconds = maybeCfg !== undefined;
  const seconds = hasExplicitSeconds
    ? secondsOrCx
    : rand((cyOrCfg as HumanConfig).idle_between_duration[0], (cyOrCfg as HumanConfig).idle_between_duration[1]);
  const cx = hasExplicitSeconds ? cxOrCy : secondsOrCx;
  const cy = hasExplicitSeconds ? (cyOrCfg as number) : cxOrCy;
  const cfg = hasExplicitSeconds ? maybeCfg! : (cyOrCfg as HumanConfig);
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
