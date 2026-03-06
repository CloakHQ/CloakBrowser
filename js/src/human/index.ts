/**
 * Human-like behavioral layer for cloakbrowser (JS/TS).
 *
 * Activated via humanize: true in launch() / launchContext().
 * Patches page methods to use Bezier mouse curves, realistic typing, and smooth scrolling.
 *
 * Fixes applied:
 * - fill() now clears existing content before typing (Ctrl+A -> Backspace)
 * - ensureCursorInit() is now async and properly awaited
 * - Locator API (Frame-level) methods are patched to go through humanization
 */

import type { Browser, BrowserContext, Page, Frame } from 'playwright-core';
import { HumanConfig, resolveConfig, rand, randRange, sleep } from './config.js';
import { RawMouse, RawKeyboard, humanMove, humanClick, clickTarget, humanIdle } from './mouse.js';
import { humanType } from './keyboard.js';
import { scrollToElement } from './scroll.js';

export { HumanConfig, resolveConfig } from './config.js';
export { humanMove, humanClick, clickTarget, humanIdle } from './mouse.js';
export { humanType } from './keyboard.js';
export { scrollToElement } from './scroll.js';

const COALESCED_PATCH = `
(() => {
  if (window.__coalescedPatched) return;
  window.__coalescedPatched = true;
  const original = PointerEvent.prototype.getCoalescedEvents;
  PointerEvent.prototype.getCoalescedEvents = function() {
    const real = original.call(this);
    if (real.length <= 1) {
      const count = 1 + Math.floor(Math.random() * 3);
      const fake = [this];
      for (let i = 0; i < count; i++) {
        fake.push(new PointerEvent(this.type, {
          clientX: this.clientX + (Math.random() - 0.5) * 2,
          clientY: this.clientY + (Math.random() - 0.5) * 2,
          pointerId: this.pointerId,
          pointerType: this.pointerType,
          bubbles: false
        }));
      }
      return fake;
    }
    return real;
  };
})();
`;

async function injectCoalescedPatch(page: Page): Promise<void> {
  try { await page.evaluate(COALESCED_PATCH); } catch {}
}

class CursorState {
  x = 0;
  y = 0;
  initialized = false;
}

async function isInputElement(page: Page, selector: string): Promise<boolean> {
  return page.evaluate((sel: string) => {
    const el = document.querySelector(sel);
    if (!el) return false;
    const tag = el.tagName.toLowerCase();
    return tag === 'input' || tag === 'textarea'
      || el.getAttribute('contenteditable') === 'true';
  }, selector).catch(() => false);
}

function patchPage(page: Page, cfg: HumanConfig, cursor: CursorState): void {
  const originals = {
    click: page.click.bind(page),
    type: page.type.bind(page),
    fill: page.fill.bind(page),
    goto: page.goto.bind(page),
    mouseMove: page.mouse.move.bind(page.mouse),
    mouseClick: page.mouse.click.bind(page.mouse),
    mouseWheel: page.mouse.wheel.bind(page.mouse),
    mouseDown: page.mouse.down.bind(page.mouse),
    mouseUp: page.mouse.up.bind(page.mouse),
    keyboardType: page.keyboard.type.bind(page.keyboard),
    keyboardDown: page.keyboard.down.bind(page.keyboard),
    keyboardUp: page.keyboard.up.bind(page.keyboard),
    keyboardPress: page.keyboard.press.bind(page.keyboard),
    keyboardInsertText: page.keyboard.insertText.bind(page.keyboard),
  };

  (page as any)._original = originals;

  const raw: RawMouse = {
    move: originals.mouseMove,
    down: originals.mouseDown,
    up: originals.mouseUp,
    wheel: originals.mouseWheel,
  };

  const rawKb: RawKeyboard = {
    down: originals.keyboardDown,
    up: originals.keyboardUp,
    type: originals.keyboardType,
    insertText: originals.keyboardInsertText,
  };

  // Fix #5 (nice-to-have): ensureCursorInit is now async and properly awaited
  async function ensureCursorInit(): Promise<void> {
    if (!cursor.initialized) {
      cursor.x = rand(cfg.initial_cursor_x[0], cfg.initial_cursor_x[1]);
      cursor.y = rand(cfg.initial_cursor_y[0], cfg.initial_cursor_y[1]);
      await originals.mouseMove(cursor.x, cursor.y);
      cursor.initialized = true;
    }
  }

  const humanGoto = async (url: string, options?: any) => {
    const response = await originals.goto(url, options);
    if (cfg.patch_coalesced) await injectCoalescedPatch(page);
    // Re-patch any new frames after navigation
    patchFrames(page, cfg, cursor, raw, rawKb, originals);
    return response;
  };

  const humanClickFn = async (selector: string, options?: any) => {
    await ensureCursorInit();
    if (cfg.idle_between_actions) {
      await humanIdle(raw, rand(cfg.idle_between_duration[0], cfg.idle_between_duration[1]), cursor.x, cursor.y, cfg);
    }
    const { box, cursorX, cursorY } = await scrollToElement(page, raw, selector, cursor.x, cursor.y, cfg);
    cursor.x = cursorX;
    cursor.y = cursorY;
    const isInput = await isInputElement(page, selector);
    const target = clickTarget(box, isInput, cfg);
    await humanMove(raw, cursor.x, cursor.y, target.x, target.y, cfg);
    cursor.x = target.x;
    cursor.y = target.y;
    await humanClick(raw, isInput, cfg);
  };

  const humanTypeFn = async (selector: string, text: string, options?: any) => {
    await sleep(randRange(cfg.field_switch_delay));
    await humanClickFn(selector);
    await sleep(rand(100, 250));
    await humanType(page, rawKb, text, cfg);
  };

  // Fix #2: fill() now clears existing content before typing
  const humanFillFn = async (selector: string, value: string, options?: any) => {
    await sleep(randRange(cfg.field_switch_delay));
    await humanClickFn(selector);
    await sleep(rand(100, 250));
    // Clear existing content (preserve fill() contract: clear then set)
    await originals.keyboardPress('Control+a');
    await sleep(rand(30, 80));
    await originals.keyboardPress('Backspace');
    await sleep(rand(50, 150));
    await humanType(page, rawKb, value, cfg);
  };

  (page as any).goto = humanGoto;
  (page as any).click = humanClickFn;
  (page as any).type = humanTypeFn;
  (page as any).fill = humanFillFn;

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
    await humanClick(raw, false, cfg);
  };

  page.keyboard.type = async (text: string, options?: any) => {
    await humanType(page, rawKb, text, cfg);
  };

  // Fix #3: Patch Locator API (Frame-level methods)
  patchFrames(page, cfg, cursor, raw, rawKb, originals);
}

/**
 * Patch Frame.click/type/fill so Locator-based calls go through humanization.
 *
 * Playwright's Locator API (page.locator().click(), etc.) delegates to
 * Frame._click / Frame.fill directly, bypassing the patched page.click().
 * By patching Frame methods, we ensure humanization works with both
 * page.click() and page.locator().click().
 */
function patchFrames(
  page: Page,
  cfg: HumanConfig,
  cursor: CursorState,
  raw: RawMouse,
  rawKb: RawKeyboard,
  originals: any,
): void {
  for (const frame of iterFrames(page)) {
    patchSingleFrame(frame, page);
  }
}

function patchSingleFrame(frame: Frame, page: Page): void {
  if ((frame as any)._humanPatched) return;
  (frame as any)._humanPatched = true;

  const origFrameClick = frame.click.bind(frame);
  const origFrameType = frame.type.bind(frame);
  const origFrameFill = frame.fill.bind(frame);

  (frame as any).click = async (selector: string, options?: any) => {
    await (page as any).click(selector, options);
  };

  (frame as any).type = async (selector: string, text: string, options?: any) => {
    await (page as any).type(selector, text, options);
  };

  (frame as any).fill = async (selector: string, value: string, options?: any) => {
    await (page as any).fill(selector, value, options);
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

function patchContext(context: BrowserContext, cfg: HumanConfig): void {
  const cursor = new CursorState();
  for (const page of context.pages()) {
    patchPage(page, cfg, cursor);
  }
  context.on('page', (page: Page) => patchPage(page, cfg, cursor));
}

export function patchBrowser(browser: Browser, cfg: HumanConfig): void {
  for (const context of browser.contexts()) {
    patchContext(context, cfg);
  }

  const origNewContext = browser.newContext.bind(browser);
  (browser as any).newContext = async (options?: any) => {
    const context = await origNewContext(options);
    patchContext(context, cfg);
    return context;
  };

  (browser as any).newPage = async (options?: any) => {
    const context = await (browser as any).newContext(options);
    const page = await context.newPage();
    return page;
  };
}

export { patchContext, patchPage };
