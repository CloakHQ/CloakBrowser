import { describe, it, expect } from "vitest";
import {
  buildBoxJs, buildActionableJs, buildPointerJs, parseResult,
  OK, NOT_FOUND, UNSUPPORTED,
} from "../src/human/stealthDom.js";
import {
  ensureActionable, checkPointerEvents, CHECKS_CLICK,
  ElementNotVisibleError, ElementNotEnabledError, ElementNotAttachedError,
  ElementNotReceivingEventsError,
} from "../src/human/actionability.js";
import { getElementBox } from "../src/human/scroll.js";

// ---------------------------------------------------------------------------
// Test doubles
// ---------------------------------------------------------------------------

/** Fake isolated world: returns a canned value (or per-expression callable). */
function fakeWorld(response: any) {
  const calls: string[] = [];
  return {
    calls,
    async evaluate(expr: string) {
      calls.push(expr);
      return typeof response === "function" ? response(expr) : response;
    },
  };
}

/** A page whose .locator throws — proves the world handled the read (no Playwright). */
function noLocatorPage(world: any) {
  return {
    _stealth: world,
    locator() { throw new Error("Playwright locator must not be used when the world handles the read"); },
  } as any;
}

/** Minimal DOM element stub for running the shipped resolver JS under Node. */
function el(tag: string, text = "", kids: any[] = []) {
  const e: any = {
    tagName: tag, textContent: text, children: kids,
    disabled: false, readOnly: false, isContentEditable: false,
    getAttribute: () => null,
  };
  e.contains = (o: any) => o === e || (e.children || []).some((c: any) => c.contains && c.contains(o));
  e.getBoundingClientRect = () => ({ x: 5, y: 6, width: 20, height: 10 });
  return e;
}

/** Execute a shipped builder's JS expression against a recording DOM stub. */
function runBuilder(js: string, matches: any[], point?: any) {
  const document = {
    querySelectorAll: (_s: string) => matches.slice(),
    evaluate: () => ({ snapshotLength: matches.length, snapshotItem: (i: number) => matches[i] }),
    elementFromPoint: (_x: number, _y: number) => point ?? null,
  };
  const fn = new Function("document", "XPathResult", "getComputedStyle", "return " + js);
  return fn(document, { ORDERED_NODE_SNAPSHOT_TYPE: 7 }, () => ({ visibility: "visible", display: "block" }));
}

// ---------------------------------------------------------------------------
// Builders + parseResult
// ---------------------------------------------------------------------------

describe("stealthDom builders", () => {
  it("box JS escapes the selector and reads geometry", () => {
    const js = buildBoxJs('a"b');
    expect(js).toContain('"a\\"b"');
    expect(js).toContain("getBoundingClientRect");
  });

  it("pointer JS inlines coordinates", () => {
    expect(buildPointerJs("#x", 1.5, 2.5)).toContain("elementFromPoint(1.5, 2.5)");
  });

  it("parseResult maps statuses", () => {
    expect(parseResult({ r: "ok", box: { x: 1 } })).toEqual({ status: OK, data: { r: "ok", box: { x: 1 } } });
    expect(parseResult({ r: "not_found" })).toEqual({ status: NOT_FOUND });
    expect(parseResult({ r: "unsupported" })).toEqual({ status: UNSUPPORTED });
    // evaluate returns undefined on error -> unsupported, never not_found
    expect(parseResult(undefined)).toEqual({ status: UNSUPPORTED });
    expect(parseResult(null)).toEqual({ status: UNSUPPORTED });
    expect(parseResult([])).toEqual({ status: UNSUPPORTED });
  });
});

// ---------------------------------------------------------------------------
// Shipped resolver JS semantics (run under Node against DOM stubs)
// ---------------------------------------------------------------------------

describe("resolver semantics (shipped JS)", () => {
  it(":has-text + trailing nth resolves and reads a box", () => {
    const r = runBuilder(buildBoxJs("button:has-text('Submit') >> nth=0"), [el("BUTTON", "Submit"), el("BUTTON", "other")]);
    expect(r.r).toBe("ok");
    expect(r.box).toEqual({ x: 5, y: 6, width: 20, height: 10 });
  });

  it("unsupported grammar is reported", () => {
    expect(runBuilder(buildBoxJs("internal:role=button"), []).r).toBe("unsupported");
    expect(runBuilder(buildBoxJs("a >> b"), [el("A")]).r).toBe("unsupported");
  });

  it("genuine not-found", () => {
    expect(runBuilder(buildBoxJs("button"), []).r).toBe("not_found");
  });

  it("actionable reads visibility/enabled", () => {
    const r = runBuilder(buildActionableJs("button"), [el("BUTTON", "x")]);
    expect(r.r).toBe("ok");
    expect(r.visible).toBe(true);
    expect(r.enabled).toBe(true);
  });

  it("pointer hit-test resolves against the element", () => {
    const target = el("BUTTON", "x");
    const r = runBuilder(buildPointerJs("button", 5, 5), [target], target);
    expect(r).toEqual({ r: "ok", hit: true });
  });
});

// ---------------------------------------------------------------------------
// Rewired helpers: world-handled path must never touch Playwright
// ---------------------------------------------------------------------------

describe("ensureActionable via isolated world", () => {
  it("ok returns without Playwright", async () => {
    const world = fakeWorld({ r: "ok", visible: true, enabled: true, editable: true });
    await ensureActionable(noLocatorPage(world), "#x", CHECKS_CLICK, 100);
    expect(world.calls.length).toBe(1);
  });

  it("not visible throws", async () => {
    const page = noLocatorPage(fakeWorld({ r: "ok", visible: false, enabled: true, editable: true }));
    await expect(ensureActionable(page, "#x", CHECKS_CLICK, 100)).rejects.toBeInstanceOf(ElementNotVisibleError);
  });

  it("not visible with no box throws without a Playwright cross-check (#560)", async () => {
    const page = noLocatorPage(fakeWorld({ r: "ok", visible: false, enabled: true, editable: true, box: null }));
    await expect(ensureActionable(page, "#x", CHECKS_CLICK, 100)).rejects.toBeInstanceOf(ElementNotVisibleError);
  });

  it("not visible with a non-empty box but Playwright agrees still throws (#560)", async () => {
    const world = fakeWorld({ r: "ok", visible: false, enabled: true, editable: true, box: { x: 0, y: 0, width: 10, height: 10 } });
    const loc = { first: () => ({ isVisible: async () => false }) };
    const page: any = { _stealth: world, locator: () => loc };
    await expect(ensureActionable(page, "#x", CHECKS_CLICK, 100)).rejects.toBeInstanceOf(ElementNotVisibleError);
  });

  it("not visible with a non-empty box and Playwright disagrees does not throw (#560)", async () => {
    const world = fakeWorld({ r: "ok", visible: false, enabled: true, editable: true, box: { x: 0, y: 0, width: 10, height: 10 } });
    const loc = { first: () => ({ isVisible: async () => true }) };
    const page: any = { _stealth: world, locator: () => loc };
    await expect(ensureActionable(page, "#x", CHECKS_CLICK, 100)).resolves.toBeUndefined();
  });

  it("disabled throws", async () => {
    const page = noLocatorPage(fakeWorld({ r: "ok", visible: true, enabled: false, editable: true }));
    await expect(ensureActionable(page, "#x", CHECKS_CLICK, 100)).rejects.toBeInstanceOf(ElementNotEnabledError);
  });

  it("not_found throws attached", async () => {
    const page = noLocatorPage(fakeWorld({ r: "not_found" }));
    await expect(ensureActionable(page, "#x", CHECKS_CLICK, 100)).rejects.toBeInstanceOf(ElementNotAttachedError);
  });

  it("unsupported falls back to Playwright", async () => {
    const loc = { first: () => ({
      waitFor: async () => {}, isVisible: async () => true, isEnabled: async () => true, isEditable: async () => true,
    }) };
    let called = false;
    const page: any = { _stealth: fakeWorld({ r: "unsupported" }), locator: () => { called = true; return loc; } };
    await ensureActionable(page, "internal:role=button", CHECKS_CLICK, 100);
    expect(called).toBe(true);
  });
});

describe("getElementBox via isolated world", () => {
  it("ok returns box without Playwright", async () => {
    const box = { x: 10, y: 20, width: 30, height: 40 };
    expect(await getElementBox(noLocatorPage(fakeWorld({ r: "ok", box })), "#x")).toEqual(box);
  });

  it("not_found stays in-world and returns null", async () => {
    expect(await getElementBox(noLocatorPage(fakeWorld({ r: "not_found" })), "#x", 100)).toBeNull();
  });

  it("unsupported falls back to Playwright", async () => {
    const box = { x: 1, y: 2, width: 3, height: 4 };
    let called = false;
    const page: any = {
      _stealth: fakeWorld({ r: "unsupported" }),
      locator: () => { called = true; return { first: () => ({ boundingBox: async () => box }) }; },
    };
    expect(await getElementBox(page, "internal:role=button")).toEqual(box);
    expect(called).toBe(true);
  });
});

describe("checkPointerEvents via isolated world", () => {
  it("hit returns", async () => {
    const world = fakeWorld({ r: "ok", hit: true });
    await checkPointerEvents(noLocatorPage(world), "#x", 5, 5, world, 200);
  });

  it("miss throws", async () => {
    const world = fakeWorld({ r: "ok", hit: false, covering: "DIV" });
    await expect(checkPointerEvents(noLocatorPage(world), "#x", 5, 5, world, 200))
      .rejects.toBeInstanceOf(ElementNotReceivingEventsError);
  });

  it("unsupported falls back to Playwright", async () => {
    const world = fakeWorld({ r: "unsupported" });
    let called = false;
    const page: any = { _stealth: world, locator: () => { called = true; return { first: () => ({
      boundingBox: async () => ({ x: 0, y: 0, width: 10, height: 10 }), evaluate: async () => ({ hit: true }),
    }) }; } };
    await checkPointerEvents(page, "internal:role=button", 5, 5, world, 200);
    expect(called).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// display:contents (#560) — shipped resolver JS executed against a DOM stub
// that supports firstChild/nextSibling traversal, per-element computed style,
// and Range.getBoundingClientRect() for text nodes.
// ---------------------------------------------------------------------------

describe("display:contents visibility/box (#560)", () => {
  function contentsEl(tag: string, display = "block") {
    const e: any = {
      nodeType: 1, tagName: tag, disabled: false, readOnly: false, isContentEditable: false,
      getAttribute: () => null, firstChild: null, nextSibling: null,
      __display: display, __rect: { x: 0, y: 0, width: 0, height: 0 },
    };
    e.getBoundingClientRect = () => e.__rect;
    return e;
  }

  function textNode(text: string, rect: { x: number; y: number; width: number; height: number }) {
    return { nodeType: 3, textContent: text, nextSibling: null, __rect: rect };
  }

  function appendChild(parent: any, child: any) {
    if (!parent.firstChild) { parent.firstChild = child; return; }
    let last = parent.firstChild;
    while (last.nextSibling) last = last.nextSibling;
    last.nextSibling = child;
  }

  function run(js: string, root: any) {
    const document = {
      querySelectorAll: (_s: string) => [root],
      createRange: () => ({
        _n: null as any,
        selectNode(this: any, n: any) { this._n = n; },
        getBoundingClientRect(this: any) { return this._n.__rect; },
      }),
    };
    const getComputedStyle = (el: any) => ({ visibility: "visible", display: el.__display ?? "block" });
    const fn = new Function("document", "getComputedStyle", "return " + js);
    return fn(document, getComputedStyle);
  }

  it("a display:contents <li> with a bare text child reads visible with the text's rect", () => {
    const li = contentsEl("LI", "contents");
    appendChild(li, textNode("Hoy", { x: 10, y: 20, width: 30, height: 12 }));

    const actionable = run(buildActionableJs("li"), li);
    expect(actionable).toEqual({ r: "ok", visible: true, enabled: true, editable: false, box: { x: 10, y: 20, width: 30, height: 12 } });

    const box = run(buildBoxJs("li"), li);
    expect(box).toEqual({ r: "ok", box: { x: 10, y: 20, width: 30, height: 12 } });
  });

  it("a display:contents element unions multiple visible children's rects", () => {
    const container = contentsEl("DIV", "contents");
    appendChild(container, textNode("a", { x: 0, y: 0, width: 10, height: 10 }));
    appendChild(container, textNode("b", { x: 20, y: 5, width: 10, height: 10 }));

    const box = run(buildBoxJs("div"), container);
    expect(box).toEqual({ r: "ok", box: { x: 0, y: 0, width: 30, height: 15 } });
  });

  it("a display:contents element with no visible content is reported not_found / not visible", () => {
    const li = contentsEl("LI", "contents");
    appendChild(li, textNode("   ", { x: 0, y: 0, width: 0, height: 0 })); // whitespace-only text

    expect(run(buildBoxJs("li"), li)).toEqual({ r: "not_found" });
    const actionable = run(buildActionableJs("li"), li);
    expect(actionable.visible).toBe(false);
  });

  it("a normal (non-contents) element is unaffected", () => {
    const li = contentsEl("LI", "block");
    li.__rect = { x: 1, y: 2, width: 3, height: 4 };

    expect(run(buildBoxJs("li"), li)).toEqual({ r: "ok", box: { x: 1, y: 2, width: 3, height: 4 } });
  });
});
