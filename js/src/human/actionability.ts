/**
 * Playwright-style actionability checks for the humanize layer.
 *
 * Selector-based reads stay inside the CDP isolated world. ElementHandle paths
 * remain separate because they already identify an exact Playwright handle.
 */

import type { Page, Frame, ElementHandle } from 'playwright-core';
import {
  buildActionableJs, buildBoxJs, buildValidateJs, evalParsed, getWorld,
  OK, NOT_FOUND, UNSUPPORTED, STALE, EVALUATION_FAILED,
  StealthEvaluationError, StealthWorldUnavailableError,
  UnsupportedHumanizeSelectorError, type StealthWorld,
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

export class ElementTargetChangedError extends ActionabilityError {
  constructor(selector: string) {
    super(selector, 'target_identity', 'selector resolved to a different element before input dispatch');
    this.name = 'ElementTargetChangedError';
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

async function stealthActionable(
  pageOrFrame: Page | Frame,
  selector: string,
  checks: ReadonlySet<CheckName>,
): Promise<void> {
  const world = getWorld(pageOrFrame);
  if (!world) throw new StealthWorldUnavailableError();

  const { status, data } = await evalParsed(world, buildActionableJs(selector));
  if (status === UNSUPPORTED) throw new UnsupportedHumanizeSelectorError(selector);
  if (status === EVALUATION_FAILED) throw new StealthEvaluationError(selector);
  if (status === NOT_FOUND) throw new ElementNotAttachedError(selector);
  if (status !== OK || !data) throw new StealthEvaluationError(selector);
  if (checks.has('visible') && !data.visible) throw new ElementNotVisibleError(selector);
  if (checks.has('enabled') && !data.enabled) throw new ElementNotEnabledError(selector);
  if (checks.has('editable') && !data.editable) throw new ElementNotEditableError(selector);
}

async function readBox(
  pageOrFrame: Page | Frame,
  selector: string,
): Promise<{ x: number; y: number; width: number; height: number } | null> {
  const world = getWorld(pageOrFrame);
  if (!world) throw new StealthWorldUnavailableError();

  const { status, data } = await evalParsed(world, buildBoxJs(selector));
  if (status === OK && data?.box) return data.box;
  if (status === NOT_FOUND) return null;
  if (status === UNSUPPORTED) throw new UnsupportedHumanizeSelectorError(selector);
  throw new StealthEvaluationError(selector);
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
  let lastError: Error | null = null;

  while (true) {
    const remainingMs = Math.max(0, deadline - Date.now());
    if (remainingMs <= 0) {
      if (lastError) throw lastError;
      throw new ActionabilityError(selector, 'timeout', 'timeout expired before first check');
    }

    try {
      await stealthActionable(pageOrFrame, selector, checks);
      return;
    } catch (error) {
      if (error instanceof ActionabilityError || error instanceof StealthEvaluationError) {
        lastError = error;
        if (Date.now() >= deadline) throw lastError;
        await backoffSleep(attempt++);
      } else {
        throw error;
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

    try {
      const box1 = await readBox(pageOrFrame, selector);
      if (!box1) throw new ElementNotAttachedError(selector);

      await new Promise(resolve => setTimeout(resolve, 100));

      const box2 = await readBox(pageOrFrame, selector);
      if (!box2) throw new ElementNotAttachedError(selector);
      if (!boxesDiffer(box1, box2)) return;
    } catch (error) {
      if (error instanceof StealthEvaluationError) {
        if (Date.now() >= deadline) throw error;
        await backoffSleep(attempt++);
        continue;
      }
      throw error;
    }

    if (Date.now() >= deadline) throw new ElementNotStableError(selector);
    await backoffSleep(attempt++);
  }
}

// ---------------------------------------------------------------------------
// Pointer-events and exact-target check
// ---------------------------------------------------------------------------

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
  targetId: number,
  gen: number,
  x: number,
  y: number,
  stealth?: StealthWorld | null,
  timeout: number = 5000,
): Promise<void> {
  const deadline = Date.now() + timeout;
  let attempt = 0;
  let lastMiss: string | null = null;
  const world = stealth ?? getWorld(pageOrFrame);

  if (!world) throw new StealthWorldUnavailableError();
  if (!Number.isInteger(targetId) || !Number.isInteger(gen)) throw new StealthEvaluationError(selector);

  while (true) {
    const { status, data } = await evalParsed(
      world,
      buildValidateJs(selector, targetId, gen, x, y),
    );

    if (status === UNSUPPORTED) throw new UnsupportedHumanizeSelectorError(selector);
    if (status === STALE) throw new ElementTargetChangedError(selector);
    if (status === NOT_FOUND) throw new ElementNotAttachedError(selector);
    if (status === EVALUATION_FAILED) {
      if (Date.now() >= deadline) throw new StealthEvaluationError(selector);
    } else if (status === OK && data && data.hit) {
      return;
    } else if (status === OK && data) {
      lastMiss = data.covering ?? 'unknown';
      if (Date.now() >= deadline) {
        throw new ElementNotReceivingEventsError(selector, lastMiss ?? 'unknown');
      }
    } else {
      throw new StealthEvaluationError(selector);
    }

    await backoffSleep(attempt++);
  }
}

// ---------------------------------------------------------------------------
// ElementHandle variant (legacy handle-scoped path)
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
    } catch (error) {
      if (error instanceof ActionabilityError) {
        lastError = error;
        if (Date.now() >= deadline) throw lastError;
        await backoffSleep(attempt++);
      } else {
        throw error;
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

    const covering = result?.covering ?? 'unknown';
    if (Date.now() >= deadline) {
      throw new ElementNotReceivingEventsError('<ElementHandle>', covering);
    }
    await backoffSleep(attempt++);
  }
}
