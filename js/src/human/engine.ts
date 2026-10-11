/**
 * Unified humanized action pipeline. Port of cloakbrowser/human/engine.py.
 *
 * One implementation drives page / frame / locator / element-handle actions:
 *
 *   resolve (isolated world, Playwright selector engine, strict mode)
 *     -> wait for element states (visible / enabled / editable / stable)
 *     -> scroll into view with mouse-wheel bursts (page, iframes, containers)
 *     -> Bezier move to a point inside the visible part of the element
 *     -> hit-target check (element itself, and every ancestor <iframe>)
 *     -> press / type
 *
 * Nothing falls back to Playwright's stock actions, and failures raise
 * Playwright `Error` / `TimeoutError`.
 */

import type { Frame, Page, ElementHandle, CDPSession } from 'playwright-core';
import { errors } from 'playwright-core';
import { type HumanConfig, mergeConfig, rand, randRange, randIntRange, sleep } from './config.js';
import { NEARBY_KEYS, SHIFT_SYMBOLS, SHIFT_SYMBOL_CODES, SHIFT_SYMBOL_KEYCODES } from './keyboard.js';
import { bezier, easeInOut, randomControlPoints, clickTarget } from './mouse.js';
import * as fields from './fields.js';
import { HELPERS, StaleElement, Worlds, intersect, type Rect } from './world.js';

const ENTER_FRAME_SPLIT = /\s*>>\s*internal:control=enter-frame\s*>>\s*/;

const CLICK_STATES = ['visible', 'enabled', 'stable'];
const HOVER_STATES = ['visible', 'stable'];
const INPUT_STATES = ['visible', 'enabled', 'editable'];
const FOCUS_STATES = ['visible', 'enabled'];
const RETRY_MS = [0, 20, 100, 100, 500];

const sleepMs = (ms: number) => (ms > 0 ? sleep(ms) : Promise.resolve());

export class CursorState {
  x = 0;
  y = 0;
  initialized = false;
}

/** Original (un-humanized) input primitives of one page. */
export interface RawInput {
  move(x: number, y: number, options?: { steps?: number }): Promise<void>;
  down(options?: { button?: string; clickCount?: number }): Promise<void>;
  up(options?: { button?: string; clickCount?: number }): Promise<void>;
  wheel(dx: number, dy: number): Promise<void>;
  keyDown(key: string): Promise<void>;
  keyUp(key: string): Promise<void>;
  keyPress(key: string, options?: { delay?: number }): Promise<void>;
  insertText(text: string): Promise<void>;
}

// ---------------------------------------------------------------------------
// Targets
// ---------------------------------------------------------------------------

export class Target {
  description: string;
  constructor(public frame: Frame, public selector: string | null = null, public strict = false,
              public handle: ElementHandle | null = null) {
    this.description = selector !== null ? `locator(${JSON.stringify(selector)})` : 'element handle';
  }
}

export class Resolved {
  constructor(public frame: Frame, public id: number) {}
}

export class Deadline {
  private end: number | null;
  constructor(public timeout: number) {
    this.end = timeout ? Date.now() + timeout : null;
  }
  remaining(): number { return this.end === null ? Infinity : Math.max(0, this.end - Date.now()); }
  /** Remaining budget as a Playwright timeout value (0 = no limit). */
  left(): number { return this.end === null ? 0 : Math.max(1, this.remaining()); }
  expired(): boolean { return this.end !== null && Date.now() >= this.end; }
}

/** Internal: the current attempt failed for `reason`; retry until timeout. */
class Retry extends Error {
  constructor(public reason: string) { super(reason); }
}

/** A read / dispatchEvent on an ElementHandle the isolated world cannot locate
 * (no box: hidden; or a box shared with another element). The patched method
 * runs Playwright's own call instead, which reads hidden elements. Also a
 * dispatchEvent whose eventInit holds a JSHandle (it lives in the page's main
 * world, where Playwright dispatches). */
export class RawFallback extends Error {}

/** A JSHandle (or ElementHandle) anywhere in `v`. */
function hasHandle(v: any): boolean {
  if (!v || typeof v !== 'object') return false;
  if (typeof v.jsonValue === 'function' && typeof v.evaluateHandle === 'function') return true;
  return Object.values(v).some(hasHandle);
}

/** Options every humanized action understands (Playwright names + ours). */
export interface Opts {
  timeout?: number;
  force?: boolean;
  trial?: boolean;
  position?: { x: number; y: number } | null;
  button?: 'left' | 'right' | 'middle';
  clickCount?: number;
  delay?: number;
  modifiers?: string[];
  steps?: number;
  sourcePosition?: { x: number; y: number };
  targetPosition?: { x: number; y: number };
  human_config?: Partial<HumanConfig> | null;
  [k: string]: any;
  /** internal */
  _deadline?: Deadline;
  _nested?: boolean;
  _aim?: any[];
  scroll?: string;
}

const err = (msg: string) => new Error(msg);

type Action = (r: Resolved, x: number, y: number, cfg: HumanConfig) => Promise<void>;
type Box = Rect & { bl: number; bt: number; clip: Rect; visible: Rect; scroller?: Rect };

const isAsciiAlnum = (ch: string) => /^[a-zA-Z0-9]$/.test(ch);
const isAscii = (ch: string) => (ch.codePointAt(0) ?? 128) < 128;
const isUpper = (ch: string) => /^[A-Z]$/.test(ch);

// ---------------------------------------------------------------------------
// Human
// ---------------------------------------------------------------------------

export class Human {
  readonly worlds: Worlds;
  /** Date.now() until which the browser joins typed letters into one type-ahead search. */
  private typeAheadUntil = 0;
  private _platform: string | null = null;
  private handleIds = new Map<string, [Frame, number, number]>();

  constructor(readonly page: Page, public cfg: HumanConfig, public cursor: CursorState, readonly raw: RawInput) {
    this.worlds = new Worlds(page);
  }

  // -- configuration ------------------------------------------------------

  callCfg(overrides?: Partial<HumanConfig> | null): HumanConfig {
    return mergeConfig(this.cfg, overrides ?? undefined);
  }

  timeout(frame: Frame, timeout?: number): number {
    const t = (frame as any)._timeout({ timeout });
    return typeof t === 'number' ? t : t.timeout;
  }

  /** Deadline for an action; nested sub-actions share their caller's. */
  deadline(target: Target, opts: Opts): Deadline {
    return opts._deadline ?? new Deadline(this.timeout(target.frame, opts.timeout));
  }

  /** Persona platform (`navigator.platform` read in the isolated world). */
  async platform(): Promise<string> {
    if (this._platform === null) {
      try { this._platform = String(await this.worlds.call(this.page.mainFrame(), 'platform')); }
      catch { this._platform = ''; }
    }
    return this._platform;
  }

  async isMac(): Promise<boolean> { return (await this.platform()).toLowerCase().startsWith('mac'); }
  async selectAllKey(): Promise<string> { return (await this.isMac()) ? 'Meta+a' : 'Control+a'; }

  private async modifier(key: string): Promise<string> {
    if (key === 'ControlOrMeta') return (await this.isMac()) ? 'Meta' : 'Control';
    return key;
  }

  // -- cursor -------------------------------------------------------------

  async ensureCursor(cfg?: HumanConfig): Promise<void> {
    if (!this.cursor.initialized) {
      const c = cfg ?? this.cfg;
      this.cursor.x = rand(c.initial_cursor_x[0], c.initial_cursor_x[1]);
      this.cursor.y = rand(c.initial_cursor_y[0], c.initial_cursor_y[1]);
      await this.raw.move(this.cursor.x, this.cursor.y);
      this.cursor.initialized = true;
    }
  }

  /** Bezier move from the current cursor position to (x, y). */
  async moveTo(x: number, y: number, cfg: HumanConfig): Promise<void> {
    await this.ensureCursor(cfg);
    const sx = this.cursor.x, sy = this.cursor.y;
    const dist = Math.hypot(x - sx, y - sy);
    if (dist >= 1) {
      const steps = Math.max(cfg.mouse_min_steps, Math.min(cfg.mouse_max_steps, Math.round(dist / cfg.mouse_steps_divisor)));
      const start = { x: sx, y: sy }, end = { x, y };
      const [cp1, cp2] = randomControlPoints(start, end);
      let burst = 0;
      const burstSize = randIntRange(cfg.mouse_burst_size);
      for (let i = 1; i <= steps; i++) {
        const progress = i / steps;
        if (i === steps) { await this.raw.move(x, y); continue; } // exact end point
        const pt = bezier(start, cp1, cp2, end, easeInOut(progress));
        const wobble = Math.sin(Math.PI * progress) * cfg.mouse_wobble_max;
        await this.raw.move(Math.round(pt.x + (Math.random() - 0.5) * 2 * wobble),
          Math.round(pt.y + (Math.random() - 0.5) * 2 * wobble));
        burst++;
        if (burst >= burstSize) { await sleepMs(randRange(cfg.mouse_burst_pause)); burst = 0; }
      }
      if (Math.random() < cfg.mouse_overshoot_chance) {
        const angle = Math.atan2(y - sy, x - sx);
        const over = randRange(cfg.mouse_overshoot_px);
        await this.raw.move(Math.round(x + Math.cos(angle) * over), Math.round(y + Math.sin(angle) * over));
        await sleepMs(rand(30, 70));
        await this.raw.move(x, y);
      }
    }
    this.cursor.x = x; this.cursor.y = y;
  }

  async idle(cfg: HumanConfig): Promise<void> {
    if (!cfg.idle_between_actions) return;
    await this.ensureCursor(cfg);
    const end = Date.now() + rand(cfg.idle_between_duration[0], cfg.idle_between_duration[1]) * 1000;
    let x = this.cursor.x, y = this.cursor.y;
    while (Date.now() < end) {
      x += (Math.random() - 0.5) * 2 * cfg.idle_drift_px;
      y += (Math.random() - 0.5) * 2 * cfg.idle_drift_px;
      await this.raw.move(Math.round(x), Math.round(y));
      await sleepMs(Math.min(randRange(cfg.idle_pause_range), Math.max(0, end - Date.now())));
    }
    // Drift is noise around the resting point, not a new position.
    await this.raw.move(this.cursor.x, this.cursor.y);
  }

  // -- resolution ---------------------------------------------------------

  /** Resolve once. Throws `Retry` (not yet there) or `Error` (final). */
  async resolve(target: Target, deadline: Deadline): Promise<Resolved> {
    if (target.handle) return this.resolveHandle(target.handle, deadline);
    let frame = target.frame;
    const parts = target.selector!.split(ENTER_FRAME_SPLIT);
    for (let i = 0; i < parts.length; i++) {
      const res = await this.worlds.call(frame, 'resolve', parts[i], !!target.strict, 0);
      if (res.status === 'none') throw new Retry(`waiting for ${target.description}`);
      if (res.status === 'strict' || res.status === 'error') throw err(res.message);
      if (i === parts.length - 1) return new Resolved(frame, res.id);
      const child = await this.worlds.contentFrame(frame, res.id);
      if (!child) throw new Retry(`waiting for the frame of ${target.description}`);
      frame = child;
    }
    throw err('unreachable');
  }

  /** `exact` (reads): skip the cache (it may hold a click's pick from a
   * same-box chain) and accept only the one element with this box; anything
   * else throws RawFallback. */
  async resolveHandle(handle: ElementHandle, _deadline?: Deadline, exact = false): Promise<Resolved> {
    const frame: Frame = (handle as any)._frame;
    const rec = await this.worlds.ready(frame);
    const guid: string = (handle as any)._guid;
    const cached = this.handleIds.get(guid);
    if (!exact && cached && cached[0] === frame && cached[1] === rec.ctx) return new Resolved(frame, cached[2]);
    // An ElementHandle carries no identity our context can read, so find
    // the element with exactly its border box.
    const box = await handle.boundingBox();
    if (!box) {
      if (exact) throw new RawFallback();
      // Resolved in an earlier document of this frame and gone now
      // (a same-document navigation keeps the element, and its box).
      if (cached && cached[0] === frame) throw err('Element is not attached to the DOM');
      throw new Retry('element is not visible');
    }
    const [ox, oy] = await this.worlds.frameGeometry(frame);
    const res = await this.worlds.call(frame, 'matchRect', box.x - ox, box.y - oy, box.width, box.height, exact);
    if (res.count !== 1) {
      if (exact) throw new RawFallback();
      throw err('cloakbrowser humanize: cannot identify the element behind this ElementHandle inside the ' +
        'isolated world (it shares its box with another element); use a Locator instead');
    }
    this.handleIds.set(guid, [frame, rec.ctx!, res.id]);
    return new Resolved(frame, res.id);
  }

  /** Resolve and wait for `states`; Playwright-style retry + timeout. */
  waitFor(target: Target, states: string[], deadline: Deadline, api: string, force = false): Promise<Resolved> {
    return this.retry(api, target, deadline, () => this.attemptStates(target, states, deadline, force));
  }

  async attemptStates(target: Target, states: string[], deadline: Deadline, force: boolean): Promise<Resolved> {
    const r = await this.resolve(target, deadline);
    if (force) return r;
    const res = await this.worlds.call(r.frame, 'states', r.id, states);
    if (res === null || res === undefined) return r;
    if (res.error) throw err(res.error);
    if (res.missing === 'attached') {
      if (target.handle) throw err('Element is not attached to the DOM');
      throw new Retry('element was detached from the DOM, retrying');
    }
    throw new Retry(`element is not ${res.missing}`);
  }

  /** Read a property through the isolated world.
   *
   * Resolve until the selector matches once (Playwright's read semantics),
   * then read the property in the world the engine already runs in.
   */
  /** For an ElementHandle: cache its exact isolated-world id, or throw
   * RawFallback at once when it has no box or shares it (Playwright reads
   * hidden elements; a read must not land on a same-box wrapper). */
  async handleOrRaw(target: Target, deadline: Deadline, api: string): Promise<void> {
    if (target.handle) await this.retry(api, target, deadline, () => this.resolveHandle(target.handle!, deadline, true));
  }

  async read(target: Target, op: string, opts: Opts, api: string, ...extra: any[]): Promise<any> {
    const deadline = this.deadline(target, opts);
    await this.handleOrRaw(target, deadline, api);
    const r = await this.waitFor(target, [], deadline, api);
    const res = await this.worlds.call(r.frame, op, r.id, ...extra);
    if (res && typeof res === 'object' && !Array.isArray(res)) {
      if (res.error) throw err(`${api}: Error: ${res.error}`);
      return res.value;
    }
    return res;
  }

  /** Dispatch a DOM event on the resolved element.
   *
   * The event is built by Playwright's own injected helper, evaluated in the
   * isolated world instead of the page's world.
   */
  async dispatch(target: Target, opts: Opts, api: string, type: string, eventInit?: any): Promise<void> {
    if (hasHandle(eventInit)) throw new RawFallback();
    const deadline = this.deadline(target, opts);
    await this.handleOrRaw(target, deadline, api);
    const r = await this.waitFor(target, [], deadline, api);
    const res = await this.worlds.call(r.frame, 'dispatchEvent', r.id, type, eventInit ?? null);
    if (res && typeof res === 'object' && res.error) throw err(`${api}: Error: ${res.error}`);
  }

  async retry<T>(api: string, target: Target, deadline: Deadline, attempt: () => Promise<T>): Promise<T> {
    const reasons: string[] = [];
    const note = (r: string) => { if (reasons[reasons.length - 1] !== r) reasons.push(r); };
    for (let n = 0; ; n++) {
      try {
        return await attempt();
      } catch (e: any) {
        if (e instanceof RawFallback) throw e;
        if (e instanceof StaleElement) {
          if (target.handle) throw err(`${api}: Element is not attached to the DOM`);
          note('element was detached from the DOM, retrying');
        } else if (e instanceof Retry) {
          note(e.reason);
        } else {
          const msg = String(e?.message ?? e);
          if (msg.startsWith(api)) throw e;
          const out = e instanceof errors.TimeoutError ? new errors.TimeoutError(`${api}: ${msg}`) : err(`${api}: ${msg}`);
          throw out;
        }
      }
      if (deadline.expired()) {
        const log = [`waiting for ${target.description}`, ...reasons.slice(-5)].map((r) => `  - ${r}`).join('\n');
        throw new errors.TimeoutError(`${api}: Timeout ${Math.round(deadline.timeout)}ms exceeded.\nCall log:\n${log}`);
      }
      await sleepMs(Math.min(RETRY_MS[Math.min(n, RETRY_MS.length - 1)], deadline.remaining()));
    }
  }

  // -- geometry -----------------------------------------------------------

  /** Element border box in viewport coordinates plus its visible clip. */
  async elementBox(r: Resolved): Promise<Box> {
    const g = await this.worlds.call(r.frame, 'geometry', r.id);
    if (!g) throw new StaleElement();
    const [ox, oy, frameClip] = await this.worlds.frameGeometry(r.frame);
    let clip = frameClip;
    const box: any = { x: g.x + ox, y: g.y + oy, width: g.width, height: g.height, bl: g.bl, bt: g.bt };
    const scroller = await this.worlds.call(r.frame, 'scroller', r.id);
    if (scroller) {
      const sc = { x: scroller.x + ox, y: scroller.y + oy, width: scroller.width, height: scroller.height };
      clip = intersect(clip, sc);
      box.scroller = sc;
    }
    box.clip = clip;
    box.visible = intersect(clip, box);
    return box;
  }

  // -- scrolling ----------------------------------------------------------

  /** Wheel-scroll until the element sits inside its visible clip (and, for
   * the main document, inside `scroll_target_zone` when the page can still
   * scroll that way). Returns the final box. */
  async scrollIntoView(r: Resolved, cfg: HumanConfig, deadline: Deadline): Promise<Box> {
    let box = await this.elementBox(r);
    const vp = await this.worlds.viewport();
    let stalled = 0, rounds = 0, overshot = false;
    while (stalled < 2 && rounds < 40 && !deadline.expired()) {
      const [dx, dy] = await this.neededScroll(r, box, vp, cfg);
      if (Math.abs(dx) < 1 && Math.abs(dy) < 1) break;
      rounds++;
      const area = box.clip.width > 4 && box.clip.height > 4 ? box.clip : { x: 0, y: 0, width: vp.width, height: vp.height };
      if (!this.inside(area)) {
        await this.moveTo(area.x + area.width * rand(0.3, 0.7), area.y + area.height * rand(0.3, 0.7), cfg);
        await sleepMs(randRange(cfg.scroll_pre_move_delay));
      }
      const before = [box.x, box.y];
      if (Math.abs(dy) >= 1) {
        await this.wheelBurst(0, dy, cfg, deadline);
        if (!overshot) {
          overshot = true;
          await this.overshoot(dy, cfg, deadline);
        }
      }
      if (Math.abs(dx) >= 1) await this.wheelBurst(dx, 0, cfg, deadline);
      await sleepMs(Math.min(randRange(cfg.scroll_settle_delay), deadline.remaining()));
      box = await this.elementBox(r);
      const moved = Math.abs(box.x - before[0]) + Math.abs(box.y - before[1]);
      stalled = moved < 1 ? stalled + 1 : 0;
    }
    return box;
  }

  private inside(a: Rect): boolean {
    const c = this.cursor;
    return a.x <= c.x && c.x <= a.x + a.width && a.y <= c.y && c.y <= a.y + a.height;
  }

  private async neededScroll(r: Resolved, box: Box, vp: { width: number; height: number }, cfg: HumanConfig): Promise<[number, number]> {
    const clip = box.clip;
    if (clip.width <= 0 || clip.height <= 0) {
      // The frame (or container) itself is out of view: bring it in first.
      return [0, (box.y + box.height / 2) - vp.height / 2];
    }
    let dy = 0, dx = 0;
    const top = box.y, bottom = box.y + box.height;
    const zone = cfg.scroll_target_zone;
    const mainDoc = !r.frame.parentFrame() && !box.scroller;
    if (mainDoc && box.height <= vp.height * (zone[1] - zone[0])) {
      const zt = vp.height * zone[0], zb = vp.height * zone[1];
      if (top < zt || bottom > zb) {
        dy = (top + box.height / 2) - vp.height * rand(zone[0], zone[1]);
        if (top >= clip.y - 1 && bottom <= clip.y + clip.height + 1) {
          // Fully visible but off-centre: only if the page can scroll that way.
          const doc = await this.worlds.call(this.page.mainFrame(), 'doc');
          if ((dy < 0 && doc.y <= 0) || (dy > 0 && doc.y >= doc.maxY)) dy = 0;
        }
      }
    } else if (box.height <= clip.height) {
      if (top < clip.y - 1 || bottom > clip.y + clip.height + 1) dy = (top + box.height / 2) - (clip.y + clip.height / 2);
    } else if (box.visible.height < clip.height * 0.5) {
      dy = top - clip.y - clip.height * 0.1;
    }
    // Horizontal (#521): containment only.
    const left = box.x, right = box.x + box.width;
    if (box.width <= clip.width) {
      if (left < clip.x - 1 || right > clip.x + clip.width + 1) dx = (left + box.width / 2) - (clip.x + clip.width / 2);
    } else if (box.visible.width <= 0) {
      dx = left - clip.x;
    }
    return [dx, dy];
  }

  /** Sometimes scroll a little past the target, pause, and wheel back
   * (`scroll_overshoot_chance` / `scroll_overshoot_px`). The next round of
   * `scrollIntoView` fixes whatever is left. */
  private async overshoot(dy: number, cfg: HumanConfig, deadline: Deadline): Promise<void> {
    if (Math.random() >= cfg.scroll_overshoot_chance || deadline.expired()) return;
    const sign = dy > 0 ? 1 : -1;
    await this.wheelBurst(0, Math.round(randRange(cfg.scroll_overshoot_px)) * sign, cfg, deadline);
    await sleepMs(Math.min(randRange(cfg.scroll_settle_delay), deadline.remaining()));
    const corrections = randIntRange([1, 2]);
    for (let i = 0; i < corrections && !deadline.expired(); i++) {
      await this.wheelBurst(0, Math.round(rand(40, 80)) * -sign, cfg, deadline);
      await sleepMs(Math.min(rand(100, 250), deadline.remaining()));
    }
  }

  /** One logical scroll: accelerate -> cruise -> decelerate in wheel ticks. */
  async wheelBurst(dx: number, dy: number, cfg: HumanConfig, deadline?: Deadline): Promise<void> {
    const total = dy ? Math.abs(dy) : Math.abs(dx);
    const sign = (dy || dx) > 0 ? 1 : -1;
    const accel = randIntRange(cfg.scroll_accel_steps), decel = randIntRange(cfg.scroll_decel_steps);
    const avg = (cfg.scroll_delta_base[0] + cfg.scroll_delta_base[1]) / 2;
    const ticks = Math.max(1, Math.ceil(total / avg));
    let sent = 0;
    for (let i = 0; i < ticks; i++) {
      if (sent >= total || deadline?.expired()) break;
      const pause = (i < accel || i >= ticks - decel) ? randRange(cfg.scroll_pause_slow) : randRange(cfg.scroll_pause_fast);
      const tick = Math.min(total - sent, randRange(cfg.scroll_delta_base) * (1 + (Math.random() - 0.5) * 2 * cfg.scroll_delta_variance));
      // Split each tick into small wheel events like real inertia.
      let left = tick;
      while (left > 0.5) {
        const chunk = Math.min(left, rand(20, 40));
        const step = Math.round(chunk) * sign;
        if (step) await this.raw.wheel(dx ? step : 0, dy ? step : 0);
        left -= chunk;
        await sleepMs(rand(8, 20));
      }
      sent += tick;
      await sleepMs(pause);
    }
  }

  // -- pointer ------------------------------------------------------------

  private point(box: Box, position: { x: number; y: number } | null | undefined, isInput: boolean, cfg: HumanConfig): [number, number] {
    if (position) return [box.x + box.bl + position.x, box.y + box.bt + position.y];
    const vis = box.visible;
    if (vis.width <= 0 || vis.height <= 0) throw new Retry('element is outside of the viewport');
    // Aim inside the visible part, keep the input bias for text fields.
    const full = clickTarget(box, isInput, cfg);
    return [Math.min(Math.max(full.x, vis.x + 1), vis.x + vis.width - 1),
      Math.min(Math.max(full.y, vis.y + 1), vis.y + vis.height - 1)];
  }

  /** Exact aim points: a date-editor segment, or a fraction along a slider. */
  private aimPoint(box: Box, aim: any[]): [number, number] {
    let x: number, y: number;
    if (aim[0] === 'segment') {
      const seg = aim[1];
      x = box.x + seg.dx + rand(-2, 2); y = box.y + seg.dy + rand(-2, 2);
    } else {
      const frac = aim[1] as number, vertical = aim[2] as boolean;
      // Native thumbs are inset by about half their width (~8px) at both ends.
      if (vertical) {
        const inset = Math.min(8, box.height / 4);
        y = box.y + box.height - inset - frac * (box.height - 2 * inset);
        x = box.x + box.width / 2;
      } else {
        const inset = Math.min(8, box.width / 4);
        x = box.x + inset + frac * (box.width - 2 * inset);
        y = box.y + box.height / 2 + rand(-1.5, 1.5);
      }
    }
    const v = box.visible;
    if (!(v.x <= x && x <= v.x + v.width && v.y <= y && y <= v.y + v.height)) throw new Retry('element is outside of the viewport');
    return [x, y];
  }

  private async hit(r: Resolved, x: number, y: number): Promise<void> {
    const [ox, oy, clip] = await this.worlds.frameGeometry(r.frame);
    if (!(clip.x <= x && x <= clip.x + clip.width && clip.y <= y && y <= clip.y + clip.height)) {
      throw new Retry('element is outside of the viewport');
    }
    let desc = await this.worlds.call(r.frame, 'hit', r.id, x - ox, y - oy);
    if (!desc && r.frame.parentFrame()) desc = await this.worlds.ownersHit(r.frame, x, y);
    if (desc) throw new Retry(`${desc} intercepts pointer events`);
  }

  /**
   * Shared scroll -> move -> hit-check -> `action` sequence.
   * `hold`: modifier names held down while the cursor travels to the target
   * (Playwright's hover modifiers).
   */
  async pointerAction(api: string, target: Target, opts: Opts, states: string[], isInputHint: boolean | null = null,
                      action: Action | null = null, hold?: string[]): Promise<Resolved> {
    let cfg = this.callCfg(opts.human_config);
    if (opts.steps) {
      cfg = mergeConfig(cfg, { mouse_min_steps: Math.trunc(opts.steps), mouse_max_steps: Math.trunc(opts.steps), mouse_overshoot_chance: 0 });
    }
    const deadline = this.deadline(target, opts);
    const force = !!opts.force, trial = !!opts.trial, position = opts.position;
    const noScroll = opts.scroll === 'none';
    await this.ensureCursor(cfg);
    if (!(opts._nested || opts._deadline)) await this.idle(cfg);

    const attempt = async (): Promise<Resolved> => {
      const r = await this.attemptStates(target, states, deadline, force);
      const box = noScroll ? await this.elementBox(r) : await this.scrollIntoView(r, cfg, deadline);
      let isInput: boolean;
      if (isInputHint === null) {
        const info = await this.worlds.call(r.frame, 'info', r.id);
        isInput = info.tag === 'input' || info.tag === 'textarea' || info.editable;
      } else {
        isInput = isInputHint;
      }
      const [x, y] = opts._aim ? this.aimPoint(box, opts._aim) : this.point(box, position, isInput, cfg);
      if (!force) await this.hit(r, x, y);
      if (trial) return r;
      const keys: string[] = [];
      for (const m of hold ?? []) keys.push(await this.modifier(m));
      for (const k of keys) await this.raw.keyDown(k);
      try {
        await this.moveTo(x, y, cfg);
      } finally {
        for (const k of [...keys].reverse()) await this.raw.keyUp(k);
      }
      // The page may replace or remove the target while the cursor travels;
      // never press on whatever is under it now (even with force). Locators
      // re-resolve and run the whole move again.
      if (!(await this.worlds.call(r.frame, 'connected', r.id))) throw new StaleElement();
      if (!force) await this.hit(r, this.cursor.x, this.cursor.y);
      if (action) await action(r, this.cursor.x, this.cursor.y, cfg);
      return r;
    };
    return this.retry(api, target, deadline, attempt);
  }

  async pressMouse(cfg: HumanConfig, isInput: boolean, button = 'left', clickCount = 1, delay?: number,
                   modifiers?: string[]): Promise<void> {
    const mods: string[] = [];
    for (const m of modifiers ?? []) mods.push(await this.modifier(m));
    await sleepMs(randRange(isInput ? cfg.click_aim_delay_input : cfg.click_aim_delay_button));
    for (const m of mods) await this.raw.keyDown(m);
    try {
      const count = Math.max(1, Math.trunc(clickCount));
      for (let n = 1; n <= count; n++) {
        const hold = delay ?? randRange(isInput ? cfg.click_hold_input : cfg.click_hold_button);
        await this.raw.down({ button, clickCount: n });
        await sleepMs(hold);
        await this.raw.up({ button, clickCount: n });
        if (n < count) await sleepMs(delay ?? rand(60, 140));
      }
    } finally {
      for (const m of [...mods].reverse()) await this.raw.keyUp(m);
    }
  }

  // -- public actions -----------------------------------------------------

  async click(target: Target, opts: Opts, api = 'click', clickCount?: number): Promise<void> {
    const count = clickCount ?? Math.trunc(opts.clickCount || 1);
    await this.pointerAction(api, target, opts, CLICK_STATES, null, async (r, _x, _y, cfg) => {
      const info = await this.worlds.call(r.frame, 'info', r.id);
      const isInput = info.tag === 'input' || info.tag === 'textarea' || info.editable;
      await this.pressMouse(cfg, isInput, opts.button || 'left', count, opts.delay, opts.modifiers);
    });
  }

  async hover(target: Target, opts: Opts, api = 'hover'): Promise<void> {
    const mods = opts.modifiers;
    // Playwright holds the modifiers while the mouse moves onto the target.
    await this.pointerAction(api, target, opts, HOVER_STATES, false, undefined, mods);
  }

  async tap(target: Target, opts: Opts, api = 'tap'): Promise<void> {
    await this.click(target, { ...opts, clickCount: 1 }, api);
  }

  /**
   * Focus by a human click unless already focused. Returns [r, clickedIn]:
   * clickedIn is true when this call clicked and focus landed in the target.
   * With requireFocus=false (press / type) a click that does not move focus is
   * fine, as in Playwright: the keys go to whatever handles them (a <canvas>,
   * document-level key handlers).
   */
  async focusElement(target: Target, opts: Opts, api: string, _cfg: HumanConfig, deadline: Deadline,
    requireFocus = true): Promise<[Resolved, boolean]> {
    const r = await this.waitFor(target, FOCUS_STATES, deadline, api, !!opts.force);
    let info = await this.worlds.call(r.frame, 'info', r.id);
    if (info.focused) return [r, false];
    // A person focuses a field by clicking it: scroll it into view with the
    // wheel and click. When it cannot be brought on screen at all the click
    // times out with "element is outside of the viewport" -- no silent
    // programmatic focus.
    await this.click(target, { _deadline: deadline, force: opts.force, human_config: opts.human_config }, api);
    info = await this.worlds.call(r.frame, 'info', r.id);
    if (info.focused || (await this.focusMovedInto(r))) return [r, true];
    if (requireFocus) {
      throw err(`${api}: Error: element did not receive focus when clicked (it may not be focusable): ${info.preview}`);
    }
    return [r, false];
  }

  /** The click landed but focus went to a focusable child: accept it. */
  private async focusMovedInto(r: Resolved): Promise<boolean> {
    const act = await this.worlds.call(r.frame, 'activeValue');
    if (!act?.tag) return false;
    return !!(await this.worlds.evaluate(r.frame,
      `(() => { const e = ${HELPERS}.el(${r.id}); const a = document.activeElement; return !!a && (e === a || e.contains(a)); })()`));
  }

  async caretToEnd(r: Resolved): Promise<void> {
    const info = await this.worlds.call(r.frame, 'info', r.id);
    if (info.tag === 'input') {
      if (!(await this.worlds.call(r.frame, 'caretAtEnd', r.id))) await this.raw.keyPress('End');
    } else {
      await this.raw.keyPress('Control+End');
    }
    await sleepMs(rand(20, 60));
  }

  private async keys(key: string): Promise<string> {
    return key.includes('ControlOrMeta') ? key.split('ControlOrMeta').join(await this.modifier('ControlOrMeta')) : key;
  }

  async press(target: Target, key: string, opts: Opts, api = 'press'): Promise<void> {
    const cfg = this.callCfg(opts.human_config);
    const deadline = this.deadline(target, opts);
    await this.focusElement(target, opts, api, cfg, deadline, false);
    await sleepMs(rand(50, 150));
    const k = await this.keys(key);
    await this.raw.keyPress(k, opts.delay !== undefined ? { delay: opts.delay } : undefined);
  }

  async type(target: Target, text: string, opts: Opts, api = 'type'): Promise<void> {
    const cfg = this.callCfg(opts.human_config);
    const deadline = this.deadline(target, opts);
    await sleepMs(randRange(cfg.field_switch_delay));
    const [r, clickedIn] = await this.focusElement(target, opts, api, cfg, deadline, false);
    if (clickedIn) await this.caretToEnd(r);
    await sleepMs(rand(100, 250));
    const info = await this.worlds.call(r.frame, 'info', r.id);
    await this.typeText(text, cfg, r.frame, info, opts.delay);
  }

  async fill(target: Target, value: string, opts: Opts, api = 'fill'): Promise<void> {
    const cfg = this.callCfg(opts.human_config);
    const deadline = this.deadline(target, opts);
    const force = !!opts.force;
    let r = await this.waitFor(target, INPUT_STATES, deadline, api, force);
    let info = await this.worlds.call(r.frame, 'info', r.id);
    const kind = fields.classify(info.tag, info.type, info.editable);
    if (kind === fields.NOT_FILLABLE) throw err(`${api}: Error: ${fields.notFillableMessage(info.tag, info.type)}`);
    if (info.type === 'number') {
      const v = fields.validateNumber(value);
      if (v === null) throw err(`${api}: Error: Cannot type text into input[type=number]`);
      value = v;
    }
    if (kind === fields.SET) {
      value = fields.normalizeSetValue(info.type, value);
      await sleepMs(randRange(cfg.field_switch_delay));
      if (info.type === 'range') await this.setRange(target, r, value, opts, api, cfg, deadline);
      else if (info.type === 'color') this.setColor(api);
      else await this.setDatetime(target, r, info.type, value, opts, api, cfg, deadline);
      return;
    }
    await sleepMs(randRange(cfg.field_switch_delay));
    [r] = await this.focusElement(target, opts, api, cfg, deadline);
    await sleepMs(rand(100, 250));
    info = await this.worlds.call(r.frame, 'info', r.id);
    if (info.value) {
      await this.raw.keyPress(await this.selectAllKey());
      await sleepMs(rand(30, 80));
      await this.raw.keyPress('Backspace');
      await sleepMs(rand(50, 150));
      info = await this.worlds.call(r.frame, 'info', r.id);
      if (info.value) {
        // Some widgets ignore select-all; clear what is left by keys.
        await this.caretToEnd(r);
        for (let i = 0; i < info.value.length; i++) {
          await this.raw.keyPress('Backspace');
          await sleepMs(rand(15, 40));
        }
      }
    }
    if (value) await this.typeText(value, cfg, r.frame, info, undefined);
  }

  async setChecked(target: Target, checked: boolean, opts: Opts, api: string): Promise<void> {
    const deadline = this.deadline(target, opts);
    const r = await this.waitFor(target, CLICK_STATES, deadline, api, !!opts.force);
    let state = await this.worlds.call(r.frame, 'checked', r.id);
    if (state.error) throw err(`${api}: Error: ${state.error}`);
    if (state.checked === checked) return;
    if (state.radio && !checked) {
      throw err(`${api}: Error: Cannot uncheck radio button. Radio buttons can only be unchecked by selecting another radio button in the same group.`);
    }
    await this.click(target, {
      force: opts.force, position: opts.position, trial: opts.trial, human_config: opts.human_config, _deadline: deadline,
    }, api);
    if (opts.trial) return;
    state = await this.worlds.call(r.frame, 'checked', r.id);
    if (state.checked !== checked) throw err(`${api}: Error: Clicking the checkbox did not change its state`);
  }

  // -- value inputs: what a person does --------------------------------

  /** date / time / datetime-local / month / week: click the first segment
   * of the native editor and type each part with the keyboard. Segment order
   * comes from the editor itself, so any locale works. */
  async setDatetime(target: Target, r: Resolved, inputType: string, value: string, opts: Opts, api: string,
                    cfg: HumanConfig, deadline: Deadline): Promise<void> {
    let parts = fields.datetimeParts(inputType, value);
    if (!parts) throw err(`${api}: Error: Malformed value`);
    const segs = await this.worlds.editorFields(r.frame, r.id);
    const kinds = segs.map((s) => s.kind);
    parts = fields.use24h(parts, kinds.includes('ampm'));
    if (!segs.length || kinds.some((k) => !(k in parts!) && k !== 'ampm')) {
      throw err(`${api}: Error: unsupported date/time editor layout ${JSON.stringify(kinds)}`);
    }
    await this.pointerAction(api, target, { ...opts, _deadline: deadline, position: null, _aim: ['segment', segs[0]] },
      INPUT_STATES, true, (_rr, _x, _y, c) => this.pressMouse(c, true));
    await sleepMs(rand(80, 200));
    const current = fields.datetimeParts(inputType, (await this.worlds.call(r.frame, 'value', r.id)) || '');
    for (let i = 0; i < segs.length; i++) {
      const kind = segs[i].kind;
      if (inputType === 'month' && kind === 'month' && current) {
        // Shown as a month name; over an existing month Chromium's digit
        // matching is unreliable, so step with the arrow keys.
        const diff = parseInt(parts.month, 10) - parseInt(current.month, 10);
        for (let k = 0; k < Math.abs(diff); k++) {
          await this.raw.keyPress(diff > 0 ? 'ArrowUp' : 'ArrowDown');
          await sleepMs(rand(60, 140));
        }
      } else if (kind === 'ampm') {
        await this.typeChar((parts.hour24 ?? 0) >= 12 ? 'P' : 'A', cfg);
      } else {
        const digits: string = parts[kind];
        for (let j = 0; j < digits.length; j++) {
          await this.typeChar(digits[j], cfg);
          if (j < digits.length - 1) {
            // The editor forgets a partial entry after ~1 s without a key;
            // keep the gap inside a segment short.
            await sleepMs(Math.min(450, Math.max(40, cfg.typing_delay + (Math.random() - 0.5) * 2 * cfg.typing_delay_spread)));
          }
        }
      }
      if (i < segs.length - 1 && !fields.segmentAutoAdvances(kind, parts, inputType)) await this.raw.keyPress('ArrowRight');
      await sleepMs(rand(60, 160));
    }
    const got = await this.worlds.call(r.frame, 'value', r.id);
    if (got !== value) throw err(`${api}: Error: the date/time editor produced ${JSON.stringify(got)} instead of ${JSON.stringify(value)}`);
  }

  /** Slider: click on the track near the wanted value, then nudge with arrow
   * keys until it is exact. */
  async setRange(target: Target, r: Resolved, value: string, opts: Opts, api: string, _cfg: HumanConfig,
                 deadline: Deadline): Promise<void> {
    const info = await this.worlds.call(r.frame, 'rangeInfo', r.id);
    const want = Number(value);
    if (value === '' || Number.isNaN(want)) throw err(`${api}: Error: Malformed value`);
    const span = info.max - info.min;
    let frac = span <= 0 ? 0.5 : Math.min(1, Math.max(0, (want - info.min) / span));
    if (info.rtl && !info.vertical) frac = 1 - frac;
    await this.pointerAction(api, target, { ...opts, _deadline: deadline, position: null, _aim: ['fraction', frac, info.vertical] },
      INPUT_STATES, false, (_rr, _x, _y, c) => this.pressMouse(c, false));
    const read = async () => Number(await this.worlds.call(r.frame, 'value', r.id));
    for (let k = 0; k < 400; k++) {
      const cur = await read();
      if (Math.abs(cur - want) < 1e-9 || (info.step && Math.abs(cur - want) < info.step / 2)) break;
      const up = cur < want;
      const key = !info.rtl ? (up ? 'ArrowRight' : 'ArrowLeft') : (up ? 'ArrowLeft' : 'ArrowRight');
      await this.raw.keyPress(key);
      await sleepMs(rand(40, 110));
      if ((await read()) === cur) break; // cannot move further (min/max reached)
    }
    const got = await this.worlds.call(r.frame, 'value', r.id);
    if (Number(got) !== this.rangeSnap(info, want)) throw err(`${api}: Error: slider stopped at ${got} instead of ${value}`);
  }

  private rangeSnap(info: any, want: number): number {
    let v = Math.min(info.max, Math.max(info.min, want));
    if (info.step) v = Math.min(info.max, info.min + Math.round((v - info.min) / info.step) * info.step);
    return v;
  }

  /** <input type=color> opens an OS colour dialog that page input cannot
   * drive. Setting the value silently would hide a robot-only path. */
  private setColor(api: string): never {
    throw err(`${api}: Error: <input type=color> opens a native colour picker that cannot be operated with ` +
      'human input; set it with page._original.fill(...) if a programmatic value is acceptable');
  }

  /** Pick options like a person: a dropdown is opened with a click and moved
   * with arrow keys + Enter; a list box gets clicks on the options
   * (Ctrl/Cmd-click to add more in a multi-select). */
  async selectOption(target: Target, options: any[], handles: ElementHandle[], opts: Opts, api = 'selectOption'): Promise<string[]> {
    const cfg = this.callCfg(opts.human_config);
    const deadline = this.deadline(target, opts);
    const force = !!opts.force;
    const [r, p] = await this.retry(api, target, deadline, async (): Promise<[Resolved, any]> => {
      const rr = await this.attemptStates(target, ['visible', 'enabled'], deadline, force);
      const ids: number[] = [];
      for (const h of handles) ids.push((await this.resolveHandle(h, deadline)).id);
      const res = await this.worlds.call(rr.frame, 'selectPlan', rr.id, options, ids);
      if (res.error) throw err(res.error);
      if (res.retry) throw new Retry(res.retry);
      return [rr, res];
    });
    if (!p.listbox) await this.selectDropdown(target, r, p.targets.length ? p.targets[0] : null, p, opts, api, deadline);
    else await this.selectListbox(target, r, p, opts, api, cfg, deadline);
    const state = await this.worlds.call(r.frame, 'selectState', r.id);
    const sorted = (a: number[]) => JSON.stringify([...a].sort((x, y) => x - y));
    if (sorted(state.selected) !== sorted(p.targets)) {
      throw err(`${api}: Error: selection ended as ${JSON.stringify(state.values)} instead of ${JSON.stringify(p.values)}`);
    }
    return state.values;
  }

  private async selectDropdown(target: Target, r: Resolved, index: number | null, p: any, opts: Opts, api: string,
                               deadline: Deadline): Promise<void> {
    if (index === null) throw err(`${api}: Error: a dropdown always keeps one option selected`);
    const state = await this.worlds.call(r.frame, 'selectState', r.id);
    if (state.current === index) {
      await this.hover(target, { _deadline: deadline, human_config: opts.human_config }, api);
      return;
    }
    const mac = process.platform === 'darwin'; // a macOS host's native popup ignores arrow keys
    const plan = await this.worlds.call(r.frame, 'typeAheadPlan', r.id, index, mac ? 0 : 3);
    if (!plan) throw err(`${api}: Error: no option of this dropdown can be reached`);
    if (mac && plan.home && /[\uD800-\uDFFF]/.test(plan.label)) {
      throw err(`${api}: Error: this option's label has an emoji or similar character that cannot be typed, and a `
        + 'macOS dropdown ignores arrow keys, so it cannot be picked with human input; select it with '
        + 'page._original.selectOption(...) if a programmatic selection is acceptable');
    }
    await this.click(target, { _deadline: deadline, force: opts.force, human_config: opts.human_config }, api);
    await sleepMs(rand(200, 450)); // popup opens; eyes find the option
    const cfg = this.callCfg(opts.human_config);
    const arrows = (n: number) => Array<string>(Math.abs(n)).fill(n > 0 ? 'ArrowDown' : 'ArrowUp');
    // No name prefix is unique (duplicate labels): Home, then walk; on macOS type the whole label.
    const keys: string[] = plan.home ? (mac ? [...plan.label] : ['Home', ...arrows(plan.arrows)])
      : [...plan.typed, ...arrows(plan.arrows)];
    // The browser joins letters typed within ~1s into one search: let an earlier
    // selectOption's search lapse before starting a new one.
    if (keys.length && keys[0].length === 1) {
      const wait = this.typeAheadUntil - Date.now();
      if (wait > 0) await sleepMs(wait);
    }
    let typed = false;
    for (const k of keys) {
      if (deadline.expired()) {
        await this.raw.keyPress('Escape');
        throw new errors.TimeoutError(`${api}: Timeout ${Math.round(deadline.timeout)}ms exceeded.\n`
          + `Call log:\n  - choosing an option of ${target.description}`);
      }
      if (k.length === 1) {
        await this.typeAheadChar(k, cfg);
        typed = true;
        this.typeAheadUntil = Date.now() + 1100;
        await sleepMs(rand(60, 160));
      } else {
        await this.raw.keyPress(k);
        await sleepMs(rand(90, 200));
      }
    }
    await sleepMs(rand(100, 250));
    await this.raw.keyPress('Enter');
    if (typed) this.typeAheadUntil = Date.now() + 1100;
    await sleepMs(rand(80, 160));
  }

  /** One type-ahead letter (lowercase: a person doesn't hold Shift to search a
   * list); a character without a US-layout key is sent as itself. */
  private async typeAheadChar(ch: string, cfg: HumanConfig): Promise<void> {
    if (ch.charCodeAt(0) < 128) {
      await this.typeChar(ch, cfg);
      return;
    }
    const session: CDPSession = await this.worlds.session();
    await session.send('Input.dispatchKeyEvent', { type: 'keyDown', key: ch, text: ch, unmodifiedText: ch });
    await sleepMs(randRange(cfg.key_hold));
    await session.send('Input.dispatchKeyEvent', { type: 'keyUp', key: ch });
  }

  private async selectListbox(target: Target, r: Resolved, p: any, opts: Opts, api: string, cfg: HumanConfig,
                              deadline: Deadline): Promise<void> {
    const state = await this.worlds.call(r.frame, 'selectState', r.id);
    const want: number[] = [...p.targets];
    const sorted = (a: number[]) => JSON.stringify([...a].sort((x, y) => x - y));
    if (sorted(state.selected) === sorted(want)) {
      await this.hover(target, { _deadline: deadline, human_config: opts.human_config }, api);
      return;
    }
    if (!want.length) throw err(`${api}: Error: deselecting every option is not something a click can do`);
    const addKey = (await this.isMac()) ? 'Meta' : 'Control';
    let first = true;
    for (const idx of want) {
      const oid = await this.worlds.call(r.frame, 'optionId', r.id, idx);
      const label = new Target(r.frame, null);
      label.description = `option #${idx}`;
      // A plain click on the first option replaces the selection; further
      // options are added with Ctrl/Cmd held, as a person does.
      await this.clickResolved(new Resolved(r.frame, oid), label, cfg, deadline, api, first ? [] : [addKey]);
      first = false;
      await sleepMs(rand(120, 300));
    }
  }

  /** Scroll / move / hit-check / click an already resolved element. */
  private async clickResolved(r: Resolved, label: Target, cfg: HumanConfig, deadline: Deadline, api: string,
                              modifiers: string[]): Promise<void> {
    await this.retry(api, label, deadline, async () => {
      const box = await this.scrollIntoView(r, cfg, deadline);
      const [x, y] = this.point(box, null, false, cfg);
      await this.hit(r, x, y);
      await this.moveTo(x, y, cfg);
      await this.hit(r, this.cursor.x, this.cursor.y);
      await this.pressMouse(cfg, false, 'left', 1, undefined, modifiers);
    });
  }

  async drag(source: Target, dest: Target, opts: Opts, api = 'dragAndDrop'): Promise<void> {
    const sub: Opts = {
      _deadline: this.deadline(source, opts), force: opts.force, human_config: opts.human_config,
      position: opts.sourcePosition, trial: opts.trial,
    };
    await this.idle(this.callCfg(opts.human_config));
    await this.hover(source, sub, api);
    if (opts.trial) {
      await this.hover(dest, { ...sub, position: opts.targetPosition, _nested: true }, api);
      return;
    }
    await sleepMs(rand(100, 200));
    await this.raw.down();
    try {
      await sleepMs(rand(80, 150));
      await this.hover(dest, { ...sub, position: opts.targetPosition, force: true, _nested: true }, api);
      await sleepMs(rand(80, 150));
    } finally {
      await this.raw.up();
    }
  }

  async focus(target: Target, opts: Opts, api = 'focus', move = false): Promise<void> {
    const deadline = this.deadline(target, opts);
    if (move) await this.hover(target, { timeout: opts.timeout, human_config: opts.human_config }, api);
    const r = await this.retry(api, target, deadline, () => this.resolve(target, deadline));
    await this.worlds.call(r.frame, 'focus', r.id);
  }

  async scrollIntoViewIfNeeded(target: Target, opts: Opts, api = 'scrollIntoViewIfNeeded'): Promise<void> {
    const cfg = this.callCfg(opts.human_config);
    const deadline = this.deadline(target, opts);
    await this.ensureCursor(cfg);
    await this.retry(api, target, deadline, async () => {
      const r = await this.attemptStates(target, ['visible', 'stable'], deadline, false);
      await this.scrollIntoView(r, cfg, deadline);
    });
  }

  // -- keyboard -----------------------------------------------------------

  /** Type `text` key by key into the focused element of `frame`. */
  async typeText(text: string, cfg: HumanConfig, frame: Frame, info: any, delay: number | undefined): Promise<void> {
    const tag = info?.tag ?? null;
    const mistypes = cfg.mistype_chance > 0 && tag !== null && fields.allowsMistype(tag, info?.type ?? null);
    const chars = [...text];
    for (let i = 0; i < chars.length; i++) {
      const ch = chars[i];
      if (!isAscii(ch)) {
        await sleepMs(randRange(cfg.key_hold));
        await this.raw.insertText(ch);
      } else {
        if (mistypes && isAsciiAlnum(ch) && Math.random() < cfg.mistype_chance) await this.typo(ch, cfg, frame);
        await this.typeChar(ch, cfg);
      }
      if (i < chars.length - 1) await this.betweenKeys(cfg, delay);
    }
  }

  private async typo(ch: string, cfg: HumanConfig, frame: Frame): Promise<void> {
    const lower = ch.toLowerCase();
    const near = NEARBY_KEYS[lower];
    if (!near) return;
    let wrong = near[Math.floor(Math.random() * near.length)];
    if (isUpper(ch)) wrong = wrong.toUpperCase();
    const before = await this.activeValue(frame);
    await this.typeChar(wrong, cfg);
    await sleepMs(randRange(cfg.mistype_delay_notice));
    const after = await this.activeValue(frame);
    if (before !== null && after === before) {
      // The page rejected the wrong key (mask / filter): nothing to undo.
      await sleepMs(randRange(cfg.mistype_delay_correct));
      return;
    }
    await this.raw.keyDown('Backspace');
    await sleepMs(randRange(cfg.key_hold));
    await this.raw.keyUp('Backspace');
    await sleepMs(randRange(cfg.mistype_delay_correct));
  }

  private async activeValue(frame: Frame): Promise<string | null> {
    try { return (await this.worlds.call(frame, 'activeValue'))?.value ?? null; } catch { return null; }
  }

  async typeChar(ch: string, cfg: HumanConfig): Promise<void> {
    if (isUpper(ch)) {
      await this.raw.keyDown('Shift');
      await sleepMs(randRange(cfg.shift_down_delay));
      await this.raw.keyDown(ch);
      await sleepMs(randRange(cfg.key_hold));
      await this.raw.keyUp(ch);
      await sleepMs(randRange(cfg.shift_up_delay));
      await this.raw.keyUp('Shift');
    } else if (SHIFT_SYMBOLS.has(ch)) {
      const session: CDPSession = await this.worlds.session();
      const code = SHIFT_SYMBOL_CODES[ch] || '';
      const vk = SHIFT_SYMBOL_KEYCODES[ch] || 0;
      await this.raw.keyDown('Shift');
      await sleepMs(randRange(cfg.shift_down_delay));
      await session.send('Input.dispatchKeyEvent', {
        type: 'keyDown', modifiers: 8, key: ch, code, windowsVirtualKeyCode: vk, text: ch, unmodifiedText: ch,
      });
      await sleepMs(randRange(cfg.key_hold));
      await session.send('Input.dispatchKeyEvent', { type: 'keyUp', modifiers: 8, key: ch, code, windowsVirtualKeyCode: vk });
      await sleepMs(randRange(cfg.shift_up_delay));
      await this.raw.keyUp('Shift');
    } else {
      await this.raw.keyDown(ch);
      await sleepMs(randRange(cfg.key_hold));
      await this.raw.keyUp(ch);
    }
  }

  private async betweenKeys(cfg: HumanConfig, delay: number | undefined): Promise<void> {
    if (delay !== undefined && delay !== null) await sleepMs(delay);
    else if (Math.random() < cfg.typing_pause_chance) await sleepMs(randRange(cfg.typing_pause_range));
    else await sleepMs(Math.max(10, cfg.typing_delay + (Math.random() - 0.5) * 2 * cfg.typing_delay_spread));
  }

  /** `page.keyboard.type`: no target; mistypes only where safe. */
  async keyboardType(text: string, delay?: number): Promise<void> {
    const frame = this.page.mainFrame();
    let info: any = null;
    try { info = await this.worlds.call(frame, 'activeValue'); } catch { info = null; }
    if (info?.tag === 'iframe') info = null; // focus inside a child frame: value checks impossible
    await this.typeText(text, this.cfg, frame, info?.tag ? info : null, delay);
  }

  // -- raw mouse API ------------------------------------------------------

  async mouseMove(x: number, y: number, steps?: number): Promise<void> {
    if (steps !== undefined && steps !== null) {
      await this.ensureCursor();
      await this.raw.move(x, y, { steps });
    } else {
      await this.moveTo(x, y, this.cfg);
    }
    this.cursor.x = x; this.cursor.y = y;
  }

  async mouseClick(x: number, y: number, delay?: number, button?: string, clickCount?: number): Promise<void> {
    await this.moveTo(x, y, this.cfg);
    await this.pressMouse(this.cfg, false, button || 'left', clickCount || 1, delay);
  }
}
