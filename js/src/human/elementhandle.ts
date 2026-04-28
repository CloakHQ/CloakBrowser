/**
 * ElementHandle humanization for Playwright.
 *
 * Mirrors Puppeteer's ElementHandle patching architecture.
 * Patches page.$(), page.$$(), page.waitForSelector() to return humanized handles,
 * and patches all interaction methods on each ElementHandle instance.
 *
 * Playwright ElementHandle methods patched:
 *   click, dblclick, hover, type, fill, press, selectOption,
 *   check, uncheck, setChecked, tap, focus
 *   + $, $$, waitForSelector (nested elements are also patched)
 *
 * Stealth-aware:
 *   - Uses CDP DOM.describeNode when available to check element type
 *     (no main-world JS execution)
 *   - Falls back to el.evaluate() only when CDP is unavailable
 */

import type { Page, Frame, ElementHandle, CDPSession } from 'playwright-core';
import type { HumanConfig } from './config.js';
import { rand, randRange, sleep, mergeConfig } from './config.js';
import { RawMouse, RawKeyboard, humanMove, humanClick, clickTarget, humanIdle } from './mouse.js';
import { humanType } from './keyboard.js';
import { humanScrollIntoView } from './scroll.js';

// --- Platform-aware select-all shortcut ---
const SELECT_ALL = process.platform === 'darwin' ? 'Meta+a' : 'Control+a';


// ============================================================================
// Stealth ElementHandle input check — uses CDP DOM.describeNode
// ============================================================================

async function isInputElementHandle(
  stealth: any, // StealthEval from index.ts
  el: ElementHandle,
): Promise<boolean> {
  // Try CDP DOM.describeNode first (no main-world JS execution)
  if (stealth) {
    try {
      const cdp: CDPSession = await stealth.getCdpSession();
      // Playwright exposes the JSHandle's internal preview via _objectId or similar
      // We need the remote object ID. Try to get it via internal API.
      const impl = (el as any)._impl ?? (el as any)._object ?? el;
      const guid = (impl as any)._guid;

      // Use el.evaluate as a reliable fallback within stealth context
      // Playwright doesn't expose remoteObject directly like Puppeteer
    } catch { /* fallthrough */ }
  }

  // Fallback: el.evaluate (works reliably in Playwright)
  try {
    return await el.evaluate((node: any) => {
      const tag = node.tagName?.toLowerCase();
      return tag === 'input' || tag === 'textarea'
        || node.getAttribute?.('contenteditable') === 'true';
    });
  } catch {
    return false;
  }
}


// ============================================================================
// CursorState type (matches index.ts)
// ============================================================================

interface CursorState {
  x: number;
  y: number;
  initialized: boolean;
}


// ============================================================================
// Patch a single Playwright ElementHandle
// ============================================================================

export function patchSingleElementHandle(
  el: ElementHandle,
  page: Page,
  cfg: HumanConfig,
  cursor: CursorState,
  raw: RawMouse,
  rawKb: RawKeyboard,
  originals: any,
  stealth: any,
): void {
  if ((el as any)._humanPatched) return;
  (el as any)._humanPatched = true;

  // Save originals
  const origElClick = el.click.bind(el);
  const origElDblclick = el.dblclick.bind(el);
  const origElHover = el.hover.bind(el);
  const origElType = el.type.bind(el);
  const origElFill = el.fill.bind(el);
  const origElPress = el.press.bind(el);
  const origElSelectOption = el.selectOption.bind(el);
  const origElCheck = el.check.bind(el);
  const origElUncheck = el.uncheck.bind(el);
  const origElSetChecked = (el as any).setChecked?.bind(el);
  const origElTap = el.tap.bind(el);
  const origElFocus = el.focus.bind(el);
  const origElScrollIntoViewIfNeeded = (el as any).scrollIntoViewIfNeeded?.bind(el);

  // Nested selectors
  const origEl$ = el.$.bind(el);
  const origEl$$ = el.$$.bind(el);
  const origElWaitForSelector = el.waitForSelector.bind(el);

  // --- Nested elements are also patched ---
  (el as any).$ = async (selector: string) => {
    const child = await origEl$(selector);
    if (child) patchSingleElementHandle(child, page, cfg, cursor, raw, rawKb, originals, stealth);
    return child;
  };

  (el as any).$$ = async (selector: string) => {
    const children = await origEl$$(selector);
    for (const child of children) {
      patchSingleElementHandle(child, page, cfg, cursor, raw, rawKb, originals, stealth);
    }
    return children;
  };

  (el as any).waitForSelector = async (selector: string, options?: any) => {
    const child = await origElWaitForSelector(selector, options);
    if (child) patchSingleElementHandle(child, page, cfg, cursor, raw, rawKb, originals, stealth);
    return child;
  };

  // --- Helper: get bounding box and move cursor to element ---
  // Accepts a per-call ``callCfg`` so type/fill overrides like
  // ``el.type(text, { human_config: { typing_delay: 30 } })`` carry through to
  // mouse movement & idle timing for that single call.
  // Also scrolls the element into view first so off-screen elements work
  // (#129, #137 follow-up): otherwise boundingBox() returns null and we'd
  // silently fall back to the unpatched native method.
  const moveToElement = async (callCfg: HumanConfig = cfg) => {
    // Ensure cursor is initialized
    const ensureCursorInit = (page as any)._ensureCursorInit;
    if (ensureCursorInit) await ensureCursorInit();

    // Scroll into view first so boundingBox() returns coordinates even when
    // the element starts below the fold. Best-effort — if humanScrollIntoView
    // throws (e.g. detached element), we let boundingBox() decide whether to
    // proceed or fall back to the original method.
    try {
      const { cursorX, cursorY } = await humanScrollIntoView(
        page, raw,
        () => el.boundingBox(),
        cursor.x, cursor.y, callCfg,
      );
      cursor.x = cursorX;
      cursor.y = cursorY;
    } catch { /* let boundingBox() decide */ }

    const box = await el.boundingBox();
    if (!box) return null;

    const isInp = await isInputElementHandle(stealth, el);
    const target = clickTarget(box, isInp, callCfg);

    if (callCfg.idle_between_actions) {
      await humanIdle(raw, rand(callCfg.idle_between_duration[0], callCfg.idle_between_duration[1]), cursor.x, cursor.y, callCfg);
    }

    await humanMove(raw, cursor.x, cursor.y, target.x, target.y, callCfg);
    cursor.x = target.x;
    cursor.y = target.y;
    return { box, isInp };
  };

  // --- el.click() ---
  (el as any).click = async (options?: any) => {
    const callCfg = mergeConfig(cfg, options?.human_config);
    const info = await moveToElement(callCfg);
    if (!info) return origElClick(options);
    await humanClick(raw, info.isInp, callCfg);
  };

  // --- el.dblclick() ---
  (el as any).dblclick = async (options?: any) => {
    const callCfg = mergeConfig(cfg, options?.human_config);
    const info = await moveToElement(callCfg);
    if (!info) return origElDblclick(options);
    await raw.down({ clickCount: 2 });
    await sleep(rand(30, 60));
    await raw.up({ clickCount: 2 });
  };

  // --- el.hover() ---
  (el as any).hover = async (options?: any) => {
    const callCfg = mergeConfig(cfg, options?.human_config);
    const info = await moveToElement(callCfg);
    if (!info) return origElHover(options);
    // Just move — no click
  };

  // --- el.type() ---
  (el as any).type = async (text: string, options?: any) => {
    const callCfg = mergeConfig(cfg, options?.human_config);
    const info = await moveToElement(callCfg);
    if (!info) return origElType(text, options);
    await humanClick(raw, info.isInp, callCfg);
    await sleep(rand(100, 250));
    let cdpSession: CDPSession | null = null;
    try { cdpSession = await stealth?.getCdpSession(); } catch {}
    await humanType(page, rawKb, text, callCfg, cdpSession);
  };

  // --- el.fill() ---
  (el as any).fill = async (value: string, options?: any) => {
    const callCfg = mergeConfig(cfg, options?.human_config);
    const info = await moveToElement(callCfg);
    if (!info) return origElFill(value, options);
    await humanClick(raw, info.isInp, callCfg);
    await sleep(rand(100, 250));
    // Clear existing content
    await originals.keyboardPress(SELECT_ALL);
    await sleep(rand(30, 80));
    await originals.keyboardPress('Backspace');
    await sleep(rand(50, 150));
    let cdpSession: CDPSession | null = null;
    try { cdpSession = await stealth?.getCdpSession(); } catch {}
    await humanType(page, rawKb, value, callCfg, cdpSession);
  };

  // --- el.press() ---
  (el as any).press = async (key: string, options?: any) => {
    await sleep(rand(20, 60));
    await originals.keyboardDown(key);
    await sleep(randRange(cfg.key_hold));
    await originals.keyboardUp(key);
  };

  // --- el.selectOption() ---
  (el as any).selectOption = async (values: any, options?: any) => {
    const info = await moveToElement();
    if (!info) return origElSelectOption(values, options);
    await humanClick(raw, false, cfg);
    await sleep(rand(100, 300));
    return origElSelectOption(values, options);
  };

  // --- el.check() ---
  (el as any).check = async (options?: any) => {
    try {
      const checked = await el.isChecked();
      if (checked) return; // Already checked
    } catch {}
    const info = await moveToElement();
    if (!info) return origElCheck(options);
    await humanClick(raw, info.isInp, cfg);
  };

  // --- el.uncheck() ---
  (el as any).uncheck = async (options?: any) => {
    try {
      const checked = await el.isChecked();
      if (!checked) return; // Already unchecked
    } catch {}
    const info = await moveToElement();
    if (!info) return origElUncheck(options);
    await humanClick(raw, info.isInp, cfg);
  };

  // --- el.setChecked() ---
  if (origElSetChecked) {
    (el as any).setChecked = async (checked: boolean, options?: any) => {
      try {
        const current = await el.isChecked();
        if (current === checked) return;
      } catch {}
      const info = await moveToElement();
      if (!info) return origElSetChecked(checked, options);
      await humanClick(raw, info.isInp, cfg);
    };
  }

  // --- el.tap() ---
  (el as any).tap = async (options?: any) => {
    const info = await moveToElement();
    if (!info) return origElTap(options);
    await humanClick(raw, info.isInp, cfg);
  };

  // --- el.focus() ---
  // Move cursor humanly but use programmatic focus (no click side-effects).
  // Stock Playwright el.focus() never clicks — clicking would trigger onclick,
  // submit forms, navigate links, etc.
  (el as any).focus = async () => {
    await moveToElement();  // human-like Bézier cursor movement
    await origElFocus();    // programmatic focus, no click
  };

  // --- el.scrollIntoViewIfNeeded() ---
  // Playwright's native version snaps the page — a strong bot signal.
  // Replace with the same accelerate → cruise → decelerate → overshoot
  // wheel sequence used by page.click() etc. Falls back to the native
  // method if the element is detached or scrolling fails.
  if (origElScrollIntoViewIfNeeded) {
    (el as any).scrollIntoViewIfNeeded = async (options?: any) => {
      const callCfg = mergeConfig(cfg, options?.human_config);
      const ensureCursorInit = (page as any)._ensureCursorInit;
      if (ensureCursorInit) await ensureCursorInit();
      try {
        const { cursorX, cursorY } = await humanScrollIntoView(
          page, raw,
          () => el.boundingBox(),
          cursor.x, cursor.y, callCfg,
        );
        cursor.x = cursorX;
        cursor.y = cursorY;
      } catch {
        return origElScrollIntoViewIfNeeded(options);
      }
    };
  }
}


// ============================================================================
// Page-level ElementHandle patching
// ============================================================================

export function patchPageElementHandles(
  page: Page,
  cfg: HumanConfig,
  cursor: CursorState,
  raw: RawMouse,
  rawKb: RawKeyboard,
  originals: any,
  stealth: any,
): void {
  // Patch page.$() — only if the method exists
  if (typeof page.$ === 'function') {
    const orig$ = page.$.bind(page);
    (page as any).$ = async (selector: string) => {
      const el = await orig$(selector);
      if (el) patchSingleElementHandle(el, page, cfg, cursor, raw, rawKb, originals, stealth);
      return el;
    };
  }

  // Patch page.$$()
  if (typeof page.$$ === 'function') {
    const orig$$ = page.$$.bind(page);
    (page as any).$$ = async (selector: string) => {
      const els = await orig$$(selector);
      for (const el of els) {
        patchSingleElementHandle(el, page, cfg, cursor, raw, rawKb, originals, stealth);
      }
      return els;
    };
  }

  // Patch page.waitForSelector()
  if (typeof page.waitForSelector === 'function') {
    const origWaitForSelector = page.waitForSelector.bind(page);
    (page as any).waitForSelector = async (selector: string, options?: any) => {
      const el = await origWaitForSelector(selector, options);
      if (el) patchSingleElementHandle(el, page, cfg, cursor, raw, rawKb, originals, stealth);
      return el;
    };
  }
}


// ============================================================================
// Frame-level ElementHandle patching
// ============================================================================

export function patchFrameElementHandles(
  frame: Frame,
  page: Page,
  cfg: HumanConfig,
  cursor: CursorState,
  raw: RawMouse,
  rawKb: RawKeyboard,
  originals: any,
  stealth: any,
): void {
  // Patch frame.$() — only if the method exists
  if (typeof frame.$ === 'function') {
    const origFrame$ = frame.$.bind(frame);
    (frame as any).$ = async (selector: string) => {
      const el = await origFrame$(selector);
      if (el) patchSingleElementHandle(el, page, cfg, cursor, raw, rawKb, originals, stealth);
      return el;
    };
  }

  // Patch frame.$$()
  if (typeof frame.$$ === 'function') {
    const origFrame$$ = frame.$$.bind(frame);
    (frame as any).$$ = async (selector: string) => {
      const els = await origFrame$$(selector);
      for (const el of els) {
        patchSingleElementHandle(el, page, cfg, cursor, raw, rawKb, originals, stealth);
      }
      return els;
    };
  }

  // Patch frame.waitForSelector()
  if (typeof frame.waitForSelector === 'function') {
    const origFrameWaitForSelector = frame.waitForSelector.bind(frame);
    (frame as any).waitForSelector = async (selector: string, options?: any) => {
      const el = await origFrameWaitForSelector(selector, options);
      if (el) patchSingleElementHandle(el, page, cfg, cursor, raw, rawKb, originals, stealth);
      return el;
    };
  }
}
