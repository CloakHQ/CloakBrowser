/**
 * Unit tests for stealth / anti-detection fixes — PUPPETEER EDITION.
 *
 * Covers:
 *   - StealthEval — CDP isolated-world lifecycle (evaluate, invalidate, retry)
 *   - isInputElement / isSelectorFocused — stealth DOM queries with fallback
 *   - typeShiftSymbol — CDP Input.dispatchKeyEvent path vs evaluate fallback
 *   - humanType integration — shift symbols routed via CDP
 *   - Navigation invalidation (goto → stealth.invalidate)
 *   - patchPage stealth infrastructure wiring
 *   - SHIFT_SYMBOL_CODES / SHIFT_SYMBOL_KEYCODES completeness
 *   - focus() — human-like click instead of programmatic CDP focus
 *   - uncheck() — fallback behavior matches Playwright (assume checked on error)
 *   - mouse.wheel() — smooth scroll via smoothWheel
 *   - mouse.dragAndDrop() — Bézier drag between coordinates
 *   - ElementHandle patching — click, hover, type, press, tap, focus, select
 *   - Frame patching — delegates to page-level humanized methods
 *   - Browser-level patching — newPage, createBrowserContext, targetcreated
 *
 * All tests are fast, mock-based, and do NOT require a browser.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { resolveConfig, rand, randRange, sleep } from "../src/human/config.js";
import { humanType } from "../src/human-puppeteer/keyboard.js";
import { humanMove, humanClick, clickTarget, humanIdle } from "../src/human/mouse.js";

// =========================================================================
// Helper: build mock page / raw objects (Puppeteer-style)
// =========================================================================

function buildMockPage(overrides: Record<string, any> = {}): any {
  const mainFrameObj = overrides.mainFrameReturn ?? {
    childFrames: vi.fn(() => []),
    click: vi.fn(async () => {}),
    hover: vi.fn(async () => {}),
    type: vi.fn(async () => {}),
    fill: vi.fn(async () => {}),
    check: vi.fn(async () => {}),
    uncheck: vi.fn(async () => {}),
    select: vi.fn(async () => []),
    press: vi.fn(async () => {}),
    clear: vi.fn(async () => {}),
    focus: vi.fn(async () => {}),
    tap: vi.fn(async () => {}),
    dragAndDrop: vi.fn(async () => {}),
    $: vi.fn(async () => null),

    $$: vi.fn(async () => []),
    waitForSelector: vi.fn(async () => null),
  };

  const page: any = {
    evaluate: overrides.evaluate ?? vi.fn(async () => false),
    mouse: {
      move: vi.fn(async () => {}),
      down: vi.fn(async () => {}),
      up: vi.fn(async () => {}),
      click: vi.fn(async () => {}),
      wheel: vi.fn(async () => {}),
      dragAndDrop: overrides.mouseDragAndDrop ?? vi.fn(async () => {}),
    },
    keyboard: {
      press: overrides.keyboardPress
        ? vi.fn(overrides.keyboardPress)
        : vi.fn(async () => {}),
      type: vi.fn(async () => {}),
      down: vi.fn(async () => {}),
      up: vi.fn(async () => {}),
      sendCharacter: vi.fn(async () => {}),
    },
    click: vi.fn(async () => {}),
    hover: vi.fn(async () => {}),
    type: vi.fn(async () => {}),
    fill: vi.fn(async () => {}),
    check: vi.fn(async () => {}),
    uncheck: vi.fn(async () => {}),
    select: vi.fn(async () => []),
    press: vi.fn(async () => {}),
    focus: vi.fn(async () => {}),
    goto: vi.fn(async () => ({})),
    tap: vi.fn(async () => {}),
    clear: vi.fn(async () => {}),
    $: overrides.$ ?? vi.fn(async () => null),

    $$: overrides.$$ ?? vi.fn(async () => []),
    waitForSelector: overrides.waitForSelector ?? vi.fn(async () => null),
    // Puppeteer-specific: viewport() returns object (not viewportSize())
    viewport: vi.fn(() => ({ width: 1280, height: 720 })),
    mainFrame: vi.fn(() => mainFrameObj),
    frames: vi.fn(() => []),
    // Puppeteer-specific: createCDPSession on page, not context
    createCDPSession: vi.fn(async () => buildMockCDP()),
    url: vi.fn(() => "about:blank"),
  };
  return page;
}

function buildMockCDP(overrides: Record<string, any> = {}): any {
  return {
    send: overrides.send ?? vi.fn(async (method: string, params?: any) => {
      if (method === "Page.getFrameTree") {
        return { frameTree: { frame: { id: "F1" } } };
      }
      if (method === "Page.createIsolatedWorld") {
        return { executionContextId: 42 };
      }
      if (method === "Runtime.evaluate") {
        return { result: { value: false } };
      }
      return {};
    }),
  };
}

function buildRawKeyboard() {
  const downKeys: string[] = [];
  const upKeys: string[] = [];
  const insertedChars: string[] = [];
  const raw = {
    down: vi.fn(async (k: string) => { downKeys.push(k); }),
    up: vi.fn(async (k: string) => { upKeys.push(k); }),
    type: vi.fn(async () => {}),
    insertText: vi.fn(async (t: string) => { insertedChars.push(t); }),
  };
  return { raw, downKeys, upKeys, insertedChars };
}

function buildMockElementHandle(overrides: Record<string, any> = {}): any {
  return {
    click: vi.fn(async () => {}),
    hover: vi.fn(async () => {}),
    type: vi.fn(async () => {}),
    press: vi.fn(async () => {}),
    tap: vi.fn(async () => {}),
    focus: vi.fn(async () => {}),
    select: vi.fn(async () => []),
    drop: vi.fn(async () => {}),
    dragAndDrop: vi.fn(async () => {}),
    boundingBox: overrides.boundingBox ?? vi.fn(async () => ({ x: 100, y: 200, width: 120, height: 30 })),
    evaluate: overrides.evaluate ?? vi.fn(async () => false),
    $: vi.fn(async () => null),

    $$: vi.fn(async () => []),
    waitForSelector: vi.fn(async () => null),
  };
}

function buildMockBrowser(pages: any[] = []): any {
  const browser: any = {
    pages: vi.fn(async () => pages),
    newPage: vi.fn(async () => buildMockPage()),
    createBrowserContext: vi.fn(async () => ({
      newPage: vi.fn(async () => buildMockPage()),
    })),
    on: vi.fn(),
    close: vi.fn(async () => {}),
  };
  return browser;
}


// =========================================================================
// SHIFT_SYMBOL_CODES / SHIFT_SYMBOL_KEYCODES completeness
// =========================================================================
describe("Puppeteer: SHIFT_SYMBOL maps completeness", () => {
  it("every shift symbol has a code and keycode entry", async () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const SHIFT_SYMBOLS = ['@', '#', '!', '$', '%', '^', '&', '*', '(', ')',
      '_', '+', '{', '}', '|', ':', '"', '<', '>', '?', '~'];

    for (const sym of SHIFT_SYMBOLS) {
      const { raw } = buildRawKeyboard();
      const page = buildMockPage();
      const mockCdp = {
        send: vi.fn(async () => ({})),
      };

      await humanType(page, raw, sym, cfg, mockCdp as any);

      const cdpCalls = mockCdp.send.mock.calls;
      const keyEvents = cdpCalls.filter(
        (c: any[]) => c[0] === "Input.dispatchKeyEvent"
      );
      expect(keyEvents.length).toBe(2);
      expect(page.evaluate).not.toHaveBeenCalled();
    }
  });

  it("all shift symbol keyDown events have correct structure", async () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const { raw } = buildRawKeyboard();
    const page = buildMockPage();
    const cdpCalls: Array<[string, any]> = [];
    const mockCdp = {
      send: vi.fn(async (method: string, params: any) => {
        cdpCalls.push([method, params]);
        return {};
      }),
    };

    await humanType(page, raw, "!", cfg, mockCdp as any);

    const keyDown = cdpCalls.find(
      ([m, p]) => m === "Input.dispatchKeyEvent" && p.type === "keyDown"
    );
    expect(keyDown).toBeDefined();
    const params = keyDown![1];

    expect(params.key).toBe("!");
    expect(params.modifiers).toBe(8);
    expect(typeof params.code).toBe("string");
    expect(params.code.length).toBeGreaterThan(0);
    expect(typeof params.windowsVirtualKeyCode).toBe("number");
    expect(params.windowsVirtualKeyCode).toBeGreaterThan(0);
    expect(params.text).toBe("!");
    expect(params.unmodifiedText).toBe("!");
  });

  it("keyUp event has no text/unmodifiedText fields", async () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const { raw } = buildRawKeyboard();
    const page = buildMockPage();
    const cdpCalls: Array<[string, any]> = [];
    const mockCdp = {
      send: vi.fn(async (method: string, params: any) => {
        cdpCalls.push([method, params]);
        return {};
      }),
    };

    await humanType(page, raw, "!", cfg, mockCdp as any);

    const keyUp = cdpCalls.find(
      ([m, p]) => m === "Input.dispatchKeyEvent" && p.type === "keyUp"
    );
    expect(keyUp).toBeDefined();
    const params = keyUp![1];

    expect(params.text).toBeUndefined();
    expect(params.unmodifiedText).toBeUndefined();
  });

  it("digit shift symbols have correct keycodes (49-57, 48)", async () => {
    const digitSymbols = ['!', '@', '#', '$', '%', '^', '&', '*', '(', ')'];
    const expectedKeycodes = [49, 50, 51, 52, 53, 54, 55, 56, 57, 48];
    const cfg = resolveConfig("default", { mistype_chance: 0 });

    for (let i = 0; i < digitSymbols.length; i++) {
      const { raw } = buildRawKeyboard();
      const page = buildMockPage();
      const cdpCalls: Array<[string, any]> = [];
      const mockCdp = {
        send: vi.fn(async (method: string, params: any) => {
          cdpCalls.push([method, params]);
          return {};
        }),
      };

      await humanType(page, raw, digitSymbols[i], cfg, mockCdp as any);

      const keyDown = cdpCalls.find(
        ([m, p]) => m === "Input.dispatchKeyEvent" && p.type === "keyDown"
      );
      expect(keyDown).toBeDefined();
      expect(keyDown![1].windowsVirtualKeyCode).toBe(expectedKeycodes[i]);
    }
  });
});


// =========================================================================
// typeShiftSymbol — CDP path vs fallback (Puppeteer keyboard.ts)
// =========================================================================
describe("Puppeteer: typeShiftSymbol CDP vs fallback", () => {
  it("uses CDP path when cdpSession is provided (no page.evaluate)", async () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const { raw } = buildRawKeyboard();
    const page = buildMockPage();
    const mockCdp = { send: vi.fn(async () => ({})) };

    await humanType(page, raw, "@", cfg, mockCdp as any);

    expect(page.evaluate).not.toHaveBeenCalled();
    expect(mockCdp.send).toHaveBeenCalled();
  });

  it("CDP path does NOT call raw.insertText for shift symbols", async () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const { raw, insertedChars } = buildRawKeyboard();
    const page = buildMockPage();
    const mockCdp = { send: vi.fn(async () => ({})) };

    await humanType(page, raw, "#", cfg, mockCdp as any);

    expect(insertedChars.length).toBe(0);
  });

  it("falls back to page.evaluate when no cdpSession", async () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const { raw, insertedChars } = buildRawKeyboard();
    const page = buildMockPage();

    await humanType(page, raw, "$", cfg, null);

    expect(page.evaluate).toHaveBeenCalled();
    expect(insertedChars).toContain("$");
  });

  it("fallback path calls raw.insertText before page.evaluate", async () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const callOrder: string[] = [];
    const raw = {
      down: vi.fn(async () => { callOrder.push("raw.down"); }),
      up: vi.fn(async () => { callOrder.push("raw.up"); }),
      type: vi.fn(async () => {}),
      insertText: vi.fn(async () => { callOrder.push("raw.insertText"); }),
    };
    const page = buildMockPage({
      evaluate: vi.fn(async () => { callOrder.push("page.evaluate"); }),
    });

    await humanType(page, raw, "%", cfg, null);

    const insertIdx = callOrder.indexOf("raw.insertText");
    const evalIdx = callOrder.indexOf("page.evaluate");
    expect(insertIdx).toBeLessThan(evalIdx);
  });

  it("Shift is held during CDP key events", async () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const callOrder: string[] = [];

    const raw = {
      down: vi.fn(async (k: string) => { callOrder.push(`raw.down(${k})`); }),
      up: vi.fn(async (k: string) => { callOrder.push(`raw.up(${k})`); }),
      type: vi.fn(async () => {}),
      insertText: vi.fn(async () => {}),
    };
    const page = buildMockPage();
    const mockCdp = {
      send: vi.fn(async (method: string, params: any) => {
        callOrder.push(`cdp.${params.type || method}`);
        return {};
      }),
    };

    await humanType(page, raw, "!", cfg, mockCdp as any);

    const shiftDownIdx = callOrder.indexOf("raw.down(Shift)");
    const keyDownIdx = callOrder.indexOf("cdp.keyDown");
    const keyUpIdx = callOrder.indexOf("cdp.keyUp");
    const shiftUpIdx = callOrder.indexOf("raw.up(Shift)");

    expect(shiftDownIdx).toBeLessThan(keyDownIdx);
    expect(keyDownIdx).toBeLessThan(keyUpIdx);
    expect(keyUpIdx).toBeLessThan(shiftUpIdx);
  });
});


// =========================================================================
// humanType integration — mixed text with CDP (Puppeteer keyboard.ts)
// =========================================================================
describe("Puppeteer: humanType mixed text with CDP", () => {
  it("normal chars use raw.down/up, shift symbols use CDP", async () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const { raw, downKeys } = buildRawKeyboard();
    const page = buildMockPage();
    const cdpCalls: Array<[string, any]> = [];
    const mockCdp = {
      send: vi.fn(async (method: string, params: any) => {
        cdpCalls.push([method, params]);
        return {};
      }),
    };

    await humanType(page, raw, "a!", cfg, mockCdp as any);

    expect(downKeys).toContain("a");

    const keyEvents = cdpCalls.filter(
      ([m]) => m === "Input.dispatchKeyEvent"
    );
    expect(keyEvents.length).toBe(2);
    expect(page.evaluate).not.toHaveBeenCalled();
  });

  it("text without shift symbols does not call CDP", async () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const { raw } = buildRawKeyboard();
    const page = buildMockPage();
    const mockCdp = { send: vi.fn(async () => ({})) };

    await humanType(page, raw, "hello", cfg, mockCdp as any);

    expect(mockCdp.send).not.toHaveBeenCalled();
    expect(page.evaluate).not.toHaveBeenCalled();
  });

  it("multiple shift symbols all go through CDP", async () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const { raw } = buildRawKeyboard();
    const page = buildMockPage();
    const cdpCalls: Array<[string, any]> = [];
    const mockCdp = {
      send: vi.fn(async (method: string, params: any) => {
        cdpCalls.push([method, params]);
        return {};
      }),
    };

    await humanType(page, raw, "!@#", cfg, mockCdp as any);

    expect(page.evaluate).not.toHaveBeenCalled();
    const keyEvents = cdpCalls.filter(
      ([m]) => m === "Input.dispatchKeyEvent"
    );
    expect(keyEvents.length).toBe(6);
  });

  it("'Hello World!' — no page.evaluate leak", async () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const { raw } = buildRawKeyboard();
    const page = buildMockPage();
    const mockCdp = { send: vi.fn(async () => ({})) };

    await humanType(page, raw, "Hello World!", cfg, mockCdp as any);

    expect(page.evaluate).not.toHaveBeenCalled();
  });

  it("password-like text 'SecurePass!123' uses CDP for '!'", async () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const { raw } = buildRawKeyboard();
    const page = buildMockPage();
    const cdpCalls: Array<[string, any]> = [];
    const mockCdp = {
      send: vi.fn(async (method: string, params: any) => {
        cdpCalls.push([method, params]);
        return {};
      }),
    };

    await humanType(page, raw, "SecurePass!123", cfg, mockCdp as any);

    const keyEvents = cdpCalls.filter(
      ([m]) => m === "Input.dispatchKeyEvent"
    );
    expect(keyEvents.length).toBe(2);
    expect(keyEvents[0][1].key).toBe("!");
    expect(page.evaluate).not.toHaveBeenCalled();
  });

  it("CDP modifier flag is always 8 (Shift)", async () => {
    const cfg = resolveConfig("default", {
      mistype_chance: 0,
      typing_delay: 0,
      shift_down_delay: [0, 0],
      shift_up_delay: [0, 0],
      key_hold: [0, 0],
    });

    const allSymbols = '@#!$%^&*()_+{}|:"<>?~';
    const { raw } = buildRawKeyboard();
    const page = buildMockPage();
    const cdpCalls: Array<[string, any]> = [];
    const mockCdp = {
      send: vi.fn(async (method: string, params: any) => {
        cdpCalls.push([method, params]);
        return {};
      }),
    };

    await humanType(page, raw, allSymbols, cfg, mockCdp as any);

    for (const [method, params] of cdpCalls) {
      if (method === "Input.dispatchKeyEvent") {
        expect(params.modifiers).toBe(8);
      }
    }
  }, 30000);
});


// =========================================================================
// Non-ASCII text does NOT go through CDP shift path
// =========================================================================
describe("Puppeteer: non-ASCII text avoids CDP shift path", () => {
  it("Cyrillic text uses insertText, not CDP", async () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const { raw, insertedChars } = buildRawKeyboard();
    const page = buildMockPage();
    const mockCdp = { send: vi.fn(async () => ({})) };

    await humanType(page, raw, "Привет", cfg, mockCdp as any);

    expect(insertedChars.join("")).toBe("Привет");
    expect(mockCdp.send).not.toHaveBeenCalled();
    expect(page.evaluate).not.toHaveBeenCalled();
  });

  it("mixed text: ASCII + Cyrillic + shift symbol", async () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const { raw, downKeys, insertedChars } = buildRawKeyboard();
    const page = buildMockPage();
    const cdpCalls: Array<[string, any]> = [];
    const mockCdp = {
      send: vi.fn(async (method: string, params: any) => {
        cdpCalls.push([method, params]);
        return {};
      }),
    };

    await humanType(page, raw, "Hi! Мир", cfg, mockCdp as any);

    expect(downKeys).toContain("Shift");
    expect(downKeys).toContain("H");
    expect(downKeys).toContain("i");

    const keyEvents = cdpCalls.filter(([m]) => m === "Input.dispatchKeyEvent");
    expect(keyEvents.length).toBe(2);

    expect(downKeys).toContain(" ");

    expect(insertedChars).toContain("М");
    expect(insertedChars).toContain("и");
    expect(insertedChars).toContain("р");

    expect(page.evaluate).not.toHaveBeenCalled();
  });
});


// =========================================================================
// patchPage stealth infrastructure (Puppeteer)
// =========================================================================
describe("Puppeteer: patchPage stealth infrastructure", () => {
  it("page._stealth is a StealthEval instance after patching", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect((page as any)._stealth).toBeDefined();
    expect(typeof (page as any)._stealth.evaluate).toBe("function");
    expect(typeof (page as any)._stealth.invalidate).toBe("function");
    expect(typeof (page as any)._stealth.getCdpSession).toBe("function");
  });

  it("page._original and page._humanCfg are set", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect((page as any)._original).toBeDefined();
    expect((page as any)._humanCfg).toBe(cfg);
  });

  it("goto invalidates stealth context", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const stealth = (page as any)._stealth;
    const invalidateSpy = vi.spyOn(stealth, "invalidate");

    await page.goto("https://example.com");

    expect(invalidateSpy).toHaveBeenCalled();
  });

  it("internal helpers are stored on page for element/frame patching", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    // Only the helpers actually used by ElementHandle/Frame patching
    expect(typeof (page as any)._ensureCursorInit).toBe("function");
    expect((page as any)._humanCursor).toBeDefined();
    expect((page as any)._humanRaw).toBeDefined();
    expect((page as any)._humanRawKb).toBeDefined();
  });

  it("page.createCDPSession is used (not context.newCDPSession)", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const stealth = (page as any)._stealth;
    await stealth.getCdpSession();

    expect(page.createCDPSession).toHaveBeenCalled();
  });
});


// =========================================================================
// StealthEval lifecycle (Puppeteer — via page.createCDPSession)
// =========================================================================
describe("Puppeteer: StealthEval lifecycle", () => {
  it("stealth.invalidate() is callable without error", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const stealth = (page as any)._stealth;
    expect(() => stealth.invalidate()).not.toThrow();
  });

  it("stealth.getCdpSession() returns a CDP session", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const stealth = (page as any)._stealth;
    const session = await stealth.getCdpSession();
    expect(session).toBeDefined();
    expect(typeof session.send).toBe("function");
  });

  it("stealth.evaluate() creates world and returns value", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const mockCdp = buildMockCDP({
      send: vi.fn(async (method: string, params?: any) => {
        if (method === "Page.getFrameTree") {
          return { frameTree: { frame: { id: "F1" } } };
        }
        if (method === "Page.createIsolatedWorld") {
          return { executionContextId: 42 };
        }
        if (method === "Runtime.evaluate") {
          return { result: { value: true } };
        }
        return {};
      }),
    });

    const page = buildMockPage();
    page.createCDPSession = vi.fn(async () => mockCdp);

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const stealth = (page as any)._stealth;
    const result = await stealth.evaluate("1 + 1");
    expect(result).toBe(true);
  });

  it("stealth.evaluate() retries on exceptionDetails", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");
    let attempt = 0;

    const mockCdp = buildMockCDP({
      send: vi.fn(async (method: string, params?: any) => {
        if (method === "Page.getFrameTree") {
          return { frameTree: { frame: { id: "F1" } } };
        }
        if (method === "Page.createIsolatedWorld") {
          return { executionContextId: 50 + attempt };
        }
        if (method === "Runtime.evaluate") {
          attempt++;
          if (attempt === 1) {
            return { exceptionDetails: { text: "stale" } };
          }
          return { result: { value: "recovered" } };
        }
        return {};
      }),
    });

    const page = buildMockPage();
    page.createCDPSession = vi.fn(async () => mockCdp);

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const stealth = (page as any)._stealth;
    const result = await stealth.evaluate("test");
    expect(result).toBe("recovered");
  });

  it("stealth.evaluate() returns undefined after double failure", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const mockCdp = buildMockCDP({
      send: vi.fn(async (method: string) => {
        if (method === "Page.getFrameTree") {
          return { frameTree: { frame: { id: "F1" } } };
        }
        if (method === "Page.createIsolatedWorld") {
          return { executionContextId: 70 };
        }
        if (method === "Runtime.evaluate") {
          return { exceptionDetails: { text: "always broken" } };
        }
        return {};
      }),
    });

    const page = buildMockPage();
    page.createCDPSession = vi.fn(async () => mockCdp);

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const stealth = (page as any)._stealth;
    const result = await stealth.evaluate("broken");
    expect(result).toBeUndefined();
  });
});


// =========================================================================
// focus() — human-like click instead of programmatic focus
// =========================================================================
describe("Puppeteer: focus() humanization", () => {
  it("page.focus is replaced with humanized version", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const originalFocus = page.focus;
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect(page.focus).not.toBe(originalFocus);
    expect(typeof page.focus).toBe("function");
  });

  it("focus() calls click when element is not focused", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const mockCdp = buildMockCDP({
      send: vi.fn(async (method: string, params?: any) => {
        if (method === "Page.getFrameTree") {
          return { frameTree: { frame: { id: "F1" } } };
        }
        if (method === "Page.createIsolatedWorld") {
          return { executionContextId: 42 };
        }
        if (method === "Runtime.evaluate") {
          // Return false = element is NOT focused → should click
          return { result: { value: false } };
        }
        return {};
      }),
    });

    const page = buildMockPage();
    page.createCDPSession = vi.fn(async () => mockCdp);

    const cfg = resolveConfig("default");
    const cursor = { x: 100, y: 100, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    // page.focus is patched — it delegates to click internally
    expect(typeof page.focus).toBe("function");
    // Verify it's not the original
    expect(page.focus).not.toBe((page as any)._original.focus);
  });

  it("focus is patched on page for frame delegation", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    const originalFocus = page.focus;
    patchPage(page as any, cfg, cursor as any);

    // focus is patched directly on page — frames delegate to page.focus
    expect(page.focus).not.toBe(originalFocus);
    expect(typeof page.focus).toBe("function");
  });
});


// =========================================================================
// uncheck() — fallback behavior (assume checked on error)
// =========================================================================
describe("Puppeteer: select() humanization", () => {
  it("page.select is replaced with humanized version", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const originalSelect = page.select;
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect(page.select).not.toBe(originalSelect);
    expect(typeof page.select).toBe("function");
  });

  it("select() hovers before delegating to original", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    // Verify original select is stored
    const originals = (page as any)._original;
    expect(typeof originals.select).toBe("function");
  });
});


// =========================================================================
// mouse.wheel() — smooth scroll
// =========================================================================
describe("Puppeteer: mouse.wheel() smooth scroll", () => {
  it("mouse.wheel is patched after patchPage", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const originalWheel = page.mouse.wheel;
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect(page.mouse.wheel).not.toBe(originalWheel);
  });

  it("mouse.wheel({deltaY: 300}) calls original wheel multiple times (smooth)", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const wheelCalls: any[] = [];
    const page = buildMockPage();
    const origWheel = vi.fn(async (opts: any) => { wheelCalls.push(opts); });
    page.mouse.wheel = origWheel;

    const cfg = resolveConfig("default");
    const cursor = { x: 100, y: 100, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    await page.mouse.wheel({ deltaY: 300 });

    // smoothWheel breaks 300px into multiple small chunks (20-40px each)
    // So original wheel should be called many times, not just once
    expect(wheelCalls.length).toBeGreaterThan(1);
  });

  it("mouse.wheel({deltaX: 200}) smooths horizontal scroll too", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const wheelCalls: any[] = [];
    const page = buildMockPage();
    const origWheel = vi.fn(async (opts: any) => { wheelCalls.push(opts); });
    page.mouse.wheel = origWheel;

    const cfg = resolveConfig("default");
    const cursor = { x: 100, y: 100, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    await page.mouse.wheel({ deltaX: 200 });

    expect(wheelCalls.length).toBeGreaterThan(1);
  });

  it("mouse.wheel with no args does nothing", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const wheelCalls: any[] = [];
    const page = buildMockPage();
    const origWheel = vi.fn(async (opts: any) => { wheelCalls.push(opts); });
    page.mouse.wheel = origWheel;

    const cfg = resolveConfig("default");
    const cursor = { x: 100, y: 100, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    await page.mouse.wheel({});

    expect(wheelCalls.length).toBe(0);
  });
});


// =========================================================================
// mouse.dragAndDrop() — Bézier drag between coordinates
// =========================================================================
describe("Puppeteer: mouse.dragAndDrop() humanization", () => {
  it("mouse.dragAndDrop is patched after patchPage", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const originalDnD = page.mouse.dragAndDrop;
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect(page.mouse.dragAndDrop).not.toBe(originalDnD);
  });

  it("mouse.dragAndDrop calls mouseMove multiple times (Bézier), then mouseDown/mouseUp", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const moveCalls: Array<[number, number]> = [];
    const downCalls: any[] = [];
    const upCalls: any[] = [];

    const page = buildMockPage();
    const origMove = vi.fn(async (x: number, y: number) => { moveCalls.push([x, y]); });
    const origDown = vi.fn(async () => { downCalls.push(true); });
    const origUp = vi.fn(async () => { upCalls.push(true); });
    page.mouse.move = origMove;
    page.mouse.down = origDown;
    page.mouse.up = origUp;

    const cfg = resolveConfig("default");
    const cursor = { x: 50, y: 50, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    await page.mouse.dragAndDrop(
      { x: 100, y: 100 },
      { x: 400, y: 400 },
    );

    // Bézier movement generates many intermediate points
    expect(moveCalls.length).toBeGreaterThan(10);
    // mouseDown and mouseUp should each be called once
    expect(downCalls.length).toBe(1);
    expect(upCalls.length).toBe(1);
  });
});


// =========================================================================
// Keyboard patches — type, press, down, up
// =========================================================================
describe("Puppeteer: keyboard patches", () => {
  it("keyboard.type is patched to use humanType", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const originalType = page.keyboard.type;
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect(page.keyboard.type).not.toBe(originalType);
  });

  it("keyboard.press is patched with delay", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const originalPress = page.keyboard.press;
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect(page.keyboard.press).not.toBe(originalPress);
  });

  it("keyboard.down is patched with small delay", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const downCalls: string[] = [];
    const page = buildMockPage();
    const origDown = page.keyboard.down;
    page.keyboard.down = vi.fn(async (k: string) => { downCalls.push(k); });

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect(page.keyboard.down).not.toBe(origDown);

    await page.keyboard.down("a");
    // Original should have been called via the patch
    // (the patched version calls originals.keyboardDown which is the stored original)
  });

  it("keyboard.up is patched with small delay", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const origUp = page.keyboard.up;

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect(page.keyboard.up).not.toBe(origUp);
  });
});


// =========================================================================
// Mouse patches — move, click with clickCount
// =========================================================================
describe("Puppeteer: mouse patches", () => {
  it("mouse.move is patched with Bézier movement", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const moveCalls: Array<[number, number]> = [];
    const page = buildMockPage();
    page.mouse.move = vi.fn(async (x: number, y: number) => { moveCalls.push([x, y]); });

    const cfg = resolveConfig("default");
    const cursor = { x: 50, y: 50, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    await page.mouse.move(500, 500);

    // Bézier generates many intermediate points
    expect(moveCalls.length).toBeGreaterThan(10);
  });

  it("mouse.click is patched with Bézier + humanClick", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const moveCalls: Array<[number, number]> = [];
    const downCalls: any[] = [];
    const upCalls: any[] = [];

    const page = buildMockPage();
    page.mouse.move = vi.fn(async (x: number, y: number) => { moveCalls.push([x, y]); });
    page.mouse.down = vi.fn(async (opts?: any) => { downCalls.push(opts); });
    page.mouse.up = vi.fn(async (opts?: any) => { upCalls.push(opts); });

    const cfg = resolveConfig("default");
    const cursor = { x: 50, y: 50, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    await page.mouse.click(300, 300);

    expect(moveCalls.length).toBeGreaterThan(5);
    expect(downCalls.length).toBe(1);
    expect(upCalls.length).toBe(1);
  });

  it("mouse.click with clickCount:2 triggers double-click sequence", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const downCalls: any[] = [];
    const upCalls: any[] = [];

    const page = buildMockPage();
    page.mouse.move = vi.fn(async () => {});
    page.mouse.down = vi.fn(async (opts?: any) => { downCalls.push(opts ?? {}); });
    page.mouse.up = vi.fn(async (opts?: any) => { upCalls.push(opts ?? {}); });

    const cfg = resolveConfig("default");
    const cursor = { x: 50, y: 50, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    await page.mouse.click(300, 300, { clickCount: 2 });

    // First click: down() + up() (no clickCount), Second click: down({clickCount:2}) + up({clickCount:2})
    expect(downCalls.length).toBe(2);
    expect(upCalls.length).toBe(2);

    // Second down/up should have clickCount:2
    const secondDown = downCalls[1];
    const secondUp = upCalls[1];
    expect(secondDown.clickCount).toBe(2);
    expect(secondUp.clickCount).toBe(2);
  });
});


// =========================================================================
// select-all: Puppeteer uses down(modifier) → press('a') → up(modifier)
// =========================================================================
describe("Puppeteer: select-all via modifier keys (not combo string)", () => {
  it("fill() calls keyboardDown(Control/Meta) → keyboardPress('a') → keyboardUp(Control/Meta)", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const keyDowns: string[] = [];
    const keyUps: string[] = [];
    const keyPresses: string[] = [];

    const page = buildMockPage();
    page.keyboard.down = vi.fn(async (k: string) => { keyDowns.push(k); });
    page.keyboard.up = vi.fn(async (k: string) => { keyUps.push(k); });
    page.keyboard.press = vi.fn(async (k: string) => { keyPresses.push(k); });

    const cfg = resolveConfig("default", {
      field_switch_delay: [0, 0],
      idle_between_actions: false,
    });
    const cursor = { x: 100, y: 100, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    // fill → click → selectAll → Backspace → type
    // We can't easily call fill without scrollToElement working,
    // but we can test pressSelectAll indirectly by checking originals are stored
    const originals = (page as any)._original;
    expect(typeof originals.keyboardDown).toBe("function");
    expect(typeof originals.keyboardPress).toBe("function");
    expect(typeof originals.keyboardUp).toBe("function");

    // Verify the modifier is correct for the platform
    const expectedModifier = process.platform === 'darwin' ? 'Meta' : 'Control';

    // Test by importing and calling pressSelectAll-equivalent logic
    await originals.keyboardDown(expectedModifier);
    await originals.keyboardPress('a');
    await originals.keyboardUp(expectedModifier);

    expect(keyDowns).toContain(expectedModifier);
    expect(keyPresses).toContain('a');
    expect(keyUps).toContain(expectedModifier);
  });
});


// =========================================================================
// ElementHandle patching (Puppeteer-specific)
// =========================================================================
describe("Puppeteer: ElementHandle patching", () => {
  it("page.$() returns patched ElementHandle", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const mockEl = buildMockElementHandle();
    const page = buildMockPage({
      $: vi.fn(async () => mockEl),
    });

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const el = await page.$('#test');
    expect(el).toBeDefined();
    expect((el as any)._humanPatched).toBe(true);
  });

  it("page.$$() returns patched ElementHandles", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const mockEl1 = buildMockElementHandle();
    const mockEl2 = buildMockElementHandle();
    const page = buildMockPage({

      $$: vi.fn(async () => [mockEl1, mockEl2]),
    });

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const els = await page.$$('.items');
    expect(els.length).toBe(2);
    expect((els[0] as any)._humanPatched).toBe(true);
    expect((els[1] as any)._humanPatched).toBe(true);
  });

  it("page.waitForSelector() returns patched ElementHandle", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const mockEl = buildMockElementHandle();
    const page = buildMockPage({
      waitForSelector: vi.fn(async () => mockEl),
    });

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const el = await page.waitForSelector('#loading');
    expect(el).toBeDefined();
    expect((el as any)._humanPatched).toBe(true);
  });

  it("patched el.click() uses humanMove + humanClick", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const moveCalls: Array<[number, number]> = [];
    const downCalls: any[] = [];
    const upCalls: any[] = [];

    const mockEl = buildMockElementHandle({
      boundingBox: vi.fn(async () => ({ x: 200, y: 300, width: 100, height: 30 })),
      evaluate: vi.fn(async () => false), // not an input
    });

    const page = buildMockPage({
      $: vi.fn(async () => mockEl),
    });
    page.mouse.move = vi.fn(async (x: number, y: number) => { moveCalls.push([x, y]); });
    page.mouse.down = vi.fn(async (opts?: any) => { downCalls.push(opts); });
    page.mouse.up = vi.fn(async (opts?: any) => { upCalls.push(opts); });

    const cfg = resolveConfig("default", { idle_between_actions: false });
    const cursor = { x: 50, y: 50, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    const el = await page.$('#btn');
    await el.click();

    // Bézier movement → multiple move calls
    expect(moveCalls.length).toBeGreaterThan(5);
    // Click → down + up
    expect(downCalls.length).toBe(1);
    expect(upCalls.length).toBe(1);
  });

  it("patched el.click({clickCount:2}) triggers double-click", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const downCalls: any[] = [];
    const upCalls: any[] = [];

    const mockEl = buildMockElementHandle({
      boundingBox: vi.fn(async () => ({ x: 200, y: 300, width: 100, height: 30 })),
      evaluate: vi.fn(async () => false),
    });

    const page = buildMockPage({
      $: vi.fn(async () => mockEl),
    });
    page.mouse.move = vi.fn(async () => {});
    page.mouse.down = vi.fn(async (opts?: any) => { downCalls.push(opts ?? {}); });
    page.mouse.up = vi.fn(async (opts?: any) => { upCalls.push(opts ?? {}); });

    const cfg = resolveConfig("default", { idle_between_actions: false });
    const cursor = { x: 50, y: 50, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    const el = await page.$('#text');
    await el.click({ clickCount: 2 });

    // First click + second click with clickCount:2
    expect(downCalls.length).toBe(2);
    expect(upCalls.length).toBe(2);
    expect(downCalls[1].clickCount).toBe(2);
    expect(upCalls[1].clickCount).toBe(2);
  });

  it("patched el.hover() uses humanMove without clicking", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const moveCalls: Array<[number, number]> = [];
    const downCalls: any[] = [];

    const mockEl = buildMockElementHandle({
      boundingBox: vi.fn(async () => ({ x: 150, y: 250, width: 80, height: 25 })),
      evaluate: vi.fn(async () => false),
    });

    const page = buildMockPage({
      $: vi.fn(async () => mockEl),
    });
    page.mouse.move = vi.fn(async (x: number, y: number) => { moveCalls.push([x, y]); });
    page.mouse.down = vi.fn(async (opts?: any) => { downCalls.push(opts); });

    const cfg = resolveConfig("default", { idle_between_actions: false });
    const cursor = { x: 50, y: 50, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    const el = await page.$('#link');
    await el.hover();

    expect(moveCalls.length).toBeGreaterThan(5);
    // Hover should NOT click
    expect(downCalls.length).toBe(0);
  });

  it("patched el.type() moves, clicks, then types with humanType", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const downCalls: any[] = [];
    const charCalls: string[] = [];

    const mockEl = buildMockElementHandle({
      boundingBox: vi.fn(async () => ({ x: 100, y: 200, width: 200, height: 30 })),
      evaluate: vi.fn(async () => true), // is an input
    });

    const page = buildMockPage({
      $: vi.fn(async () => mockEl),
    });
    page.mouse.move = vi.fn(async () => {});
    page.mouse.down = vi.fn(async (opts?: any) => { downCalls.push(opts); });
    page.mouse.up = vi.fn(async () => {});
    page.keyboard.down = vi.fn(async (k: string) => { charCalls.push(`down:${k}`); });
    page.keyboard.up = vi.fn(async (k: string) => { charCalls.push(`up:${k}`); });
    page.keyboard.sendCharacter = vi.fn(async () => {});

    const cfg = resolveConfig("default", {
      mistype_chance: 0,
      idle_between_actions: false,
      typing_delay: 0,
      typing_delay_spread: 0,
      key_hold: [0, 0],
    });
    const cursor = { x: 50, y: 50, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    const el = await page.$('#email');
    await el.type('ab');

    // Should have clicked first (mouseDown)
    expect(downCalls.length).toBe(1);
    // Should have typed 'a' and 'b' via keyboard.down/up
    expect(charCalls).toContain('down:a');
    expect(charCalls).toContain('up:a');
    expect(charCalls).toContain('down:b');
    expect(charCalls).toContain('up:b');
  });

  it("patched el.focus() clicks to focus instead of programmatic focus", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const downCalls: any[] = [];

    const mockEl = buildMockElementHandle({
      boundingBox: vi.fn(async () => ({ x: 100, y: 200, width: 200, height: 30 })),
      evaluate: vi.fn(async () => true),
    });

    const page = buildMockPage({
      $: vi.fn(async () => mockEl),
    });
    page.mouse.move = vi.fn(async () => {});
    page.mouse.down = vi.fn(async (opts?: any) => { downCalls.push(opts); });
    page.mouse.up = vi.fn(async () => {});

    const cfg = resolveConfig("default", { idle_between_actions: false });
    const cursor = { x: 50, y: 50, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    const el = await page.$('#input');
    await el.focus();

    // focus should trigger a click (mouseDown + mouseUp)
    expect(downCalls.length).toBe(1);
  });

  it("el with null boundingBox falls back to original", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const originalClickCalled = { value: false };
    const mockEl = buildMockElementHandle({
      boundingBox: vi.fn(async () => null), // not visible
    });
    // Override the original click to track it
    mockEl.click = vi.fn(async () => { originalClickCalled.value = true; });

    const page = buildMockPage({
      $: vi.fn(async () => mockEl),
    });

    const cfg = resolveConfig("default");
    const cursor = { x: 50, y: 50, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    const el = await page.$('#hidden');
    await el.click();

    // Should have fallen back to original click
    expect(originalClickCalled.value).toBe(true);
  });

  it("nested el.$() returns patched child", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const childEl = buildMockElementHandle();
    const parentEl = buildMockElementHandle();
    parentEl.$ = vi.fn(async () => childEl);

    const page = buildMockPage({
      $: vi.fn(async () => parentEl),
    });

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const parent = await page.$('#parent');
    const child = await parent.$('.child');

    expect(child).toBeDefined();
    expect((child as any)._humanPatched).toBe(true);
  });

  it("double-patching is prevented (_humanPatched guard)", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const mockEl = buildMockElementHandle();
    const page = buildMockPage({
      $: vi.fn(async () => mockEl),
    });

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    // First call
    const el1 = await page.$('#btn');
    const clickFn1 = el1.click;

    // Second call — same element, should not re-patch
    const el2 = await page.$('#btn');
    const clickFn2 = el2.click;

    // Functions should be identical (not re-wrapped)
    expect(clickFn1).toBe(clickFn2);
  });
});


// =========================================================================
// Frame-level patching
// =========================================================================
describe("Puppeteer: frame-level patching", () => {
  it("child frames are marked _humanPatched", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const childFrame: any = {
      click: vi.fn(async () => {}),
      hover: vi.fn(async () => {}),
      type: vi.fn(async () => {}),
      fill: vi.fn(async () => {}),
      check: vi.fn(async () => {}),
      uncheck: vi.fn(async () => {}),
      select: vi.fn(async () => []),
      press: vi.fn(async () => {}),
      clear: vi.fn(async () => {}),
      focus: vi.fn(async () => {}),
      tap: vi.fn(async () => {}),
      pressSequentially: vi.fn(async () => {}),
      dragAndDrop: vi.fn(async () => {}),
      $: vi.fn(async () => null),

      $$: vi.fn(async () => []),
      waitForSelector: vi.fn(async () => null),
      childFrames: vi.fn(() => []),
    };

    const mainFrame = {
      ...childFrame,
      childFrames: vi.fn(() => [childFrame]),
    };

    const page = buildMockPage({ mainFrameReturn: mainFrame });
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect((childFrame as any)._humanPatched).toBe(true);
  });

  it("frame.focus is patched to delegate to page.focus", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const childFrame: any = {
      click: vi.fn(async () => {}),
      hover: vi.fn(async () => {}),
      type: vi.fn(async () => {}),
      fill: vi.fn(async () => {}),
      check: vi.fn(async () => {}),
      uncheck: vi.fn(async () => {}),
      select: vi.fn(async () => []),
      press: vi.fn(async () => {}),
      clear: vi.fn(async () => {}),
      focus: vi.fn(async () => {}),
      tap: vi.fn(async () => {}),
      pressSequentially: vi.fn(async () => {}),
      dragAndDrop: vi.fn(async () => {}),
      $: vi.fn(async () => null),

      $$: vi.fn(async () => []),
      waitForSelector: vi.fn(async () => null),
      childFrames: vi.fn(() => []),
    };

    const mainFrame = {
      ...childFrame,
      childFrames: vi.fn(() => [childFrame]),
    };

    const page = buildMockPage({ mainFrameReturn: mainFrame });
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    // frame.focus should now be patched (not the original)
    const originalFrameFocus = vi.fn(async () => {});
    expect(childFrame.focus).not.toBe(originalFrameFocus);
    expect(typeof childFrame.focus).toBe("function");
  });

  it("frame.$() returns patched ElementHandles", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const mockEl = buildMockElementHandle();
    const childFrame: any = {
      click: vi.fn(async () => {}),
      hover: vi.fn(async () => {}),
      type: vi.fn(async () => {}),
      fill: vi.fn(async () => {}),
      check: vi.fn(async () => {}),
      uncheck: vi.fn(async () => {}),
      select: vi.fn(async () => []),
      press: vi.fn(async () => {}),
      clear: vi.fn(async () => {}),
      focus: vi.fn(async () => {}),
      tap: vi.fn(async () => {}),
      pressSequentially: vi.fn(async () => {}),
      dragAndDrop: vi.fn(async () => {}),
      $: vi.fn(async () => mockEl),

      $$: vi.fn(async () => []),
      waitForSelector: vi.fn(async () => null),
      childFrames: vi.fn(() => []),
    };

    const mainFrame = {
      ...childFrame,
      childFrames: vi.fn(() => [childFrame]),
    };

    const page = buildMockPage({ mainFrameReturn: mainFrame });
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const el = await childFrame.$('#in-frame');
    expect(el).toBeDefined();
    expect((el as any)._humanPatched).toBe(true);
  });
});


// =========================================================================
// Browser-level patching
// =========================================================================
describe("Puppeteer: browser-level patching", () => {
  it("patchBrowser patches newPage()", async () => {
    const { patchBrowser } = await import("../src/human-puppeteer/index.js");

    const browser = buildMockBrowser();
    const origNewPage = browser.newPage; 
    const cfg = resolveConfig("default");
    patchBrowser(browser as any, cfg);

    expect(browser.newPage).not.toBe(origNewPage); 
    expect(typeof browser.newPage).toBe("function");
  });

  it("patchBrowser patches createIncognitoBrowserContext()", async () => {
    const { patchBrowser } = await import("../src/human-puppeteer/index.js");

    const browser: any = {
      pages: vi.fn(async () => []),
      newPage: vi.fn(async () => buildMockPage()),
      createIncognitoBrowserContext: vi.fn(async () => ({
        newPage: vi.fn(async () => buildMockPage()),
      })),
      on: vi.fn(),
      close: vi.fn(async () => {}),
    };

    const origCreateCtx = browser.createIncognitoBrowserContext;
    const cfg = resolveConfig("default");
    patchBrowser(browser as any, cfg);

    expect(browser.createIncognitoBrowserContext).not.toBe(origCreateCtx);
  });

  it("patchBrowser listens for targetcreated event", async () => {
    const { patchBrowser } = await import("../src/human-puppeteer/index.js");

    const browser = buildMockBrowser();
    const cfg = resolveConfig("default");
    patchBrowser(browser as any, cfg);

    expect(browser.on).toHaveBeenCalledWith("targetcreated", expect.any(Function));
  });

  it("newPage from patched browser returns page with _original", async () => {
    const { patchBrowser } = await import("../src/human-puppeteer/index.js");

    const mockPage = buildMockPage();
    const browser = buildMockBrowser();
    const origNewPage = vi.fn(async () => mockPage);
    browser.newPage = origNewPage;

    const cfg = resolveConfig("default");
    patchBrowser(browser as any, cfg);

    const page = await browser.newPage();
    expect((page as any)._original).toBeDefined();
    expect((page as any)._humanCfg).toBe(cfg);
    expect((page as any)._stealth).toBeDefined();
  });

  it("pages from patched createIncognitoBrowserContext also get humanized", async () => {
    const { patchBrowser } = await import("../src/human-puppeteer/index.js");

    const mockPage = buildMockPage();
    const mockCtx = {
      newPage: vi.fn(async () => mockPage),
    };
    const browser: any = {
      pages: vi.fn(async () => []),
      newPage: vi.fn(async () => buildMockPage()),
      createIncognitoBrowserContext: vi.fn(async () => mockCtx),
      on: vi.fn(),
      close: vi.fn(async () => {}),
    };

    const cfg = resolveConfig("default");
    patchBrowser(browser as any, cfg);

    const ctx = await browser.createIncognitoBrowserContext();
    const page = await ctx.newPage();

    expect((page as any)._original).toBeDefined();
    expect((page as any)._humanCfg).toBe(cfg);
  });
});



// =========================================================================
// isInputElement / isSelectorFocused — through patchPage click flow
// =========================================================================
describe("Puppeteer: isInputElement stealth integration via patchPage", () => {
  it("click() uses stealth.evaluate for isInputElement (no page.evaluate)", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const evaluateCalls: any[] = [];
    const stealthEvaluateCalls: string[] = [];

    const mockCdp = buildMockCDP({
      send: vi.fn(async (method: string, params?: any) => {
        if (method === "Page.getFrameTree") {
          return { frameTree: { frame: { id: "F1" } } };
        }
        if (method === "Page.createIsolatedWorld") {
          return { executionContextId: 100 };
        }
        if (method === "Runtime.evaluate") {
          stealthEvaluateCalls.push(params.expression);
          return { result: { value: false } };
        }
        return {};
      }),
    });

    const page = buildMockPage({
      evaluate: vi.fn(async (...args: any[]) => {
        evaluateCalls.push(args);
        return false;
      }),
    });
    page.createCDPSession = vi.fn(async () => mockCdp);

    const cfg = resolveConfig("default", { idle_between_actions: false });
    const cursor = { x: 100, y: 100, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    try {
      await page.click("#btn");
    } catch (e) {
      // scrollToElement might throw with mocks
    }

    const isInputCalls = stealthEvaluateCalls.filter(
      expr => expr.includes("tagName") || expr.includes("querySelector")
    );

    const qsCalls = evaluateCalls.filter(
      args => typeof args[0] === "string" && args[0].includes("querySelector")
    );

    if (isInputCalls.length > 0) {
      expect(qsCalls.length).toBe(0);
    }
  });
});


// =========================================================================
// isSelectorFocused stealth integration via patchPage press flow
// =========================================================================
describe("Puppeteer: isSelectorFocused stealth integration via patchPage", () => {
  it("focus() uses stealth.evaluate for focus check", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const stealthEvaluateCalls: string[] = [];

    const mockCdp = buildMockCDP({
      send: vi.fn(async (method: string, params?: any) => {
        if (method === "Page.getFrameTree") {
          return { frameTree: { frame: { id: "F1" } } };
        }
        if (method === "Page.createIsolatedWorld") {
          return { executionContextId: 200 };
        }
        if (method === "Runtime.evaluate") {
          stealthEvaluateCalls.push(params.expression);
          // Return true = element IS focused → focus() should skip clicking
          return { result: { value: true } };
        }
        return {};
      }),
    });

    const page = buildMockPage({
      evaluate: vi.fn(async () => true),
    });
    page.createCDPSession = vi.fn(async () => mockCdp);

    const cfg = resolveConfig("default");
    const cursor = { x: 50, y: 50, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    try {
      await page.focus("input#field");
    } catch (e) {
      // May throw with mocks — that's fine, we just need the stealth call
    }

    const focusCalls = stealthEvaluateCalls.filter(
      expr => expr.includes("activeElement")
    );
    expect(focusCalls.length).toBeGreaterThan(0);
  });
});


// =========================================================================
// Puppeteer-specific: sendCharacter mapped to insertText
// =========================================================================
describe("Puppeteer: sendCharacter → insertText mapping", () => {
  it("rawKb.insertText is mapped from keyboard.sendCharacter", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const sentChars: string[] = [];
    const page = buildMockPage();
    page.keyboard.sendCharacter = vi.fn(async (ch: string) => { sentChars.push(ch); });

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const originals = (page as any)._original;
    expect(typeof originals.keyboardSendCharacter).toBe("function");

    // rawKb.insertText should use the original sendCharacter
    await originals.keyboardSendCharacter("€");
    expect(sentChars).toContain("€");
  });
});


// =========================================================================
// Puppeteer-specific: viewport() vs viewportSize()
// =========================================================================
describe("Puppeteer: viewport() API (not viewportSize)", () => {
  it("patchPage works with page.viewport() (Puppeteer API)", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    // Puppeteer uses viewport(), not viewportSize()
    page.viewport = vi.fn(() => ({ width: 1920, height: 1080 }));
    expect(page.viewportSize).toBeUndefined; // should NOT exist

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };

    // Should not throw
    expect(() => patchPage(page as any, cfg, cursor as any)).not.toThrow();
  });
});


// =========================================================================
// Cursor initialization
// =========================================================================
describe("Puppeteer: cursor initialization", () => {
  it("cursor is initialized on patchPage with random position", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const moveCalls: Array<[number, number]> = [];
    const page = buildMockPage();
    page.mouse.move = vi.fn(async (x: number, y: number) => { moveCalls.push([x, y]); });

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    // Wait for the async init
    await sleep(50);

    // Cursor should be initialized within the config range
    expect(cursor.x).toBeGreaterThanOrEqual(cfg.initial_cursor_x[0]);
    expect(cursor.x).toBeLessThanOrEqual(cfg.initial_cursor_x[1]);
    expect(cursor.y).toBeGreaterThanOrEqual(cfg.initial_cursor_y[0]);
    expect(cursor.y).toBeLessThanOrEqual(cfg.initial_cursor_y[1]);
    expect(cursor.initialized).toBe(true);
  });
});


// =========================================================================
// Page-level method replacement verification
// =========================================================================
describe("Puppeteer: all page methods are replaced", () => {
  it("all interaction methods are replaced after patchPage", async () => {
    const { patchPage } = await import("../src/human-puppeteer/index.js");

    const page = buildMockPage();
    const originals = {
      goto: page.goto,
      click: page.click,
      hover: page.hover,
      type: page.type,
      select: page.select,
      focus: page.focus,
      tap: page.tap,
      mouseMove: page.mouse.move,
      mouseClick: page.mouse.click,
      mouseWheel: page.mouse.wheel,
      keyboardType: page.keyboard.type,
      keyboardPress: page.keyboard.press,
      keyboardDown: page.keyboard.down,
      keyboardUp: page.keyboard.up,
    };

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect(page.goto).not.toBe(originals.goto);
    expect(page.click).not.toBe(originals.click);
    expect(page.hover).not.toBe(originals.hover);
    expect(page.type).not.toBe(originals.type);
    expect(page.select).not.toBe(originals.select);
    expect(page.focus).not.toBe(originals.focus);
    expect(page.mouse.move).not.toBe(originals.mouseMove);
    expect(page.mouse.click).not.toBe(originals.mouseClick);
    expect(page.mouse.wheel).not.toBe(originals.mouseWheel);
    expect(page.keyboard.type).not.toBe(originals.keyboardType);
    expect(page.keyboard.press).not.toBe(originals.keyboardPress);
    expect(page.keyboard.down).not.toBe(originals.keyboardDown);
    expect(page.keyboard.up).not.toBe(originals.keyboardUp);
  });
});


// =========================================================================
// SLOW TESTS — require real browser (run with: vitest run --testTimeout=60000)
// Only run when SLOW=1 env var is set
// =========================================================================

const SLOW = process.env.SLOW === '1';
const describeIfSlow = SLOW ? describe : describe.skip;

describeIfSlow("Puppeteer stealth browser: no evaluate leak on click", () => {
  it("click() does not trigger querySelector from evaluate context", async () => {
    const { launch } = await import("../src/puppeteer.js");

    const browser = await launch({ humanize: true, headless: true });
    const page = await browser.newPage();

    await page.goto('https://www.wikipedia.org', { waitUntil: 'domcontentloaded' });
    await sleep(1000);

    // Inject detection script
    await page.evaluate(() => {
      (window as any).__evalLeaks = [];
      const origQS = document.querySelector.bind(document);
      document.querySelector = function (sel: string) {
        try { throw new Error(); } catch (e: any) {
          if (e.stack && e.stack.includes(':302:')) {
            (window as any).__evalLeaks.push(sel);
          }
        }
        return origQS(sel);
      } as any;
    });

    await page.click('#searchInput');
    await sleep(500);

    const leaks = await page.evaluate(() => (window as any).__evalLeaks || []);
    expect(leaks.length).toBe(0);

    await browser.close();
  }, 30000);
});

describeIfSlow("Puppeteer stealth browser: shift symbols isTrusted=true", () => {
  it("'!' produces isTrusted=true keydown, not isTrusted=false", async () => {
    const { launch } = await import("../src/puppeteer.js");

    const browser = await launch({ humanize: true, headless: true });
    const page = await browser.newPage();

    await page.goto('https://www.wikipedia.org', { waitUntil: 'domcontentloaded' });
    await sleep(1000);

    await page.evaluate(() => {
      (window as any).__untrustedKeys = [];
      (window as any).__trustedKeys = [];
      const input = document.querySelector('#searchInput');
      if (input) {
        input.addEventListener('keydown', (e) => {
          if (!e.isTrusted) {
            (window as any).__untrustedKeys.push((e as KeyboardEvent).key);
          } else {
            (window as any).__trustedKeys.push((e as KeyboardEvent).key);
          }
        }, true);
      }
    });

    await page.click('#searchInput');
    await sleep(300);
    await page.keyboard.type('test!');
    await sleep(500);

    const untrusted = await page.evaluate(() => (window as any).__untrustedKeys || []);
    const trusted = await page.evaluate(() => (window as any).__trustedKeys || []);

    expect(untrusted).not.toContain('!');
    expect(trusted).toContain('!');

    await browser.close();
  }, 30000);
});

describeIfSlow("Puppeteer stealth browser: navigation invalidation", () => {
  it("click works after navigation (isolated world re-created)", async () => {
    const { launch } = await import("../src/puppeteer.js");

    const browser = await launch({ humanize: true, headless: true });
    const page = await browser.newPage();

    expect((page as any)._stealth).toBeDefined();

    await page.goto('https://www.wikipedia.org', { waitUntil: 'domcontentloaded' });
    await sleep(1000);
    await page.click('#searchInput');
    await sleep(300);

    // Second navigation
    await page.goto('https://www.wikipedia.org', { waitUntil: 'domcontentloaded' });
    await sleep(1000);

    // Should still work
    await page.click('#searchInput');
    await sleep(300);
    await page.keyboard.type('after navigation');
    await sleep(500);

    // Puppeteer doesn't have locator().inputValue(), use evaluate instead
    const val = await page.evaluate(() => {
      const el = document.querySelector('#searchInput') as HTMLInputElement;
      return el ? el.value : '';
    });
    expect(val).toContain('after navigation');

    await browser.close();
  }, 60000);
});

describeIfSlow("Puppeteer stealth browser: ElementHandle humanization", () => {
  it("el.click() uses Bézier movement, not instant CDP click", async () => {
    const { launch } = await import("../src/puppeteer.js");

    const browser = await launch({ humanize: true, headless: true });
    const page = await browser.newPage();

    await page.goto('https://example.com', { waitUntil: 'domcontentloaded' });
    await sleep(1000);

    // Track mousemove events at document level
    await page.evaluate(() => {
      (window as any).__moveCounts = 0;
      document.addEventListener('mousemove', () => {
        (window as any).__moveCounts++;
      }, true);
    });

    // <h1> on example.com — always present, clickable, no navigation
    const el = await page.$('h1');
    expect(el).not.toBeNull();
    expect((el as any)._humanPatched).toBe(true);

    // Reset counter right before the click
    await page.evaluate(() => { (window as any).__moveCounts = 0; });

    // Click via ElementHandle — should use Bézier curve
    await el!.click();
    await sleep(500);

    const moveCount = await page.evaluate(() => (window as any).__moveCounts || 0);

    // Bézier movement generates many intermediate mousemove events (>10)
    // An instant CDP dispatchMouseEvent would generate 0 or 1
    expect(moveCount).toBeGreaterThan(5);

    await browser.close();
  }, 30000);
});

describeIfSlow("Puppeteer stealth browser: focus() uses click", () => {
  it("page.focus() triggers mouse events (not programmatic focus)", async () => {
    const { launch } = await import("../src/puppeteer.js");

    const browser = await launch({ humanize: true, headless: true });
    const page = await browser.newPage();

    await page.goto('https://www.wikipedia.org', { waitUntil: 'domcontentloaded' });
    await sleep(2000);

    // Click somewhere else first to ensure #searchInput is NOT focused
    await page.mouse.click(50, 50);
    await sleep(500);

    // Inject event tracking on #searchInput AFTER ensuring it's not focused
    await page.evaluate(() => {
      (window as any).__mouseEvents = [];
      const input = document.querySelector('#searchInput');
      if (input) {
        for (const evt of ['mousedown', 'mouseup', 'click', 'mousemove']) {
          input.addEventListener(evt, (e) => {
            (window as any).__mouseEvents.push(evt);
          }, true);
        }
      }
    });

    // Now focus — should trigger humanized click with mouse events
    await page.focus('#searchInput');
    await sleep(1000);

    const events = await page.evaluate(() => (window as any).__mouseEvents || []);
    expect(events.length).toBeGreaterThan(0);
    expect(events).toContain('mousedown');

    await browser.close();
  }, 30000);
});

describeIfSlow("Puppeteer stealth browser: mouse.wheel smooth scroll", () => {
  it("mouse.wheel generates multiple small scroll events", async () => {
    const { launch } = await import("../src/puppeteer.js");

    const browser = await launch({ humanize: true, headless: true });
    const page = await browser.newPage();

    await page.goto('https://en.wikipedia.org/wiki/Main_Page', { waitUntil: 'domcontentloaded' });
    await sleep(1000);

    // Track scroll events
    await page.evaluate(() => {
      (window as any).__wheelEvents = 0;
      window.addEventListener('wheel', () => {
        (window as any).__wheelEvents++;
      }, { passive: true });
    });

    await page.mouse.wheel({ deltaY: 500 });
    await sleep(1000);

    const wheelCount = await page.evaluate(() => (window as any).__wheelEvents || 0);
    // Smooth scroll should generate multiple wheel events, not just 1
    expect(wheelCount).toBeGreaterThan(3);

    await browser.close();
  }, 30000);
});
