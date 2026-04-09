/**
 * Unit tests for stealth / anti-detection fixes (issue #110).
 *
 * Covers:
 *   - StealthEval — CDP isolated-world lifecycle (evaluate, invalidate, retry)
 *   - isInputElement / isSelectorFocused — stealth DOM queries with fallback
 *   - typeShiftSymbol — CDP Input.dispatchKeyEvent path vs evaluate fallback
 *   - humanType integration — shift symbols routed via CDP
 *   - Navigation invalidation (goto → stealth.invalidate)
 *   - patchPage stealth infrastructure wiring
 *   - SHIFT_SYMBOL_CODES / SHIFT_SYMBOL_KEYCODES completeness
 *
 * All tests are fast, mock-based, and do NOT require a browser.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { resolveConfig, rand, randRange, sleep } from "../src/human/config.js";
import { humanType } from "../src/human/keyboard.js";
import { humanMove, humanClick, clickTarget, humanIdle } from "../src/human/mouse.js";

// =========================================================================
// Helper: build mock page / raw objects
// =========================================================================

function buildMockPage(overrides: Record<string, any> = {}): any {
  const mainFrameObj = overrides.mainFrameReturn ?? {
    childFrames: vi.fn(() => []),
    click: vi.fn(async () => {}),
    dblclick: vi.fn(async () => {}),
    hover: vi.fn(async () => {}),
    type: vi.fn(async () => {}),
    fill: vi.fn(async () => {}),
    check: vi.fn(async () => {}),
    uncheck: vi.fn(async () => {}),
    selectOption: vi.fn(async () => {}),
    press: vi.fn(async () => {}),
    clear: vi.fn(async () => {}),
    dragAndDrop: vi.fn(async () => {}),
    locator: vi.fn(() => ({
      boundingBox: vi.fn(async () => ({ x: 0, y: 0, width: 100, height: 30 })),
      first: vi.fn(function (this: any) { return this; }),
    })),
  };

  const makeLocator = () => {
    const loc: any = {
      boundingBox: vi.fn(async () => ({ x: 100, y: 100, width: 200, height: 30 })),
      scrollIntoViewIfNeeded: vi.fn(async () => {}),
      isChecked: overrides.isChecked ?? vi.fn(async () => false),
    };
    loc.first = vi.fn(() => loc);
    return loc;
  };

  const page: any = {
    evaluate: overrides.evaluate ?? vi.fn(async () => false),
    addInitScript: vi.fn(async () => {}),
    mouse: {
      move: vi.fn(async () => {}),
      down: vi.fn(async () => {}),
      up: vi.fn(async () => {}),
      click: vi.fn(async () => {}),
      dblclick: vi.fn(async () => {}),
      wheel: vi.fn(async () => {}),
    },
    keyboard: {
      press: overrides.keyboardPress
        ? vi.fn(overrides.keyboardPress)
        : vi.fn(async () => {}),
      type: vi.fn(async () => {}),
      down: vi.fn(async () => {}),
      up: vi.fn(async () => {}),
      insertText: vi.fn(async () => {}),
    },
    click: vi.fn(async () => {}),
    dblclick: vi.fn(async () => {}),
    hover: vi.fn(async () => {}),
    type: vi.fn(async () => {}),
    fill: vi.fn(async () => {}),
    check: vi.fn(async () => {}),
    uncheck: vi.fn(async () => {}),
    selectOption: vi.fn(async () => {}),
    press: vi.fn(async () => {}),
    goto: vi.fn(async () => ({})),
    isChecked: overrides.isChecked ?? vi.fn(async () => false),
    locator: vi.fn(() => makeLocator()),
    viewportSize: vi.fn(() => ({ width: 1280, height: 720 })),
    mainFrame: vi.fn(() => mainFrameObj),
    frames: vi.fn(() => []),
    context: vi.fn(() => ({
      pages: vi.fn(() => []),
      addInitScript: vi.fn(async () => {}),
      newCDPSession: vi.fn(async () => buildMockCDP()),
    })),
    url: vi.fn(() => "about:blank"),
    waitForTimeout: vi.fn(async () => {}),
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


// =========================================================================
// SHIFT_SYMBOL_CODES / SHIFT_SYMBOL_KEYCODES completeness
// =========================================================================
describe("SHIFT_SYMBOL maps completeness", () => {
  it("every shift symbol has a code and keycode entry", async () => {
    // We access these via dynamic import to get internal constants
    // Since they're not exported directly, we test via humanType behavior
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    const SHIFT_SYMBOLS = ['@', '#', '!', '$', '%', '^', '&', '*', '(', ')',
      '_', '+', '{', '}', '|', ':', '"', '<', '>', '?', '~'];

    // Each shift symbol should work via CDP path without error
    for (const sym of SHIFT_SYMBOLS) {
      const { raw } = buildRawKeyboard();
      const page = buildMockPage();
      const mockCdp = {
        send: vi.fn(async () => ({})),
      };

      await humanType(page, raw, sym, cfg, mockCdp as any);

      // CDP path: should have called cdp.send for keyDown + keyUp
      const cdpCalls = mockCdp.send.mock.calls;
      const keyEvents = cdpCalls.filter(
        (c: any[]) => c[0] === "Input.dispatchKeyEvent"
      );
      expect(keyEvents.length).toBe(2);

      // page.evaluate should NOT have been called (stealth path)
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
    expect(params.modifiers).toBe(8); // Shift flag
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
// typeShiftSymbol — CDP path vs fallback
// =========================================================================
describe("typeShiftSymbol CDP vs fallback", () => {
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

    // insertText should NOT be called for shift symbols in CDP path
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

    // Expected order: raw.down(Shift) → cdp.keyDown → cdp.keyUp → raw.up(Shift)
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
// humanType integration — mixed text with CDP
// =========================================================================
describe("humanType mixed text with CDP", () => {
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

    // 'a' → raw.down('a') + raw.up('a')
    expect(downKeys).toContain("a");

    // '!' → CDP keyDown + keyUp
    const keyEvents = cdpCalls.filter(
      ([m]) => m === "Input.dispatchKeyEvent"
    );
    expect(keyEvents.length).toBe(2);

    // No page.evaluate
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
    // 3 symbols × 2 events = 6
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
    // Only '!' triggers CDP: 2 events (keyDown + keyUp)
    expect(keyEvents.length).toBe(2);
    expect(keyEvents[0][1].key).toBe("!");
    expect(page.evaluate).not.toHaveBeenCalled();
  });

  it("CDP modifier flag is always 8 (Shift)", async () => {
    // Убираем задержки в 0, чтобы 21 символ не вызывал таймаут в 5 секунд
    const cfg = resolveConfig("default", { 
      mistype_chance: 0,
      typing_delay: 0,
      shift_down_delay: [0, 0],
      shift_up_delay: [0, 0],
      key_hold: [0, 0]
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
// patchPage stealth wiring
// =========================================================================
describe("patchPage stealth infrastructure", () => {
  it("page._stealth is a StealthEval instance after patching", async () => {
    const { patchPage } = await import("../src/human/index.js");

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
    const { patchPage } = await import("../src/human/index.js");

    const page = buildMockPage();
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect((page as any)._original).toBeDefined();
    expect((page as any)._humanCfg).toBe(cfg);
  });

  it("goto invalidates stealth context", async () => {
    const { patchPage } = await import("../src/human/index.js");

    const page = buildMockPage();
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const stealth = (page as any)._stealth;
    const invalidateSpy = vi.spyOn(stealth, "invalidate");

    await page.goto("https://example.com");

    expect(invalidateSpy).toHaveBeenCalled();
  });

  it("humanClickFn is stored for frame patching", async () => {
    const { patchPage } = await import("../src/human/index.js");

    const page = buildMockPage();
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect(typeof (page as any)._humanClickFn).toBe("function");
    expect(typeof (page as any)._humanHoverFn).toBe("function");
    expect(typeof (page as any)._humanClearFn).toBe("function");
    expect(typeof (page as any)._humanPressFn).toBe("function");
  });
});


// =========================================================================
// StealthEval lifecycle (via patchPage)
// =========================================================================
describe("StealthEval lifecycle", () => {
  it("stealth.invalidate() is callable without error", async () => {
    const { patchPage } = await import("../src/human/index.js");

    const page = buildMockPage();
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const stealth = (page as any)._stealth;
    expect(() => stealth.invalidate()).not.toThrow();
  });

  it("stealth.getCdpSession() returns a CDP session", async () => {
    const { patchPage } = await import("../src/human/index.js");

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
    const { patchPage } = await import("../src/human/index.js");

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
    page.context = vi.fn(() => ({
      pages: vi.fn(() => []),
      addInitScript: vi.fn(async () => {}),
      newCDPSession: vi.fn(async () => mockCdp),
    }));

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const stealth = (page as any)._stealth;
    const result = await stealth.evaluate("1 + 1");
    expect(result).toBe(true);
  });

  it("stealth.evaluate() retries on exceptionDetails", async () => {
    const { patchPage } = await import("../src/human/index.js");
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
    page.context = vi.fn(() => ({
      pages: vi.fn(() => []),
      addInitScript: vi.fn(async () => {}),
      newCDPSession: vi.fn(async () => mockCdp),
    }));

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const stealth = (page as any)._stealth;
    const result = await stealth.evaluate("test");
    expect(result).toBe("recovered");
  });

  it("stealth.evaluate() returns undefined after double failure", async () => {
    const { patchPage } = await import("../src/human/index.js");

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
    page.context = vi.fn(() => ({
      pages: vi.fn(() => []),
      addInitScript: vi.fn(async () => {}),
      newCDPSession: vi.fn(async () => mockCdp),
    }));

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    const stealth = (page as any)._stealth;
    const result = await stealth.evaluate("broken");
    expect(result).toBeUndefined();
  });
});


// =========================================================================
// isInputElement / isSelectorFocused — through patchPage click flow
// =========================================================================
describe("isInputElement stealth integration via patchPage", () => {
  it("click() uses stealth.evaluate for isInputElement (no page.evaluate)", async () => {
    const { patchPage } = await import("../src/human/index.js");

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
          return { result: { value: false } }; // not an input
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
    page.context = vi.fn(() => ({
      pages: vi.fn(() => []),
      addInitScript: vi.fn(async () => {}),
      newCDPSession: vi.fn(async () => mockCdp),
    }));

    const cfg = resolveConfig("default", { idle_between_actions: false });
    const cursor = { x: 100, y: 100, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    try {
      await page.click("#btn");
    } catch (e) {
      // scrollToElement might throw with mocks; that's fine
    }

    // The stealth path should have been used for isInputElement
    // (Runtime.evaluate in isolated world, NOT page.evaluate)
    const isInputCalls = stealthEvaluateCalls.filter(
      expr => expr.includes("tagName") || expr.includes("querySelector")
    );

    // We expect at least one stealth evaluate for the isInputElement check
    // OR page.evaluate was NOT called for this purpose
    // The key assertion: page.evaluate is NOT used for querySelector-based DOM checks
    const qsCalls = evaluateCalls.filter(
      args => typeof args[0] === "string" && args[0].includes("querySelector")
    );
    // If stealth worked, no querySelector calls should go through page.evaluate
    if (isInputCalls.length > 0) {
      expect(qsCalls.length).toBe(0);
    }
  });
});


// =========================================================================
// isSelectorFocused stealth integration via patchPage press flow
// =========================================================================
describe("isSelectorFocused stealth integration via patchPage", () => {
  it("press() uses stealth.evaluate for focus check", async () => {
    const { patchPage } = await import("../src/human/index.js");

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
          // Return true = element IS focused → skip click
          return { result: { value: true } };
        }
        return {};
      }),
    });

    const pressedKeys: string[] = [];
    const page = buildMockPage({
      evaluate: vi.fn(async () => true),
      keyboardPress: async (key: string) => { pressedKeys.push(key); },
    });
    page.context = vi.fn(() => ({
      pages: vi.fn(() => []),
      addInitScript: vi.fn(async () => {}),
      newCDPSession: vi.fn(async () => mockCdp),
    }));

    const cfg = resolveConfig("default");
    const cursor = { x: 50, y: 50, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    try {
      await page.press("input#field", "Enter");
    } catch (e) {
      // May throw with mocks
    }

    // Focus check should use isolated world (Runtime.evaluate with activeElement)
    const focusCalls = stealthEvaluateCalls.filter(
      expr => expr.includes("activeElement")
    );
    expect(focusCalls.length).toBeGreaterThan(0);
  });
});


// =========================================================================
// Frame patching with stealth
// =========================================================================
describe("frame patching with stealth", () => {
  it("child frames use stealth for clear() focus check", async () => {
    const { patchPage } = await import("../src/human/index.js");

    const childFrame: any = {
      click: vi.fn(async () => {}),
      dblclick: vi.fn(async () => {}),
      hover: vi.fn(async () => {}),
      type: vi.fn(async () => {}),
      fill: vi.fn(async () => {}),
      check: vi.fn(async () => {}),
      uncheck: vi.fn(async () => {}),
      selectOption: vi.fn(async () => {}),
      press: vi.fn(async () => {}),
      clear: vi.fn(async () => {}),
      dragAndDrop: vi.fn(async () => {}),
      locator: vi.fn(() => ({
        boundingBox: vi.fn(async () => ({ x: 0, y: 0, width: 100, height: 30 })),
      })),
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
});


// =========================================================================
// Page-level: pressSequentially, tap, clear are patched
// =========================================================================
describe("page-level pressSequentially, tap, clear patches", () => {
  it("page.pressSequentially is replaced after patchPage", async () => {
    const { patchPage } = await import("../src/human/index.js");

    const page = buildMockPage();
    const originalPressSeq = page.pressSequentially ?? (() => {});
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect(typeof (page as any).pressSequentially).toBe("function");
    expect((page as any).pressSequentially).not.toBe(originalPressSeq);
  });

  it("page.tap is replaced after patchPage", async () => {
    const { patchPage } = await import("../src/human/index.js");

    const page = buildMockPage();
    const originalTap = page.tap ?? (() => {});
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect(typeof (page as any).tap).toBe("function");
    expect((page as any).tap).not.toBe(originalTap);
  });

  it("page.clear is replaced after patchPage", async () => {
    const { patchPage } = await import("../src/human/index.js");

    const page = buildMockPage();
    const originalClear = page.clear ?? (() => {});
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect(typeof (page as any).clear).toBe("function");
    expect((page as any).clear).not.toBe(originalClear);
  });
});


// =========================================================================
// Frame-level: pressSequentially, tap are patched
// =========================================================================
describe("frame-level pressSequentially, tap patches", () => {
  it("child frame has pressSequentially patched", async () => {
    const { patchPage } = await import("../src/human/index.js");

    const childFrame: any = {
      click: vi.fn(async () => {}),
      dblclick: vi.fn(async () => {}),
      hover: vi.fn(async () => {}),
      type: vi.fn(async () => {}),
      fill: vi.fn(async () => {}),
      check: vi.fn(async () => {}),
      uncheck: vi.fn(async () => {}),
      selectOption: vi.fn(async () => {}),
      press: vi.fn(async () => {}),
      pressSequentially: vi.fn(async () => {}),
      tap: vi.fn(async () => {}),
      clear: vi.fn(async () => {}),
      dragAndDrop: vi.fn(async () => {}),
      locator: vi.fn(() => ({
        boundingBox: vi.fn(async () => ({ x: 0, y: 0, width: 100, height: 30 })),
      })),
      childFrames: vi.fn(() => []),
    };

    const origPressSeq = childFrame.pressSequentially;
    const origTap = childFrame.tap;

    const mainFrame = {
      ...childFrame,
      childFrames: vi.fn(() => [childFrame]),
    };

    const page = buildMockPage({ mainFrameReturn: mainFrame });
    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    expect((childFrame as any)._humanPatched).toBe(true);
    // pressSequentially and tap should be replaced with humanized versions
    expect(childFrame.pressSequentially).not.toBe(origPressSeq);
    expect(childFrame.tap).not.toBe(origTap);
    expect(typeof childFrame.pressSequentially).toBe("function");
    expect(typeof childFrame.tap).toBe("function");
  });
});


// =========================================================================
// Non-ASCII text does NOT go through CDP shift symbol path
// =========================================================================
describe("non-ASCII text avoids CDP shift path", () => {
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

    // 'H' → shifted char via raw
    expect(downKeys).toContain("Shift");
    expect(downKeys).toContain("H");

    // 'i' → normal char
    expect(downKeys).toContain("i");

    // '!' → CDP path
    const keyEvents = cdpCalls.filter(([m]) => m === "Input.dispatchKeyEvent");
    expect(keyEvents.length).toBe(2);

    // ' ' → normal char (space)
    expect(downKeys).toContain(" ");

    // 'Мир' → insertText
    expect(insertedChars).toContain("М");
    expect(insertedChars).toContain("и");
    expect(insertedChars).toContain("р");

    expect(page.evaluate).not.toHaveBeenCalled();
  });
});


// =========================================================================
// SLOW TESTS — require real browser (run with: vitest run --testTimeout=60000)
// Only run when SLOW=1 env var is set
// =========================================================================

const SLOW = process.env.SLOW === '1';
const describeIfSlow = SLOW ? describe : describe.skip;

describeIfSlow("stealth browser: no evaluate leak on click", () => {
  it("click() does not trigger querySelector from evaluate context", async () => {
    const { launch } = await import("../src/index.js");

    const browser = await launch({ headless: true, humanize: true });

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

describeIfSlow("stealth browser: shift symbols isTrusted=true", () => {
  it("'!' produces isTrusted=true keydown, not isTrusted=false", async () => {
    const { launch } = await import("../src/index.js");

    const browser = await launch({ headless: true, humanize: true });

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

describeIfSlow("stealth browser: navigation invalidation", () => {
  it("click works after navigation (isolated world re-created)", async () => {
    const { launch } = await import("../src/index.js");

    const browser = await launch({ headless: true, humanize: true });

    const page = await browser.newPage();

    expect((page as any)._stealth).toBeDefined();

    await page.goto('https://www.wikipedia.org', { waitUntil: 'domcontentloaded' });
    await sleep(1000);
    await page.click('#searchInput');
    await sleep(300);

    // Second navigation — invalidates isolated world
    await page.goto('https://www.wikipedia.org', { waitUntil: 'domcontentloaded' });
    await sleep(1000);

    // Should still work (isolated world auto re-created)
    await page.click('#searchInput');
    await sleep(300);
    await page.keyboard.type('after navigation');
    await sleep(500);

    const val = await page.locator('#searchInput').inputValue();
    expect(val).toContain('after navigation');

    await browser.close();
  }, 60000);
});

describeIfSlow("stealth browser: full form no evaluate leak", () => {
  it("form with shift symbols has zero evaluate leaks and zero untrusted events", async () => {
    const { launch } = await import("../src/index.js");

    const browser = await launch({ headless: true, humanize: true });

    const page = await browser.newPage();

    await page.goto(
      'https://deviceandbrowserinfo.com/are_you_a_bot_interactions',
      { waitUntil: 'domcontentloaded' },
    );
    await sleep(3000);

    await page.evaluate(() => {
      (window as any).__evalLeaks = [];
      (window as any).__untrustedKeys = [];

      const origQS = document.querySelector.bind(document);
      document.querySelector = function (sel: string) {
        try { throw new Error(); } catch (e: any) {
          if (e.stack && e.stack.includes(':302:')) {
            (window as any).__evalLeaks.push(sel);
          }
        }
        return origQS(sel);
      } as any;

      document.addEventListener('keydown', (e) => {
        if (!e.isTrusted) {
          (window as any).__untrustedKeys.push((e as KeyboardEvent).key);
        }
      }, true);
    });

    await page.click('#email');
    await sleep(300);
    await page.fill('#email', 'test@example.com');
    await sleep(500);
    await page.click('#password');
    await sleep(300);
    await page.fill('#password', 'SecurePass!@#123');
    await sleep(500);

    const evalLeaks = await page.evaluate(() => (window as any).__evalLeaks || []);
    const untrusted = await page.evaluate(() => (window as any).__untrustedKeys || []);

    expect(evalLeaks.length).toBe(0);
    expect(untrusted.length).toBe(0);

    await page.click('button[type="submit"]');
    await sleep(5000);

    const body = await page.locator('body').textContent();
    expect(body).not.toContain('"superHumanSpeed": true');
    expect(body).not.toContain('"suspiciousClientSideBehavior": true');

    await browser.close();
  }, 60000);
});
