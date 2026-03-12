/**
 * Human-like behavioral layer for cloakbrowser (JS/TS).
 *
 * Activated via humanize: true in launch() / launchContext().
 * Patches page methods to use Bezier mouse curves, realistic typing, and smooth scrolling.
 *
 * Patches all interaction methods:
 * click, dblclick, hover, type, fill, check, uncheck, selectOption,
 * press, pressSequentially, tap, dragTo, clear + Frame-level equivalents.
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

// --- Platform-aware select-all shortcut (macOS uses Meta, others use Control) ---
const SELECT_ALL = process.platform === 'darwin' ? 'Meta+a' : 'Control+a';

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

async function isSelectorFocused(page: Page, selector: string): Promise<boolean> {
  return page.evaluate((sel: string) => {
    const el = document.querySelector(sel);
    return el === document.activeElement;
  }, selector).catch(() => false);
}

// ============================================================================
// Page-level patching
// ============================================================================

/**
 * Replace page methods with human-like implementations.
 */
function patchPage(page: Page, cfg: HumanConfig, cursor: CursorState): void {
  const originals = {
    click: page.click.bind(page),
    dblclick: page.dblclick.bind(page),
    hover: page.hover.bind(page),
    type: page.type.bind(page),
    fill: page.fill.bind(page),
    check: page.check.bind(page),
    uncheck: page.uncheck.bind(page),
    selectOption: page.selectOption.bind(page),
    press: page.press.bind(page),
    goto: page.goto.bind(page),
    isChecked: page.isChecked.bind(page),
    mouseMove: page.mouse.move.bind(page.mouse),
    mouseClick: page.mouse.click.bind(page.mouse),
    mouseDblclick: page.mouse.dblclick.bind(page.mouse),
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
  (page as any)._humanCfg = cfg;

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

  async function ensureCursorInit(): Promise<void> {
    if (!cursor.initialized) {
      cursor.x = rand(cfg.initial_cursor_x[0], cfg.initial_cursor_x[1]);
      cursor.y = rand(cfg.initial_cursor_y[0], cfg.initial_cursor_y[1]);
      await originals.mouseMove(cursor.x, cursor.y);
      cursor.initialized = true;
    }
  }

  // --- goto ---
  const humanGoto = async (url: string, options?: any) => {
    const response = await originals.goto(url, options);
    // Patch any new frames after navigation
    patchFrames(page, cfg, cursor, raw, rawKb, originals);
    return response;
  };

  // --- click ---
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

  // --- dblclick ---
  const humanDblclickFn = async (selector: string, options?: any) => {
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
    await raw.down({ clickCount: 2 });
    await sleep(rand(30, 60));
    await raw.up({ clickCount: 2 });
  };

  // --- hover ---
  const humanHoverFn = async (selector: string, options?: any) => {
    await ensureCursorInit();
    if (cfg.idle_between_actions) {
      await humanIdle(raw, rand(cfg.idle_between_duration[0], cfg.idle_between_duration[1]), cursor.x, cursor.y, cfg);
    }
    const { box, cursorX, cursorY } = await scrollToElement(page, raw, selector, cursor.x, cursor.y, cfg);
    cursor.x = cursorX;
    cursor.y = cursorY;
    const target = clickTarget(box, false, cfg);
    await humanMove(raw, cursor.x, cursor.y, target.x, target.y, cfg);
    cursor.x = target.x;
    cursor.y = target.y;
  };

  // --- type ---
  const humanTypeFn = async (selector: string, text: string, options?: any) => {
    await sleep(randRange(cfg.field_switch_delay));
    await humanClickFn(selector);
    await sleep(rand(100, 250));
    await humanType(page, rawKb, text, cfg);
  };

  // --- fill (clears existing content first) ---
  const humanFillFn = async (selector: string, value: string, options?: any) => {
    await sleep(randRange(cfg.field_switch_delay));
    await humanClickFn(selector);
    await sleep(rand(100, 250));
    await originals.keyboardPress(SELECT_ALL);
    await sleep(rand(30, 80));
    await originals.keyboardPress('Backspace');
    await sleep(rand(50, 150));
    await humanType(page, rawKb, value, cfg);
  };

  // --- clear ---
  const humanClearFn = async (selector: string, options?: any) => {
    if (!await isSelectorFocused(page, selector)) {
      await humanClickFn(selector);
    }
    await sleep(rand(50, 150));
    await originals.keyboardPress(SELECT_ALL);
    await sleep(rand(30, 80));
    await originals.keyboardPress('Backspace');
  };

  // --- check ---
  const humanCheckFn = async (selector: string, options?: any) => {
    if (cfg.idle_between_actions) {
      await humanIdle(raw, rand(cfg.idle_between_duration[0], cfg.idle_between_duration[1]), cursor.x, cursor.y, cfg);
    }
    const checked = await originals.isChecked(selector).catch(() => false);
    if (!checked) {
      await humanClickFn(selector);
    }
  };

  // --- uncheck ---
  const humanUncheckFn = async (selector: string, options?: any) => {
    if (cfg.idle_between_actions) {
      await humanIdle(raw, rand(cfg.idle_between_duration[0], cfg.idle_between_duration[1]), cursor.x, cursor.y, cfg);
    }
    const checked = await originals.isChecked(selector).catch(() => true);
    if (checked) {
      await humanClickFn(selector);
    }
  };

  // --- selectOption ---
  const humanSelectOptionFn = async (selector: string, values: any, options?: any) => {
    await humanHoverFn(selector);
    await sleep(rand(100, 300));
    return originals.selectOption(selector, values, options);
  };

  // --- press (checks focus first — avoids redundant mouse moves) ---
  const humanPressFn = async (selector: string, key: string, options?: any) => {
    if (!await isSelectorFocused(page, selector)) {
      await humanClickFn(selector);
    }
    await sleep(rand(50, 150));
    await originals.keyboardPress(key);
  };

  // --- pressSequentially ---
  const humanPressSequentiallyFn = async (selector: string, text: string, options?: any) => {
    if (!await isSelectorFocused(page, selector)) {
      await humanClickFn(selector);
    }
    await sleep(rand(100, 250));
    await humanType(page, rawKb, text, cfg);
  };

  // --- tap ---
  const humanTapFn = async (selector: string, options?: any) => {
    await humanClickFn(selector, options);
  };

  // Assign page-level patches
  (page as any).goto = humanGoto;
  (page as any).click = humanClickFn;
  (page as any).dblclick = humanDblclickFn;
  (page as any).hover = humanHoverFn;
  (page as any).type = humanTypeFn;
  (page as any).fill = humanFillFn;
  (page as any).check = humanCheckFn;
  (page as any).uncheck = humanUncheckFn;
  (page as any).selectOption = humanSelectOptionFn;
  (page as any).press = humanPressFn;

  // --- mouse patches ---
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

  // --- keyboard patches ---
  page.keyboard.type = async (text: string, options?: any) => {
    await humanType(page, rawKb, text, cfg);
  };

  // Store helpers for frame patching
  (page as any)._humanCursor = cursor;
  (page as any)._humanRaw = raw;
  (page as any)._humanRawKb = rawKb;
  (page as any)._humanOriginals = originals;
  (page as any)._humanClickFn = humanClickFn;
  (page as any)._humanHoverFn = humanHoverFn;
  (page as any)._humanClearFn = humanClearFn;
  (page as any)._humanPressFn = humanPressFn;
  (page as any)._humanPressSequentiallyFn = humanPressSequentiallyFn;
  (page as any)._humanTapFn = humanTapFn;
  (page as any)._ensureCursorInit = ensureCursorInit;

  // Initialize cursor immediately so it doesn't visibly jump from (0,0)
  cursor.x = rand(cfg.initial_cursor_x[0], cfg.initial_cursor_x[1]);
  cursor.y = rand(cfg.initial_cursor_y[0], cfg.initial_cursor_y[1]);
  originals.mouseMove(cursor.x, cursor.y).then(() => {
    cursor.initialized = true;
  }).catch(() => {});

  // --- Patch Frame-level methods (for sub-frames) ---
  patchFrames(page, cfg, cursor, raw, rawKb, originals);
}


// ============================================================================
// Frame-level patching
// ============================================================================

/**
 * Patch Frame methods so Locator-based calls go through humanization.
 * All 11 methods patched: click, dblclick, hover, type, fill, check, uncheck,
 * selectOption, press, clear, dragAndDrop.
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
    patchSingleFrame(frame, page, cfg, originals);
  }
}

function patchSingleFrame(frame: Frame, page: Page, cfg: HumanConfig, originals: any): void {
  if ((frame as any)._humanPatched) return;
  (frame as any)._humanPatched = true;

  // Save originals for methods that need fallback
  const origFrameSelectOption = frame.selectOption.bind(frame);
  const origFrameDragAndDrop = frame.dragAndDrop.bind(frame);

  (frame as any).click = async (selector: string, options?: any) => {
    await (page as any).click(selector, options);
  };

  (frame as any).dblclick = async (selector: string, options?: any) => {
    await (page as any).dblclick(selector, options);
  };

  (frame as any).hover = async (selector: string, options?: any) => {
    await (page as any).hover(selector, options);
  };

  (frame as any).type = async (selector: string, text: string, options?: any) => {
    await (page as any).type(selector, text, options);
  };

  (frame as any).fill = async (selector: string, value: string, options?: any) => {
    await (page as any).fill(selector, value, options);
  };

  (frame as any).check = async (selector: string, options?: any) => {
    await (page as any).check(selector, options);
  };

  (frame as any).uncheck = async (selector: string, options?: any) => {
    await (page as any).uncheck(selector, options);
  };

  (frame as any).selectOption = async (selector: string, values: any, options?: any) => {
    await (page as any).hover(selector);
    await sleep(rand(100, 300));
    return origFrameSelectOption(selector, values, options);
  };

  (frame as any).press = async (selector: string, key: string, options?: any) => {
    await (page as any).press(selector, key, options);
  };

  (frame as any).clear = async (selector: string, options?: any) => {
    if (!await isSelectorFocused(page, selector)) {
      await (page as any).click(selector);
    }
    await sleep(rand(50, 150));
    await originals.keyboardPress(SELECT_ALL);
    await sleep(rand(30, 80));
    await originals.keyboardPress('Backspace');
  };

  (frame as any).dragAndDrop = async (source: string, target: string, options?: any) => {
    const srcBox = await frame.locator(source).boundingBox().catch(() => null);
    const tgtBox = await frame.locator(target).boundingBox().catch(() => null);

    if (srcBox && tgtBox) {
      const sx = srcBox.x + srcBox.width / 2;
      const sy = srcBox.y + srcBox.height / 2;
      const tx = tgtBox.x + tgtBox.width / 2;
      const ty = tgtBox.y + tgtBox.height / 2;

      await page.mouse.move(sx, sy);
      await sleep(rand(100, 200));
      await originals.mouseDown();
      await sleep(rand(80, 150));
      await page.mouse.move(tx, ty);
      await sleep(rand(80, 150));
      await originals.mouseUp();
    } else {
      return origFrameDragAndDrop(source, target, options);
    }
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
// Context-level patching
// ============================================================================

function patchContext(context: BrowserContext, cfg: HumanConfig): void {
  const cursor = new CursorState();
  for (const page of context.pages()) {
    patchPage(page, cfg, cursor);
  }
  context.on('page', (page: Page) => {
    if (!(page as any)._original) {
      patchPage(page, cfg, new CursorState());
    }
  });

  const origNewPage = context.newPage.bind(context);
  (context as any).newPage = async () => {
    const page = await origNewPage();
    if (!(page as any)._original) {
      patchPage(page, cfg, new CursorState());
    }
    return page;
  };
}


// ============================================================================
// Browser-level patching
// ============================================================================

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

  const origNewPage = browser.newPage.bind(browser);
  (browser as any).newPage = async (options?: any) => {
    const page = await origNewPage(options);
    if (!(page as any)._original) {
      const ctx = page.context();
      if (!(ctx as any)._humanPatched) {
        patchContext(ctx, cfg);
        (ctx as any)._humanPatched = true;
      }
      patchPage(page, cfg, new CursorState());
    }
    return page;
  };
}

export { patchContext, patchPage };
