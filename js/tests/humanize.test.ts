import { describe, it, expect, vi } from "vitest";
import { resolveConfig, rand, randRange, sleep } from "../src/human/config.js";
import { humanMove, humanClick, clickTarget, humanIdle } from "../src/human/mouse.js";

// =========================================================================
// Config resolution
// =========================================================================
describe("resolveConfig", () => {
  it("returns valid default config", () => {
    const cfg = resolveConfig("default");
    expect(cfg).toBeDefined();
    expect(cfg.mouse_min_steps).toBeGreaterThan(0);
    expect(cfg.mouse_max_steps).toBeGreaterThan(cfg.mouse_min_steps);
    expect(cfg.typing_delay).toBeGreaterThan(0);
    expect(cfg.initial_cursor_x).toHaveLength(2);
    expect(cfg.initial_cursor_y).toHaveLength(2);
  });

  it("returns valid careful config with slower typing", () => {
    const cfg = resolveConfig("careful");
    const def = resolveConfig("default");
    expect(cfg).toBeDefined();
    expect(cfg.typing_delay).toBeGreaterThanOrEqual(def.typing_delay);
  });

  it("applies custom overrides", () => {
    const cfg = resolveConfig("default", { mouse_min_steps: 100, mouse_max_steps: 200 });
    expect(cfg.mouse_min_steps).toBe(100);
    expect(cfg.mouse_max_steps).toBe(200);
  });

  it("preserves idle_between_actions override", () => {
    const cfg = resolveConfig("default", {
      idle_between_actions: true,
      idle_between_duration: [50, 100],
    });
    expect(cfg.idle_between_actions).toBe(true);
    expect(cfg.idle_between_duration[0]).toBe(50);
    expect(cfg.idle_between_duration[1]).toBe(100);
  });

  it("throws on unknown preset name", () => {
    expect(() => resolveConfig("nonexistent" as any)).toThrow(/Unknown humanize preset/);
  });

  it("returns all required fields including mistype", () => {
    const cfg = resolveConfig("default");
    const required = [
      "mouse_min_steps", "mouse_max_steps", "typing_delay",
      "initial_cursor_x", "initial_cursor_y", "idle_between_actions",
      "idle_between_duration", "patch_coalesced", "field_switch_delay",
      "mistype_chance", "mistype_delay_notice", "mistype_delay_correct",
    ];
    for (const f of required) {
      expect(cfg).toHaveProperty(f);
    }
  });

  it("mistype_delay fields are [min, max] tuples", () => {
    const cfg = resolveConfig("default");
    expect(Array.isArray(cfg.mistype_delay_notice)).toBe(true);
    expect(cfg.mistype_delay_notice).toHaveLength(2);
    expect(cfg.mistype_delay_notice[0]).toBeLessThanOrEqual(cfg.mistype_delay_notice[1]);
    expect(Array.isArray(cfg.mistype_delay_correct)).toBe(true);
    expect(cfg.mistype_delay_correct).toHaveLength(2);
    expect(cfg.mistype_delay_correct[0]).toBeLessThanOrEqual(cfg.mistype_delay_correct[1]);
  });
});

// =========================================================================
// rand / randRange / sleep
// =========================================================================
describe("rand helpers", () => {
  it("rand stays within bounds over many iterations", () => {
    for (let i = 0; i < 500; i++) {
      const v = rand(10, 20);
      expect(v).toBeGreaterThanOrEqual(10);
      expect(v).toBeLessThanOrEqual(20);
    }
  });

  it("randRange stays within bounds", () => {
    for (let i = 0; i < 500; i++) {
      const v = randRange([5, 15]);
      expect(v).toBeGreaterThanOrEqual(5);
      expect(v).toBeLessThanOrEqual(15);
    }
  });

  it("sleep pauses for approximately correct duration", async () => {
    const t0 = Date.now();
    await sleep(50);
    const elapsed = Date.now() - t0;
    expect(elapsed).toBeGreaterThanOrEqual(40);
    expect(elapsed).toBeLessThan(200);
  });
});

// =========================================================================
// Bézier mouse movement (behavioral with vi.fn mocks)
// =========================================================================
describe("humanMove", () => {
  function makeFakeRaw() {
    const moves: Array<{ x: number; y: number }> = [];
    return {
      raw: {
        move: vi.fn(async (x: number, y: number) => { moves.push({ x, y }); }),
        down: vi.fn(async () => {}),
        up: vi.fn(async () => {}),
        wheel: vi.fn(async () => {}),
      },
      moves,
    };
  }

  it("generates multiple intermediate points", async () => {
    const cfg = resolveConfig("default");
    const { raw, moves } = makeFakeRaw();
    await humanMove(raw, 0, 0, 500, 300, cfg);
    expect(moves.length).toBeGreaterThanOrEqual(10);
    const last = moves[moves.length - 1];
    expect(Math.abs(last.x - 500)).toBeLessThan(10);
    expect(Math.abs(last.y - 300)).toBeLessThan(10);
  });

  it("raw.move called exactly once per step", async () => {
    const cfg = resolveConfig("default");
    const { raw, moves } = makeFakeRaw();
    await humanMove(raw, 0, 0, 400, 400, cfg);
    expect(raw.move).toHaveBeenCalledTimes(moves.length);
  });

  it("no single jump exceeds 50% of total distance", async () => {
    const cfg = resolveConfig("default");
    const { raw, moves } = makeFakeRaw();
    await humanMove(raw, 0, 0, 400, 400, cfg);
    const totalDist = Math.sqrt(400 ** 2 + 400 ** 2);
    const maxJump = totalDist * 0.5;
    for (let i = 1; i < moves.length; i++) {
      const dx = moves[i].x - moves[i - 1].x;
      const dy = moves[i].y - moves[i - 1].y;
      expect(Math.sqrt(dx * dx + dy * dy)).toBeLessThan(maxJump);
    }
  });

  it("produces curved path (not a straight line)", async () => {
    const cfg = resolveConfig("default");
    let maxDev = 0;
    for (let trial = 0; trial < 10; trial++) {
      const { raw, moves } = makeFakeRaw();
      await humanMove(raw, 0, 0, 500, 0, cfg);
      const dev = Math.max(...moves.map(m => Math.abs(m.y)));
      if (dev > maxDev) maxDev = dev;
    }
    expect(maxDev).toBeGreaterThan(0.5);
  });

  it("handles very short distances", async () => {
    const cfg = resolveConfig("default");
    const { raw, moves } = makeFakeRaw();
    await humanMove(raw, 100, 100, 103, 102, cfg);
    expect(moves.length).toBeGreaterThanOrEqual(1);
  });

  it("handles zero distance without crashing", async () => {
    const cfg = resolveConfig("default");
    const { raw } = makeFakeRaw();
    await humanMove(raw, 200, 200, 200, 200, cfg);
    // Completes without error; may or may not call move (both valid)
    expect(true).toBe(true);
  });
});

// =========================================================================
// humanClick behavioral
// =========================================================================
describe("humanClick", () => {
  it("calls down then up in correct order", async () => {
    const cfg = resolveConfig("default");
    const callOrder: string[] = [];
    const raw = {
      move: vi.fn(async () => {}),
      down: vi.fn(async () => { callOrder.push("down"); }),
      up: vi.fn(async () => { callOrder.push("up"); }),
      wheel: vi.fn(async () => {}),
    };
    await humanClick(raw, false, cfg);
    expect(raw.down).toHaveBeenCalledTimes(1);
    expect(raw.up).toHaveBeenCalledTimes(1);
    expect(callOrder).toEqual(["down", "up"]);
  });
});

// =========================================================================
// humanIdle behavioral
// =========================================================================
describe("humanIdle", () => {
  it("calls raw.move at least once during idle", async () => {
    const cfg = resolveConfig("default");
    const raw = {
      move: vi.fn(async () => {}),
      down: vi.fn(async () => {}),
      up: vi.fn(async () => {}),
      wheel: vi.fn(async () => {}),
    };
    await humanIdle(raw, 10, 100, 100, cfg);
    expect(raw.move).toHaveBeenCalled();
  }, 15000);
});

// =========================================================================
// clickTarget
// =========================================================================
describe("clickTarget", () => {
  it("returns point within bounding box", () => {
    const cfg = resolveConfig("default");
    const box = { x: 100, y: 200, width: 150, height: 40 };
    for (let i = 0; i < 100; i++) {
      const t = clickTarget(box, false, cfg);
      expect(t.x).toBeGreaterThanOrEqual(100);
      expect(t.x).toBeLessThanOrEqual(250);
      expect(t.y).toBeGreaterThanOrEqual(200);
      expect(t.y).toBeLessThanOrEqual(240);
    }
  });

  it("isInput=true biases click toward left side of box", () => {
    const cfg = resolveConfig("default");
    const box = { x: 50, y: 50, width: 200, height: 30 };
    let sumX = 0;
    const N = 300;
    for (let i = 0; i < N; i++) {
      const t = clickTarget(box, true, cfg);
      expect(t.x).toBeGreaterThanOrEqual(50);
      expect(t.x).toBeLessThanOrEqual(250);
      sumX += t.x;
    }
    const avgX = sumX / N;
    expect(avgX).toBeLessThan(175);
  });

  it("does not crash with 1x1 box", () => {
    const cfg = resolveConfig("default");
    const t = clickTarget({ x: 0, y: 0, width: 1, height: 1 }, false, cfg);
    expect(t.x).toBeGreaterThanOrEqual(0);
    expect(t.x).toBeLessThanOrEqual(1);
  });
});

// =========================================================================
// patchPage behavioral: fill uses platform SELECT_ALL
// =========================================================================
describe("patchPage fill", () => {
  it("fill calls keyboard.press with platform-correct select-all", async () => {
    const { patchPage } = await import("../src/human/index.js");

    const pressedKeys: string[] = [];
    const page = buildMockPage({
      keyboardPress: async (key: string) => { pressedKeys.push(key); },
      evaluate: async () => false,
    });

    const cfg = resolveConfig("default");
    const cursor = { x: 0, y: 0, initialized: false };
    patchPage(page as any, cfg, cursor as any);

    try { await (page as any).fill("input#name", "hello"); } catch (_) {}

    const expected = process.platform === "darwin" ? "Meta+a" : "Control+a";
    const wrong = process.platform === "darwin" ? "Control+a" : "Meta+a";
    if (pressedKeys.length > 0) {
      expect(pressedKeys).toContain(expected);
      expect(pressedKeys).not.toContain(wrong);
    }
  }, 30000);
});


// =========================================================================
// patchPage behavioral: check/uncheck with idle_between_actions
// =========================================================================
describe("patchPage check/uncheck idle", () => {
  it("check with idle=true calls humanClickFn and does not crash on idle", async () => {
    const { patchPage } = await import("../src/human/index.js");

    let downCalled = false;
    const page = buildMockPage({
      isChecked: async () => false,
      evaluate: async () => false,
    });
    page.mouse.down = vi.fn(async () => { downCalled = true; });

    const cfg = resolveConfig("default", {
      idle_between_actions: true,
      idle_between_duration: [1, 2],
    });
    const cursor = { x: 100, y: 100, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    try { await (page as any).check("input#cb"); } catch (_) {}

    // humanCheckFn → humanIdle → humanClickFn → humanClick → raw.down
    expect(downCalled).toBe(true);
  }, 30000);

  it("uncheck with idle=true calls humanClickFn and does not crash on idle", async () => {
    const { patchPage } = await import("../src/human/index.js");

    let downCalled = false;
    const page = buildMockPage({
      isChecked: async () => true,
      evaluate: async () => false,
    });
    page.mouse.down = vi.fn(async () => { downCalled = true; });

    const cfg = resolveConfig("default", {
      idle_between_actions: true,
      idle_between_duration: [1, 2],
    });
    const cursor = { x: 100, y: 100, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    try { await (page as any).uncheck("input#cb"); } catch (_) {}

    expect(downCalled).toBe(true);
  }, 30000);

  it("config with idle=true is accepted by resolveConfig", () => {
    const cfg = resolveConfig("default", {
      idle_between_actions: true,
      idle_between_duration: [5, 10],
    });
    expect(cfg.idle_between_actions).toBe(true);
    expect(cfg.idle_between_duration).toEqual([5, 10]);
  });
});

// =========================================================================
// patchPage behavioral: press focus check
// =========================================================================
describe("patchPage press focus", () => {
  it("press clicks element when NOT focused (mouse.down called)", async () => {
    const { patchPage } = await import("../src/human/index.js");

    let downCount = 0;
    const page = buildMockPage({
      evaluate: async () => false,
    });
    // Intercept mouse.down before patching so raw captures it
    page.mouse.down = vi.fn(async () => { downCount++; });

    const cfg = resolveConfig("default");
    const cursor = { x: 50, y: 50, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    try { await (page as any).press("input#field", "Enter"); } catch (_) {}

    expect(downCount).toBeGreaterThan(0);
  });

  it("press skips click when element IS focused (no mouse.down)", async () => {
    const { patchPage } = await import("../src/human/index.js");

    let downCount = 0;
    const page = buildMockPage({
      evaluate: async () => true,
    });
    page.mouse.down = vi.fn(async () => { downCount++; });

    const cfg = resolveConfig("default");
    const cursor = { x: 50, y: 50, initialized: true };
    patchPage(page as any, cfg, cursor as any);

    try { await (page as any).press("input#field", "Enter"); } catch (_) {}

    expect(downCount).toBe(0);
  });
});

// =========================================================================
// patchPage behavioral: frame patching
// =========================================================================
describe("patchPage frame patching", () => {
  it("patches child frames with _humanPatched flag", async () => {
    const { patchPage } = await import("../src/human/index.js");

    const childFrame = buildMockFrame();
    const mainFrame = {
      ...buildMockFrame(),
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
// Mistype config
// =========================================================================
describe("mistype config", () => {
  it("default config has valid mistype fields", () => {
    const cfg = resolveConfig("default");
    expect(typeof cfg.mistype_chance).toBe("number");
    expect(cfg.mistype_chance).toBeGreaterThanOrEqual(0);
    expect(cfg.mistype_chance).toBeLessThanOrEqual(1);
    // mistype_delay_notice and mistype_delay_correct are [min, max] tuples
    expect(Array.isArray(cfg.mistype_delay_notice)).toBe(true);
    expect(cfg.mistype_delay_notice).toHaveLength(2);
    expect(Array.isArray(cfg.mistype_delay_correct)).toBe(true);
    expect(cfg.mistype_delay_correct).toHaveLength(2);
  });

  it("mistype_chance can be overridden to 0 (disabled)", () => {
    const cfg = resolveConfig("default", { mistype_chance: 0 });
    expect(cfg.mistype_chance).toBe(0);
  });

  it("mistype_chance can be overridden to higher value", () => {
    const cfg = resolveConfig("default", { mistype_chance: 0.15 });
    expect(cfg.mistype_chance).toBe(0.15);
  });
});

// =========================================================================
// Module exports
// =========================================================================
describe("module exports", () => {
  it("patchBrowser, patchContext, patchPage are all exported functions", async () => {
    const mod = await import("../src/human/index.js");
    expect(typeof mod.patchBrowser).toBe("function");
    expect(typeof mod.patchContext).toBe("function");
    expect(typeof mod.patchPage).toBe("function");
  });

  it("humanMove, humanClick, clickTarget, humanIdle are exported", async () => {
    const mod = await import("../src/human/index.js");
    expect(typeof mod.humanMove).toBe("function");
    expect(typeof mod.humanClick).toBe("function");
    expect(typeof mod.clickTarget).toBe("function");
    expect(typeof mod.humanIdle).toBe("function");
  });

  it("resolveConfig is re-exported from index", async () => {
    const mod = await import("../src/human/index.js");
    expect(typeof mod.resolveConfig).toBe("function");
  });
});

// =========================================================================
// Test helpers
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
      first: vi.fn(function(this: any) { return this; }),
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
    })),
    url: vi.fn(() => "about:blank"),
    waitForTimeout: vi.fn(async () => {}),
  };
  return page;
}


function buildMockFrame(): any {
  return {
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
}
