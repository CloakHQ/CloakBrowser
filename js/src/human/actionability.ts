/**
 * Playwright-style actionability checks for the humanize layer.
 *
 * Checks: attached, visible, stable, enabled, editable, receives pointer events.
 * Retry loop with backoff matching Playwright internals: [100, 250, 500, 1000]ms.
 */

import type { Page, Frame, ElementHandle } from 'playwright-core';
import {
  buildActionableJs, buildBoxJs, buildPointerJs, evalParsed, getWorld,
  OK, NOT_FOUND, UNSUPPORTED, type StealthWorld,
} from './stealthDom.js';

// ---------------------------------------------------------------------------
// Error hierarchy
// ---------------------------------------------------------------------------

export class ActionabilityError extends Error {
  selector: string;
  check: string;

  constructor(selector: string, check: string, message: string) {
    super(`Element ${JSON.stringify(selector)} failed ${check} check: ${message}`);
    this.name = 'ActionabilityError';
    this.selector = selector;
    this.check = check;
  }
}

export class ElementNotAttachedError extends ActionabilityError {
  constructor(selector: string) {
    super(selector, 'attached', 'element not found in DOM');
    this.name = 'ElementNotAttachedError';
  }
}

export class ElementNotVisibleError extends ActionabilityError {
  constructor(selector: string) {
    super(selector, 'visible', 'element is not visible');
    this.name = 'ElementNotVisibleError';
  }
}

export class ElementNotStableError extends ActionabilityError {
  constructor(selector: string) {
    super(selector, 'stable', 'element position is still changing');
    this.name = 'ElementNotStableError';
  }
}

export class ElementNotEnabledError extends ActionabilityError {
  constructor(selector: string) {
    super(selector, 'enabled', 'element is disabled');
    this.name = 'ElementNotEnabledError';
  }
}

export class ElementNotEditableError extends ActionabilityError {
  constructor(selector: string) {
    super(selector, 'editable', 'element is not editable');
    this.name = 'ElementNotEditableError';
  }
}

export class ElementNotReceivingEventsError extends ActionabilityError {
  coveringTag: string;
  constructor(selector: string, coveringTag: string = 'unknown') {
    super(selector, 'pointer_events', `element is covered by <${coveringTag}>`);
    this.name = 'ElementNotReceivingEventsError';
    this.coveringTag = coveringTag;
  }
}

// ---------------------------------------------------------------------------
// Check-set constants
// ---------------------------------------------------------------------------

export type CheckName = 'attached' | 'visible' | 'enabled' | 'editable' | 'pointer_events';

export const CHECKS_CLICK: ReadonlySet<CheckName> = new Set(['attached', 'visible', 'enabled', 'pointer_events']);
export const CHECKS_HOVER: ReadonlySet<CheckName> = new Set(['attached', 'visible', 'pointer_events']);
export const CHECKS_INPUT: ReadonlySet<CheckName> = new Set(['attached', 'visible', 'enabled', 'editable', 'pointer_events']);
export const CHECKS_FOCUS: ReadonlySet<CheckName> = new Set(['attached', 'visible', 'enabled']);
export const CHECKS_CHECK: ReadonlySet<CheckName> = new Set(['attached', 'visible', 'enabled', 'pointer_events']);

const BACKOFF_MS = [100, 250, 500, 1000];

function backoffSleep(attempt: number): Promise<void> {
  const idx = Math.min(attempt, BACKOFF_MS.length - 1);
  return new Promise(resolve => setTimeout(resolve, BACKOFF_MS[idx]));
}

// ---------------------------------------------------------------------------
// Pre-scroll actionability
// ---------------------------------------------------------------------------

/**
 * Run the actionability checks through the isolated world.
 *
 * Returns true when handled (throwing the specific ActionabilityError on a failed
 * check), or false when the selector/world is unsupported so the caller falls back
 * to the regular Playwright read.
 */
async function stealthActionable(
  pageOrFrame: Page | Frame,
  selector: string,
  checks: ReadonlySet<CheckName>,
): Promise<boolean> {
  const world = getWorld(pageOrFrame);
  if (!world) return false;
  const { status, data } = await evalParsed(world, buildActionableJs(selector));
  if (status === UNSUPPORTED) return false;
  if (status === NOT_FOUND) {
    // Every check-set includes 'attached'; not present yet -> throw so the retry
    // loop backs off and re-reads in-world (mirrors waitFor({ state: 'attached' })).
    throw new ElementNotAttachedError(selector);
  }
  if (checks.has('visible') && !data.visible) throw new ElementNotVisibleError(selector);
  if (checks.has('enabled') && !data.enabled) throw new ElementNotEnabledError(selector);
  if (checks.has('editable') && !data.editable) throw new ElementNotEditableError(selector);
  return true;
}

/**
 * Bounding box via the isolated world, falling back to Playwright. Returns the box,
 * or null when the element is not present. Only an unsupported selector (or missing
 * world) reaches Playwright's `boundingBox`; a genuine not-found stays in-world.
 */
async function readBox(
  pageOrFrame: Page | Frame,
  selector: string,
  remainingMs: number,
): Promise<{ x: number; y: number; width: number; height: number } | null> {
  const world = getWorld(pageOrFrame);
  if (world) {
    const { status, data } = await evalParsed(world, buildBoxJs(selector));
    if (status === OK) return data.box;
    if (status === NOT_FOUND) return null;
    // UNSUPPORTED -> Playwright below
  }
  try {
    const loc = pageOrFrame.locator(selector).first();
    return await loc.boundingBox({ timeout: Math.max(1, Math.min(remainingMs, 1000)) });
  } catch {
    return null;
  }
}

export async function ensureActionable(
  pageOrFrame: Page | Frame,
  selector: string,
  checks: ReadonlySet<CheckName>,
  timeout: number = 30000,
  force: boolean = false,
): Promise<void> {
  if (force) return;

  const deadline = Date.now() + timeout;
  let attempt = 0;
  let lastError: ActionabilityError | null = null;

  while (true) {
    const remainingMs = Math.max(0, deadline - Date.now());
    if (remainingMs <= 0) {
      if (lastError) throw lastError;
      throw new ActionabilityError(selector, 'timeout', 'timeout expired before first check');
    }

    try {
      // Prefer the isolated-world read; fall back to Playwright's locator
      // predicates only for selector grammar the isolated world can't resolve.
      if (!await stealthActionable(pageOrFrame, selector, checks)) {
        const loc = pageOrFrame.locator(selector).first();

        if (checks.has('attached')) {
          try {
            await loc.waitFor({ state: 'attached', timeout: Math.max(1, Math.min(remainingMs, 2000)) });
          } catch {
            throw new ElementNotAttachedError(selector);
          }
        }

        if (checks.has('visible')) {
          if (!await loc.isVisible()) throw new ElementNotVisibleError(selector);
        }

        if (checks.has('enabled')) {
          if (!await loc.isEnabled()) throw new ElementNotEnabledError(selector);
        }

        if (checks.has('editable')) {
          if (!await loc.isEditable()) throw new ElementNotEditableError(selector);
        }
      }

      return;
    } catch (e) {
      if (e instanceof ActionabilityError) {
        lastError = e;
        if (Date.now() >= deadline) throw lastError;
        await backoffSleep(attempt);
        attempt++;
      } else {
        throw e;
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Post-scroll stability check
// ---------------------------------------------------------------------------

function boxesDiffer(
  a: { x: number; y: number; width: number; height: number },
  b: { x: number; y: number; width: number; height: number },
): boolean {
  return (
    Math.abs(a.x - b.x) > 1 ||
    Math.abs(a.y - b.y) > 1 ||
    Math.abs(a.width - b.width) > 1 ||
    Math.abs(a.height - b.height) > 1
  );
}

export async function ensureStable(
  pageOrFrame: Page | Frame,
  selector: string,
  timeout: number = 5000,
): Promise<void> {
  const deadline = Date.now() + timeout;
  let attempt = 0;

  while (true) {
    const remainingMs = Math.max(0, deadline - Date.now());
    if (remainingMs <= 0) throw new ElementNotStableError(selector);

    const box1 = await readBox(pageOrFrame, selector, remainingMs);
    if (!box1) throw new ElementNotAttachedError(selector);

    await new Promise(r => setTimeout(r, 100));

    const box2 = await readBox(pageOrFrame, selector, remainingMs);
    if (!box2) throw new ElementNotAttachedError(selector);

    if (!boxesDiffer(box1, box2)) return;

    if (Date.now() >= deadline) throw new ElementNotStableError(selector);

    await backoffSleep(attempt);
    attempt++;
  }
}

// ---------------------------------------------------------------------------
// Pointer-events check (post-scroll, at actual click coordinates)
// ---------------------------------------------------------------------------

const POINTER_EVENTS_LOCATOR_JS = `(expected, data) => {
  const rect = expected.getBoundingClientRect();
  const frameOffsetX = data.box ? data.box.x - rect.x : 0;
  const frameOffsetY = data.box ? data.box.y - rect.y : 0;
  const target = document.elementFromPoint(data.x - frameOffsetX, data.y - frameOffsetY);
  if (!target) return { hit: false, reason: 'no_element_at_point', covering: 'none' };
  let node = target;
  while (node) { if (node === expected) return { hit: true }; node = node.parentNode; }
  if (expected.contains(target)) return { hit: true };
  return { hit: false, reason: 'covered', covering: target.tagName || 'unknown' };
}`;

const POINTER_EVENTS_HANDLE_JS = `(expected, data) => {
  const rect = expected.getBoundingClientRect();
  const frameOffsetX = data.box ? data.box.x - rect.x : 0;
  const frameOffsetY = data.box ? data.box.y - rect.y : 0;
  const target = document.elementFromPoint(data.x - frameOffsetX, data.y - frameOffsetY);
  if (!target) return { hit: false, reason: 'no_element_at_point', covering: 'none' };
  let node = target;
  while (node) { if (node === expected) return { hit: true }; node = node.parentNode; }
  if (expected.contains(target)) return { hit: true };
  return { hit: false, reason: 'covered', covering: target.tagName || 'unknown' };
}`;

export async function checkPointerEvents(
  pageOrFrame: Page | Frame,
  selector: string,
  x: number,
  y: number,
  stealth?: { evaluate(expression: string): Promise<any> } | null,
  timeout: number = 5000,
): Promise<void> {
  const deadline = Date.now() + timeout;
  let attempt = 0;
  let lastMiss: string | null = null;

  while (true) {
    // Isolated-world hit test; the passed-in `stealth` world is reused, falling
    // back to Playwright only for unsupported selectors.
    const world: StealthWorld | null = stealth ?? getWorld(pageOrFrame);
    let result: any = null;
    let handled = false;
    if (world) {
      const { status, data } = await evalParsed(world, buildPointerJs(selector, x, y));
      if (status === OK) {
        result = { hit: !!data.hit, covering: data.covering ?? 'unknown' };
        handled = true;
      } else if (status === NOT_FOUND) {
        result = null; // indeterminate -> proceed (fail-open)
        handled = true;
      }
    }
    if (!handled) {
      try {
        const loc = pageOrFrame.locator(selector).first();
        const box = await loc.boundingBox({ timeout: Math.max(1, Math.min(deadline - Date.now(), 1000)) });
        result = await loc.evaluate(POINTER_EVENTS_LOCATOR_JS, { x, y, box });
      } catch {
        result = null;
      }
    }

    // An indeterminate result fails open — failing closed would block legitimate
    // clicks. But once a miss has been *determined*, a later indeterminate
    // attempt must not launder it into a pass: near the deadline the boundingBox
    // timeout is clamped to ~1ms and always throws, which used to turn a proven
    // miss into "unknown" and let the click through silently (#329).
    if (!result) {
      if (lastMiss !== null && Date.now() >= deadline) {
        throw new ElementNotReceivingEventsError(selector, lastMiss);
      }
      return;
    }
    if (result.hit) return;

    const covering = (result as any)?.covering ?? 'unknown';
    lastMiss = covering;
    if (Date.now() >= deadline) throw new ElementNotReceivingEventsError(selector, covering);

    await backoffSleep(attempt);
    attempt++;
  }
}

// ---------------------------------------------------------------------------
// ElementHandle variant
// ---------------------------------------------------------------------------

export async function ensureActionableHandle(
  el: ElementHandle,
  checks: ReadonlySet<CheckName>,
  timeout: number = 30000,
  force: boolean = false,
): Promise<void> {
  if (force) return;

  const deadline = Date.now() + timeout;
  let attempt = 0;
  let lastError: ActionabilityError | null = null;
  const label = '<ElementHandle>';

  while (true) {
    const remainingMs = Math.max(0, deadline - Date.now());
    if (remainingMs <= 0) {
      if (lastError) throw lastError;
      throw new ActionabilityError(label, 'timeout', 'timeout expired before first check');
    }

    try {
      if (checks.has('visible')) {
        try {
          await el.waitForElementState('visible', { timeout: Math.max(1, Math.min(remainingMs, 2000)) });
        } catch {
          throw new ElementNotVisibleError(label);
        }
      }

      if (checks.has('enabled')) {
        try {
          await el.waitForElementState('enabled', { timeout: Math.max(1, Math.min(remainingMs, 2000)) });
        } catch {
          throw new ElementNotEnabledError(label);
        }
      }

      if (checks.has('editable')) {
        try {
          await el.waitForElementState('editable', { timeout: Math.max(1, Math.min(remainingMs, 2000)) });
        } catch {
          throw new ElementNotEditableError(label);
        }
      }

      return;
    } catch (e) {
      if (e instanceof ActionabilityError) {
        lastError = e;
        if (Date.now() >= deadline) throw lastError;
        await backoffSleep(attempt);
        attempt++;
      } else {
        throw e;
      }
    }
  }
}

export async function checkPointerEventsHandle(
  el: ElementHandle,
  x: number,
  y: number,
  timeout: number = 5000,
): Promise<void> {
  const deadline = Date.now() + timeout;
  let attempt = 0;

  while (true) {
    let result: any;
    try {
      const box = await el.boundingBox();
      result = await el.evaluate(POINTER_EVENTS_HANDLE_JS, { x, y, box });
    } catch {
      result = null;
    }

    if (!result || result.hit) return;

    const covering = (result as any)?.covering ?? 'unknown';
    if (Date.now() >= deadline) throw new ElementNotReceivingEventsError('<ElementHandle>', covering);

    await backoffSleep(attempt);
    attempt++;
  }
}
