/**
 * Human-like behavioral layer for cloakbrowser — Puppeteer edition.
 *
 * Mirrors Playwright humanize architecture, adapted for Puppeteer API.
 *
 * Patches ALL native Puppeteer interaction surfaces:
 *
 * PAGE-LEVEL:
 *   click (with clickCount support for dblclick), hover, type,
 *   select, focus, tap, goto
 *
 * MOUSE:
 *   move, click (with clickCount support for dblclick), wheel,
 *   dragAndDrop
 *
 * KEYBOARD:
 *   type, down, up, press, sendCharacter
 *
 * FRAME-LEVEL:
 *   click, hover, type, select, focus, tap
 *   + $, $$, waitForSelector (return patched ElementHandles)
 *
 * ELEMENTHANDLE-LEVEL (Puppeteer-specific, no Playwright equivalent):
 *   click (with clickCount), hover, type, press, tap, select,
 *   focus, drop, dragAndDrop
 *   + $, $$, waitForSelector (nested elements are also patched)
 *
 * BROWSER-LEVEL:
 *   newPage, createBrowserContext / createIncognitoBrowserContext,
 *   targetcreated event
 *
 * Stealth-aware:
 *   - isInputElement / isSelectorFocused use CDP Isolated Worlds
 *   - Shift symbol typing uses CDP Input.dispatchKeyEvent (isTrusted=true)
 *   - ElementHandle isInput check uses CDP DOM.describeNode (no JS execution)
 *   - Falls back to page.evaluate only when CDP session is unavailable
 *
 * Puppeteer-specific adaptations:
 *   - page.createCDPSession() instead of context.newCDPSession(page)
 *   - page.viewport() instead of page.viewportSize()
 *   - page.$(selector) instead of page.locator(selector)
 *   - keyboard.sendCharacter() mapped via RawKeyboard.insertText
 *   - mouse.wheel({deltaX, deltaY}) object form adapted to (dx, dy)
 *   - page.select() instead of page.selectOption()
 *   - ElementHandle prototype patching (Puppeteer-only)
 *   - No page.dblclick() — Puppeteer uses click({clickCount:2})
 */

import type { Browser, Page, Frame, CDPSession, ElementHandle, BrowserContext } from 'puppeteer-core';
import type { HumanConfig } from '../human/config.js';
import { resolveConfig, mergeConfig, rand, randRange, sleep } from '../human/config.js';
import { RawMouse, RawKeyboard, humanMove, humanClick, clickTarget, humanIdle } from '../human/mouse.js';
import { humanType } from './keyboard.js';
import { scrollToElement, humanScrollIntoView, smoothWheel } from './scroll.js';

export type { HumanConfig } from '../human/config.js';
export { resolveConfig, mergeConfig } from '../human/config.js';
export { humanMove, humanClick, clickTarget, humanIdle } from '../human/mouse.js';
export { humanType } from './keyboard.js';
export { scrollToElement, humanScrollIntoView } from './scroll.js';


// ============================================================================
// CDP Isolated World — stealth DOM evaluation (Puppeteer version)
// ============================================================================

class StealthEval {
  private cdp: CDPSession | null = null;
  private contextId: number | null = null;
  private page: Page;

  constructor(page: Page) {
    this.page = page;
  }

  private async ensureCdp(): Promise<CDPSession> {
    if (!this.cdp) {
      this.cdp = await this.page.createCDPSession();
    }
    return this.cdp;
  }

  private async createWorld(): Promise<number> {
    const cdp = await this.ensureCdp();
    const tree = await cdp.send('Page.getFrameTree');
    const frameId = (tree as any).frameTree.frame.id;
    const result = await cdp.send('Page.createIsolatedWorld', {
      frameId,
      worldName: '',
      grantUniveralAccess: true,
    });
    const ctxId = (result as any).executionContextId;
    this.contextId = ctxId;
    return ctxId;
  }

  async evaluate(expression: string): Promise<any> {
    if (this.contextId === null) {
      await this.createWorld();
    }

    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const cdp = await this.ensureCdp();
        const result = await cdp.send('Runtime.evaluate', {
          expression,
          contextId: this.contextId!,
          returnByValue: true,
        });

        if ((result as any).exceptionDetails) {
          if (attempt === 0) {
            await this.createWorld();
            continue;
          }
          return undefined;
        }

        return (result as any).result?.value;
      } catch {
        if (attempt === 0) {
          this.contextId = null;
          try { await this.createWorld(); } catch { return undefined; }
          continue;
        }
        return undefined;
      }
    }
    return undefined;
  }

  invalidate(): void {
    this.contextId = null;
  }

  async getCdpSession(): Promise<CDPSession> {
    return this.ensureCdp();
  }
}


// ============================================================================
// Cursor state
// ============================================================================

class CursorState {
  x = 0;
  y = 0;
  initialized = false;
}


// ============================================================================
// Stealth DOM queries
// ============================================================================

async function isInputElement(
  stealth: StealthEval | null,
  page: Page,
  selector: string,
): Promise<boolean> {
  if (stealth) {
    try {
      const escaped = JSON.stringify(selector);
      const result = await stealth.evaluate(`
        (() => {
          const el = document.querySelector(${escaped});
          if (!el) return false;
          const tag = el.tagName.toLowerCase();
          return tag === 'input' || tag === 'textarea'
            || el.getAttribute('contenteditable') === 'true';
        })()
      `);
      return !!result;
    } catch { /* fallthrough */ }
  }

  return page.evaluate((sel: string) => {
    const el = document.querySelector(sel);
    if (!el) return false;
    const tag = el.tagName.toLowerCase();
    return tag === 'input' || tag === 'textarea'
      || el.getAttribute('contenteditable') === 'true';
  }, selector).catch(() => false);
}

async function isSelectorFocused(
  stealth: StealthEval | null,
  page: Page,
  selector: string,
): Promise<boolean> {
  if (stealth) {
    try {
      const escaped = JSON.stringify(selector);
      const result = await stealth.evaluate(`
        (() => {
          const el = document.querySelector(${escaped});
          return el === document.activeElement;
        })()
      `);
      return !!result;
    } catch { /* fallthrough */ }
  }

  return page.evaluate((sel: string) => {
    const el = document.querySelector(sel);
    return el === document.activeElement;
  }, selector).catch(() => false);
}


// ============================================================================
// Stealth ElementHandle input check — uses CDP DOM.describeNode
// instead of el.evaluate() to avoid main-world JS execution.
// ============================================================================

async function isInputElementHandle(
  stealth: StealthEval | null,
  el: ElementHandle,
): Promise<boolean> {
  if (stealth) {
    try {
      const cdp = await stealth.getCdpSession();
      const remoteObject = (el as any).remoteObject?.();
      if (remoteObject?.objectId) {
        const { node } = await cdp.send('DOM.describeNode', {
          objectId: remoteObject.objectId,
        }) as any;

        const tag = (node?.nodeName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea') return true;

        const attrs: string[] = node?.attributes || [];
        for (let i = 0; i < attrs.length; i += 2) {
          if (attrs[i] === 'contenteditable' && attrs[i + 1] === 'true') {
            return true;
          }
        }
        return false;
      }
    } catch { /* fallthrough to el.evaluate */ }
  }

  return el.evaluate((node: any) => {
    const tag = node.tagName?.toLowerCase();
    return tag === 'input' || tag === 'textarea'
      || node.getAttribute?.('contenteditable') === 'true';
  }).catch(() => false);
}


// ============================================================================
// Page-level patching
// ============================================================================

function patchPage(page: Page, cfg: HumanConfig, cursor: CursorState): void {
  const originals = {
    click: page.click.bind(page),
    hover: page.hover.bind(page),
    type: page.type.bind(page),
    select: page.select.bind(page),
    focus: page.focus.bind(page),
    goto: page.goto.bind(page),
    tap: page.tap.bind(page),

    mouseMove: page.mouse.move.bind(page.mouse),
    mouseClick: page.mouse.click.bind(page.mouse),
    mouseDown: page.mouse.down.bind(page.mouse),
    mouseUp: page.mouse.up.bind(page.mouse),
    mouseWheel: (page.mouse as any).wheel?.bind(page.mouse),
    mouseDragAndDrop: (page.mouse as any).dragAndDrop?.bind(page.mouse),

    keyboardType: page.keyboard.type.bind(page.keyboard),
    keyboardDown: page.keyboard.down.bind(page.keyboard) as (key: string) => Promise<void>,
    keyboardUp: page.keyboard.up.bind(page.keyboard) as (key: string) => Promise<void>,
    keyboardPress: page.keyboard.press.bind(page.keyboard),
    keyboardSendCharacter: page.keyboard.sendCharacter.bind(page.keyboard),
  };

  (page as any)._original = originals;
  (page as any)._humanCfg = cfg;

  const stealth = new StealthEval(page);
  (page as any)._stealth = stealth;

  let cdpSession: CDPSession | null = null;
  const ensureCdp = async (): Promise<CDPSession | null> => {
    if (!cdpSession) {
      try { cdpSession = await stealth.getCdpSession(); } catch {}
    }
    return cdpSession;
  };

  const raw: RawMouse = {
    move: originals.mouseMove,
    down: originals.mouseDown,
    up: originals.mouseUp,
    wheel: async (deltaX: number, deltaY: number) => {
      if (originals.mouseWheel) {
        await originals.mouseWheel({ deltaX, deltaY });
      }
    },
  };

  const rawKb: RawKeyboard = {
    down: originals.keyboardDown,
    up: originals.keyboardUp,
    type: originals.keyboardType,
    insertText: originals.keyboardSendCharacter,
  };

  async function ensureCursorInit(): Promise<void> {
    if (!cursor.initialized) {
      cursor.x = rand(cfg.initial_cursor_x[0], cfg.initial_cursor_x[1]);
      cursor.y = rand(cfg.initial_cursor_y[0], cfg.initial_cursor_y[1]);
      await originals.mouseMove(cursor.x, cursor.y);
      cursor.initialized = true;
    }
  }

  // ==== goto ====
  const humanGoto = async (url: string, options?: any) => {
    const response = await originals.goto(url, options);
    stealth.invalidate();
    patchFrames(page, cfg, cursor, raw, rawKb, originals, stealth);
    return response;
  };

  // ==== click (with clickCount support for dblclick) ====
  const humanClickFn = async (selector: string, options?: any) => {
    await ensureCursorInit();
    const callCfg = mergeConfig(cfg, options?.human_config);
    if (callCfg.idle_between_actions) {
      await humanIdle(raw, rand(callCfg.idle_between_duration[0], callCfg.idle_between_duration[1]), cursor.x, cursor.y, callCfg);
    }
    const { box, cursorX, cursorY } = await scrollToElement(page, raw, selector, cursor.x, cursor.y, callCfg, options?.timeout);
    cursor.x = cursorX;
    cursor.y = cursorY;
    const isInput = await isInputElement(stealth, page, selector);
    const target = clickTarget(box, isInput, callCfg);
    await humanMove(raw, cursor.x, cursor.y, target.x, target.y, callCfg);
    cursor.x = target.x;
    cursor.y = target.y;

    const clickCount = options?.clickCount ?? options?.count ?? 1;
    if (clickCount >= 2) {
      await humanClick(raw, isInput, callCfg);
      await sleep(rand(40, 90));
      await raw.down({ clickCount: 2 });
      await sleep(rand(30, 60));
      await raw.up({ clickCount: 2 });
    } else {
      await humanClick(raw, isInput, callCfg);
    }
  };

  // ==== hover ====
  const humanHoverFn = async (selector: string, options?: any) => {
    await ensureCursorInit();
    const callCfg = mergeConfig(cfg, options?.human_config);
    if (callCfg.idle_between_actions) {
      await humanIdle(raw, rand(callCfg.idle_between_duration[0], callCfg.idle_between_duration[1]), cursor.x, cursor.y, callCfg);
    }
    const { box, cursorX, cursorY } = await scrollToElement(page, raw, selector, cursor.x, cursor.y, callCfg, options?.timeout);
    cursor.x = cursorX;
    cursor.y = cursorY;
    const target = clickTarget(box, false, callCfg);
    await humanMove(raw, cursor.x, cursor.y, target.x, target.y, callCfg);
    cursor.x = target.x;
    cursor.y = target.y;
  };

  // ==== type ====
  const humanTypeFn = async (selector: string, text: string, options?: any) => {
    const callCfg = mergeConfig(cfg, options?.human_config);
    await sleep(randRange(callCfg.field_switch_delay));
    await humanClickFn(selector, options);
    await sleep(rand(100, 250));
    const cdp = await ensureCdp();
    await humanType(page, rawKb, text, callCfg, cdp);
  };

  // ==== select ====
  const humanSelectFn = async (selector: string, ...values: string[]) => {
    await humanHoverFn(selector);
    await sleep(rand(100, 300));
    return originals.select(selector, ...values);
  };

  // ==== focus ====
  const humanFocusFn = async (selector: string) => {
    if (!await isSelectorFocused(stealth, page, selector)) {
      await humanClickFn(selector);
    }
  };

  // ==== tap ====
  const humanTapFn = async (selector: string, options?: any) => {
    await humanClickFn(selector, options);
  };

  // ============================================================
  // Assign page-level patches
  // ============================================================
  (page as any).goto = humanGoto;
  (page as any).click = humanClickFn;
  (page as any).hover = humanHoverFn;
  (page as any).type = humanTypeFn;
  (page as any).select = humanSelectFn;
  (page as any).focus = humanFocusFn;
  (page as any).tap = humanTapFn;

  // ============================================================
  // Mouse patches
  // ============================================================
  page.mouse.move = async (x: number, y: number, options?: any) => {
    await ensureCursorInit();
    await humanMove(raw, cursor.x, cursor.y, x, y, cfg);
    cursor.x = x;
    cursor.y = y;
  };

  page.mouse.click = async (x: number, y: number, options?: any) => {
    await ensureCursorInit();
    await humanMove(raw, cursor.x, cursor.y, x, y, cfg);
    cursor.x = x;
    cursor.y = y;

    const clickCount = options?.clickCount ?? options?.count ?? 1;
    if (clickCount >= 2) {
      await humanClick(raw, false, cfg);
      await sleep(rand(40, 90));
      await raw.down({ clickCount: 2 });
      await sleep(rand(30, 60));
      await raw.up({ clickCount: 2 });
    } else {
      await humanClick(raw, false, cfg);
    }
  };

  if (originals.mouseWheel) {
    (page.mouse as any).wheel = async (options?: { deltaX?: number; deltaY?: number }) => {
      const dx = options?.deltaX ?? 0;
      const dy = options?.deltaY ?? 0;
      if (Math.abs(dy) > 0) {
        await smoothWheel(raw, dy, cfg, 'y');
      }
      if (Math.abs(dx) > 0) {
        await smoothWheel(raw, dx, cfg, 'x');
      }
    };
  }

  if (originals.mouseDragAndDrop) {
    (page.mouse as any).dragAndDrop = async (
      start: { x: number; y: number },
      target: { x: number; y: number },
      options?: any,
    ) => {
      await ensureCursorInit();
      await humanMove(raw, cursor.x, cursor.y, start.x, start.y, cfg);
      cursor.x = start.x;
      cursor.y = start.y;
      await sleep(rand(100, 200));
      await originals.mouseDown();
      await sleep(rand(80, 150));
      await humanMove(raw, cursor.x, cursor.y, target.x, target.y, cfg);
      cursor.x = target.x;
      cursor.y = target.y;
      await sleep(rand(80, 150));
      await originals.mouseUp();
    };
  }

  // ============================================================
  // Keyboard patches
  // ============================================================
  page.keyboard.type = async (text: string, options?: any) => {
    const cdp = await ensureCdp();
    await humanType(page, rawKb, text, cfg, cdp);
  };

  page.keyboard.press = async (key: any, options?: any) => {
    await sleep(rand(20, 60));
    await originals.keyboardDown(key as any);
    await sleep(randRange(cfg.key_hold));
    await originals.keyboardUp(key as any);
  };

  page.keyboard.down = async (key: any) => {
    await sleep(rand(10, 30));
    await originals.keyboardDown(key as any);
  };

  page.keyboard.up = async (key: any) => {
    await sleep(rand(10, 30));
    await originals.keyboardUp(key as any);
  };

  // ============================================================
  // Store helpers for frame/element patching
  // ============================================================
  (page as any)._humanCursor = cursor;
  (page as any)._humanRaw = raw;
  (page as any)._humanRawKb = rawKb;
  (page as any)._ensureCursorInit = ensureCursorInit;

  // Initialize cursor
  cursor.x = rand(cfg.initial_cursor_x[0], cfg.initial_cursor_x[1]);
  cursor.y = rand(cfg.initial_cursor_y[0], cfg.initial_cursor_y[1]);
  originals.mouseMove(cursor.x, cursor.y).then(() => {
    cursor.initialized = true;
  }).catch(() => {});

  // Patch frames
  patchFrames(page, cfg, cursor, raw, rawKb, originals, stealth);

  // Patch ElementHandle selectors
  patchElementHandle(page, cfg, cursor, raw, rawKb, originals, stealth);
}


// ============================================================================
// ElementHandle patching — PUPPETEER-SPECIFIC
// ============================================================================

function patchElementHandle(
  page: Page,
  cfg: HumanConfig,
  cursor: CursorState,
  raw: RawMouse,
  rawKb: RawKeyboard,
  originals: any,
  stealth: StealthEval,
): void {
  const orig$ = page.$.bind(page);
  const orig$$ = page.$$.bind(page);
  const origWaitForSelector = page.waitForSelector.bind(page);

  (page as any).$ = async (selector: string) => {
    const el = await orig$(selector);
    if (el) patchSingleElementHandle(el, page, cfg, cursor, raw, rawKb, originals, stealth);
    return el;
  };

  (page as any).$$ = async (selector: string) => {
    const els = await orig$$(selector);
    for (const el of els) {
      patchSingleElementHandle(el, page, cfg, cursor, raw, rawKb, originals, stealth);
    }
    return els;
  };

  (page as any).waitForSelector = async (selector: string, options?: any) => {
    const el = await origWaitForSelector(selector, options);
    if (el) patchSingleElementHandle(el, page, cfg, cursor, raw, rawKb, originals, stealth);
    return el;
  };
}

function patchSingleElementHandle(
  el: ElementHandle,
  page: Page,
  cfg: HumanConfig,
  cursor: CursorState,
  raw: RawMouse,
  rawKb: RawKeyboard,
  originals: any,
  stealth: StealthEval,
): void {
  if ((el as any)._humanPatched) return;
  (el as any)._humanPatched = true;

  const origElClick = el.click.bind(el);
  const origElHover = el.hover.bind(el);
  const origElType = el.type.bind(el);
  const origElPress = (el as any).press?.bind(el);
  const origElTap = (el as any).tap?.bind(el);
  const origElFocus = (el as any).focus?.bind(el);
  const origElDragAndDrop = (el as any).dragAndDrop?.bind(el);
  const origElSelect = (el as any).select?.bind(el);
  const origElDrop = (el as any).drop?.bind(el);
  // Puppeteer v22+ adds ElementHandle.scrollIntoView(); earlier versions
  // expose it implicitly via evaluate(node => node.scrollIntoView()).
  const origElScrollIntoView = (el as any).scrollIntoView?.bind(el);

  // --- Nested selectors ---
  const origEl$ = el.$.bind(el);
  const origEl$$ = el.$$.bind(el);
  const origElWaitForSelector = el.waitForSelector.bind(el);

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

  // --- Helper: get box and move cursor. Accepts a per-call ``callCfg``
  // so type/fill overrides like ``el.type(text, { human_config: {...} })``
  // carry through to mouse timing for that single call. Also scrolls into
  // view first so off-screen elements work (#129, #137 follow-up).
  const moveToElement = async (callCfg: HumanConfig = cfg) => {
    await (page as any)._ensureCursorInit();

    try {
      const { cursorX, cursorY } = await humanScrollIntoView(
        page, raw,
        () => el.boundingBox().then(b => b ?? null),
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

    const clickCount = options?.clickCount ?? options?.count ?? 1;
    if (clickCount >= 2) {
      await humanClick(raw, info.isInp, callCfg);
      await sleep(rand(40, 90));
      await raw.down({ clickCount: 2 });
      await sleep(rand(30, 60));
      await raw.up({ clickCount: 2 });
    } else {
      await humanClick(raw, info.isInp, callCfg);
    }
  };

  // --- el.hover() ---
  (el as any).hover = async () => {
    const info = await moveToElement();
    if (!info) return origElHover();
  };

  // --- el.type() ---
  (el as any).type = async (text: string, options?: any) => {
    const callCfg = mergeConfig(cfg, options?.human_config);
    const info = await moveToElement(callCfg);
    if (!info) return origElType(text, options);
    await humanClick(raw, info.isInp, callCfg);
    await sleep(rand(100, 250));
    const cdp = await stealth.getCdpSession().catch(() => null);
    await humanType(page, rawKb, text, callCfg, cdp);
  };

  // --- el.scrollIntoView() ---
  // Puppeteer-only equivalent of Playwright's scrollIntoViewIfNeeded.
  // Replaces the native snap-scroll (a strong bot signal) with the same
  // accelerate → cruise → decelerate → overshoot wheel sequence used by
  // page.click(). Only patched when the underlying ElementHandle exposes
  // ``scrollIntoView`` (Puppeteer v22+).
  if (origElScrollIntoView) {
    (el as any).scrollIntoView = async (options?: any) => {
      const callCfg = mergeConfig(cfg, options?.human_config);
      await (page as any)._ensureCursorInit();
      try {
        const { cursorX, cursorY } = await humanScrollIntoView(
          page, raw,
          () => el.boundingBox().then(b => b ?? null),
          cursor.x, cursor.y, callCfg,
        );
        cursor.x = cursorX;
        cursor.y = cursorY;
      } catch {
        return origElScrollIntoView(options);
      }
    };
  }

  // --- el.press() ---
  if (origElPress) {
    (el as any).press = async (key: string, options?: any) => {
      await sleep(rand(20, 60));
      await originals.keyboardDown(key as any);
      await sleep(randRange(cfg.key_hold));
      await originals.keyboardUp(key as any);
    };
  }

  // --- el.tap() ---
  if (origElTap) {
    (el as any).tap = async () => {
      const info = await moveToElement();
      if (!info) return origElTap();
      await humanClick(raw, info.isInp, cfg);
    };
  }

  // --- el.focus() ---
  if (origElFocus) {
    (el as any).focus = async () => {
      const info = await moveToElement();
      if (!info) return origElFocus();
      await humanClick(raw, info.isInp, cfg);
    };
  }

  // --- el.select() ---
  if (origElSelect) {
    (el as any).select = async (...values: string[]) => {
      const info = await moveToElement();
      if (!info) return origElSelect(...values);
      await humanClick(raw, false, cfg);
      await sleep(rand(100, 300));
      return origElSelect(...values);
    };
  }

  // --- el.drop() ---
  if (origElDrop) {
    (el as any).drop = async (draggable: ElementHandle, options?: any) => {
      const srcBox = await draggable.boundingBox();
      const tgtBox = await el.boundingBox();

      if (srcBox && tgtBox) {
        const sx = srcBox.x + srcBox.width / 2;
        const sy = srcBox.y + srcBox.height / 2;
        const tx = tgtBox.x + tgtBox.width / 2;
        const ty = tgtBox.y + tgtBox.height / 2;

        await (page as any)._ensureCursorInit();
        await humanMove(raw, cursor.x, cursor.y, sx, sy, cfg);
        cursor.x = sx;
        cursor.y = sy;
        await sleep(rand(100, 200));
        await originals.mouseDown();
        await sleep(rand(80, 150));
        await humanMove(raw, cursor.x, cursor.y, tx, ty, cfg);
        cursor.x = tx;
        cursor.y = ty;
        await sleep(rand(80, 150));
        await originals.mouseUp();
      } else {
        return origElDrop(draggable, options);
      }
    };
  }

  // --- el.dragAndDrop() ---
  if (origElDragAndDrop) {
    (el as any).dragAndDrop = async (targetEl: ElementHandle, options?: any) => {
      const srcBox = await el.boundingBox();
      const tgtBox = await targetEl.boundingBox();

      if (srcBox && tgtBox) {
        const sx = srcBox.x + srcBox.width / 2;
        const sy = srcBox.y + srcBox.height / 2;
        const tx = tgtBox.x + tgtBox.width / 2;
        const ty = tgtBox.y + tgtBox.height / 2;

        await (page as any)._ensureCursorInit();
        await humanMove(raw, cursor.x, cursor.y, sx, sy, cfg);
        cursor.x = sx;
        cursor.y = sy;
        await sleep(rand(100, 200));
        await originals.mouseDown();
        await sleep(rand(80, 150));
        await humanMove(raw, cursor.x, cursor.y, tx, ty, cfg);
        cursor.x = tx;
        cursor.y = ty;
        await sleep(rand(80, 150));
        await originals.mouseUp();
      } else {
        return origElDragAndDrop(targetEl, options);
      }
    };
  }
}


// ============================================================================
// Frame-level patching — native Puppeteer Frame methods only
// Puppeteer Frame has: click, hover, type, select, focus, tap
// ============================================================================

function patchFrames(
  page: Page,
  cfg: HumanConfig,
  cursor: CursorState,
  raw: RawMouse,
  rawKb: RawKeyboard,
  originals: any,
  stealth: StealthEval,
): void {
  for (const frame of iterFrames(page)) {
    patchSingleFrame(frame, page, cfg, cursor, raw, rawKb, originals, stealth);
  }
}

function patchSingleFrame(
  frame: Frame,
  page: Page,
  cfg: HumanConfig,
  cursor: CursorState,
  raw: RawMouse,
  rawKb: RawKeyboard,
  originals: any,
  stealth: StealthEval,
): void {
  if ((frame as any)._humanPatched) return;
  (frame as any)._humanPatched = true;

  const origFrameSelect = frame.select.bind(frame);

  (frame as any).click = async (selector: string, options?: any) => {
    await (page as any).click(selector, options);
  };

  (frame as any).hover = async (selector: string, options?: any) => {
    await (page as any).hover(selector, options);
  };

  (frame as any).type = async (selector: string, text: string, options?: any) => {
    await (page as any).type(selector, text, options);
  };

  (frame as any).select = async (selector: string, ...values: string[]) => {
    await (page as any).hover(selector);
    await sleep(rand(100, 300));
    return origFrameSelect(selector, ...values);
  };

  (frame as any).focus = async (selector: string) => {
    await (page as any).focus(selector);
  };

  (frame as any).tap = async (selector: string, options?: any) => {
    await (page as any).click(selector, options);
  };

  // Patch frame.$() to return patched ElementHandles
  const origFrame$ = frame.$.bind(frame);
  const origFrame$$ = frame.$$.bind(frame);
  const origFrameWaitForSelector = frame.waitForSelector.bind(frame);

  (frame as any).$ = async (selector: string) => {
    const el = await origFrame$(selector);
    if (el) patchSingleElementHandle(el, page, cfg, cursor, raw, rawKb, originals, stealth);
    return el;
  };

  (frame as any).$$ = async (selector: string) => {
    const els = await origFrame$$(selector);
    for (const el of els) {
      patchSingleElementHandle(el, page, cfg, cursor, raw, rawKb, originals, stealth);
    }
    return els;
  };

  (frame as any).waitForSelector = async (selector: string, options?: any) => {
    const el = await origFrameWaitForSelector(selector, options);
    if (el) patchSingleElementHandle(el, page, cfg, cursor, raw, rawKb, originals, stealth);
    return el;
  };
}


function* iterFrames(page: Page): Generator<Frame> {
  try {
    const mainFrame = page.mainFrame();
    yield mainFrame;
    for (const child of mainFrame.childFrames()) {
      yield child;
    }
  } catch {}
}


// ============================================================================
// Browser-level patching
// ============================================================================

export function patchBrowser(browser: Browser, cfg: HumanConfig): void {
  browser.pages().then(pages => {
    for (const page of pages) {
      if (!(page as any)._original) {
        patchPage(page, cfg, new CursorState());
      }
    }
  }).catch(() => {});

  const origNewPage = browser.newPage.bind(browser);
  (browser as any).newPage = async () => {
    const page = await origNewPage();
    if (!(page as any)._original) {
      patchPage(page, cfg, new CursorState());
    }
    return page;
  };

  // v21: createIncognitoBrowserContext
  // v22+: createBrowserContext (renamed in puppeteer/puppeteer#11834)
  for (const methodName of ['createBrowserContext', 'createIncognitoBrowserContext'] as const) {
    if (typeof (browser as any)[methodName] === 'function') {
      const origCreateContext = (browser as any)[methodName].bind(browser);
      (browser as any)[methodName] = async (options?: any) => {
        const context: BrowserContext = await origCreateContext(options);

        const origCtxNewPage = context.newPage.bind(context);
        (context as any).newPage = async () => {
          const page = await origCtxNewPage();
          if (!(page as any)._original) {
            patchPage(page, cfg, new CursorState());
          }
          return page;
        };

        return context;
      };
    }
  }

  browser.on('targetcreated', async (target: any) => {
    try {
      if (target.type() === 'page') {
        const page = await target.page();
        if (page && !(page as any)._original) {
          patchPage(page, cfg, new CursorState());
        }
      }
    } catch {}
  });
}

export { patchPage };
