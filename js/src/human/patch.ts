/**
 * Wire the humanize engine into playwright-core's client classes.
 * Port of cloakbrowser/human/patch.py.
 *
 * Patching is prototype-level and idempotent: Page, Frame, Locator,
 * ElementHandle, Mouse and Keyboard methods check whether their page was
 * humanized (`patchPage`) and otherwise call the original Playwright method.
 * Every humanized method:
 *
 * - accepts the options the original accepts plus `human_config` (and, for
 *   backwards compatibility, HumanConfig keys directly in the options);
 * - honours Playwright's semantics for those options (`button`, `clickCount`,
 *   `modifiers`, `position`, `trial`, `force`, `timeout` including page
 *   defaults and `0` = no limit, `strict`);
 * - throws Playwright `Error` / `TimeoutError` instead of silently falling
 *   back to Playwright's stock implementation.
 *
 * playwright-core does not export its client classes, so prototypes are
 * reached through live instances: the page itself, `page.mainFrame()`,
 * `page.locator()` (no protocol call), `page.mouse` / `page.keyboard`, and
 * the connection's object-creation hook (first ElementHandle created).
 */

import { createRequire } from 'node:module';
import type { Browser, BrowserContext, ElementHandle, Frame, Page } from 'playwright-core';
import { type HumanConfig, rand } from './config.js';
import { CursorState, Human, Target, type Opts, type RawInput } from './engine.js';

type Kind = 'Page' | 'Frame' | 'Locator' | 'ElementHandle' | 'Mouse' | 'Keyboard';
type Handler = (h: Human, self: any, args: any[]) => Promise<any>;

const PATCHED = new WeakSet<object>();
const ORIG = new WeakMap<object, Map<string, (...a: any[]) => any>>();
const MARK = Symbol.for('cloakbrowser.humanized');

const API_NAME: Record<Kind, string> = {
  Page: 'page', Frame: 'frame', Locator: 'locator', ElementHandle: 'elementHandle', Mouse: 'mouse', Keyboard: 'keyboard',
};

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function pageOf(kind: Kind, self: any): any {
  switch (kind) {
    case 'Page': return self;
    case 'Frame': return self._page;
    case 'Locator':
    case 'ElementHandle': return self._frame?._page;
    default: return self._page;
  }
}

function humanFor(kind: Kind, self: any): Human | null {
  // No try/catch: swallowing an error here would run Playwright's stock
  // action on a humanized page.
  return pageOf(kind, self)?._cloakHuman ?? null;
}

/** Per-call options: Playwright options + `human_config` + legacy direct
 * HumanConfig keys (`{ typing_delay: 30 }`). */
function opts(h: Human, o: any): Opts {
  const out: Opts = { ...(o ?? {}) };
  const direct: Record<string, unknown> = {};
  for (const k of Object.keys(out)) if (k in h.cfg) { direct[k] = out[k]; delete out[k]; }
  if (Object.keys(direct).length || out.human_config) out.human_config = { ...direct, ...(out.human_config ?? {}) };
  return out;
}

const isHandle = (v: any) => !!v && typeof v === 'object' && typeof v.boundingBox === 'function' && '_elementChannel' in v;

function selectValues(values: any): [any[], ElementHandle[]] {
  if (values === null || values === undefined) return [[], []];
  const list = Array.isArray(values) ? values : [values];
  const options: any[] = [], handles: ElementHandle[] = [];
  list.forEach((v, i) => {
    if (v === null || v === undefined) throw new Error(`options[${i}]: expected object, got null`);
    if (isHandle(v)) handles.push(v);
    else if (typeof v === 'string') options.push({ valueOrLabel: v });
    else {
      const o: any = {};
      for (const k of ['value', 'label', 'index']) if (v[k] !== undefined) o[k] = v[k];
      options.push(o);
    }
  });
  return [options, handles];
}

// ---------------------------------------------------------------------------
// targets
// ---------------------------------------------------------------------------

function frameOf(kind: Kind, self: any): Frame {
  return kind === 'Page' ? self.mainFrame() : self;
}

function target(kind: Kind, self: any, args: any[], o: Opts): { t: Target; rest: any[] } {
  if (kind === 'Page' || kind === 'Frame') return { t: new Target(frameOf(kind, self), args[0], !!o.strict), rest: args.slice(1) };
  if (kind === 'Locator') return { t: new Target(self._frame, self._selector, true), rest: args };
  return { t: new Target(self._frame, null, false, self), rest: args };
}

/** Index of the options argument for each method (after the selector for
 * Page / Frame). */
const OPT_INDEX: Record<string, number> = {
  click: 0, dblclick: 0, hover: 0, tap: 0, check: 0, uncheck: 0, focus: 0, clear: 0, scrollIntoViewIfNeeded: 0,
  fill: 1, type: 1, pressSequentially: 1, press: 1, setChecked: 1, selectOption: 1, dragTo: 1,
};

function handlers(kind: Kind): Record<string, Handler> {
  const api = API_NAME[kind];
  const sel = kind === 'Page' || kind === 'Frame' ? 1 : 0;
  const optArg = (name: string, args: any[]) => args[sel + OPT_INDEX[name]];
  const prep = (name: string, h: Human, self: any, args: any[]) => {
    const o = opts(h, optArg(name, args));
    return { o, ...target(kind, self, args, o) };
  };

  const table: Record<string, Handler> = {
    click: async (h, self, args) => { const { o, t } = prep('click', h, self, args); await h.click(t, o, `${api}.click`); },
    dblclick: async (h, self, args) => { const { o, t } = prep('dblclick', h, self, args); await h.click(t, o, `${api}.dblclick`, 2); },
    hover: async (h, self, args) => { const { o, t } = prep('hover', h, self, args); await h.hover(t, o, `${api}.hover`); },
    tap: async (h, self, args) => { const { o, t } = prep('tap', h, self, args); await h.tap(t, o, `${api}.tap`); },
    fill: async (h, self, args) => { const { o, t, rest } = prep('fill', h, self, args); await h.fill(t, String(rest[0]), o, `${api}.fill`); },
    type: async (h, self, args) => { const { o, t, rest } = prep('type', h, self, args); await h.type(t, String(rest[0]), o, `${api}.type`); },
    press: async (h, self, args) => { const { o, t, rest } = prep('press', h, self, args); await h.press(t, String(rest[0]), o, `${api}.press`); },
    check: async (h, self, args) => { const { o, t } = prep('check', h, self, args); await h.setChecked(t, true, o, `${api}.check`); },
    uncheck: async (h, self, args) => { const { o, t } = prep('uncheck', h, self, args); await h.setChecked(t, false, o, `${api}.uncheck`); },
    setChecked: async (h, self, args) => {
      const { o, t, rest } = prep('setChecked', h, self, args);
      await h.setChecked(t, !!rest[0], o, `${api}.setChecked`);
    },
    selectOption: async (h, self, args) => {
      const { o, t, rest } = prep('selectOption', h, self, args);
      const [options, handles] = selectValues(rest[0]);
      return h.selectOption(t, options, handles, o, `${api}.selectOption`);
    },
    focus: async (h, self, args) => {
      const { o, t } = prep('focus', h, self, args);
      await h.focus(t, o, `${api}.focus`, kind === 'ElementHandle');
    },
  };
  if (kind === 'Page' || kind === 'Frame') {
    table.dragAndDrop = async (h, self, args) => {
      const o = opts(h, args[2]);
      const frame = frameOf(kind, self);
      await h.drag(new Target(frame, args[0], !!o.strict), new Target(frame, args[1], !!o.strict), o, `${api}.dragAndDrop`);
    };
  }
  if (kind === 'Locator') {
    table.clear = async (h, self, args) => { const { o, t } = prep('clear', h, self, args); await h.fill(t, '', o, `${api}.clear`); };
    table.pressSequentially = async (h, self, args) => {
      const { o, t, rest } = prep('pressSequentially', h, self, args);
      await h.type(t, String(rest[0]), o, `${api}.pressSequentially`);
    };
    table.dragTo = async (h, self, args) => {
      const o = opts(h, args[1]);
      const other = args[0];
      await h.drag(new Target(self._frame, self._selector, true), new Target(other._frame, other._selector, true), o, `${api}.dragTo`);
    };
  }
  if (kind === 'Locator' || kind === 'ElementHandle') {
    table.scrollIntoViewIfNeeded = async (h, self, args) => {
      const { o, t } = prep('scrollIntoViewIfNeeded', h, self, args);
      await h.scrollIntoViewIfNeeded(t, o, `${api}.scrollIntoViewIfNeeded`);
    };
  }
  return table;
}

const INPUT_HANDLERS: Record<'Mouse' | 'Keyboard', Record<string, Handler>> = {
  Mouse: {
    move: (h, _s, [x, y, o]) => h.mouseMove(x, y, o?.steps),
    click: (h, _s, [x, y, o]) => h.mouseClick(x, y, o?.delay, o?.button, o?.clickCount),
    dblclick: (h, _s, [x, y, o]) => h.mouseClick(x, y, o?.delay, o?.button, 2),
  },
  Keyboard: {
    type: (h, _s, [text, o]) => h.keyboardType(String(text), o?.delay),
  },
};

// ---------------------------------------------------------------------------
// prototype patching
// ---------------------------------------------------------------------------

function wrap(kind: Kind, proto: any, name: string, handler: Handler): void {
  const orig = Object.prototype.hasOwnProperty.call(proto, name) ? proto[name] : undefined;
  if (typeof orig !== 'function' || orig[MARK]) return;
  if (!ORIG.has(proto)) ORIG.set(proto, new Map());
  ORIG.get(proto)!.set(name, orig);
  const wrapper = async function (this: any, ...args: any[]) {
    const h = humanFor(kind, this);
    if (!h) return orig.apply(this, args);
    return handler(h, this, args);
  };
  Object.defineProperty(wrapper, 'name', { value: name });
  (wrapper as any)[MARK] = true;
  proto[name] = wrapper;
}

function patchProto(kind: Kind, proto: any): void {
  if (!proto || proto === Object.prototype || PATCHED.has(proto)) return;
  PATCHED.add(proto);
  const table = kind === 'Mouse' || kind === 'Keyboard' ? INPUT_HANDLERS[kind] : handlers(kind);
  for (const [name, handler] of Object.entries(table)) wrap(kind, proto, name, handler);
}

/** The unpatched Playwright method `name` of `obj`'s class. */
export function original(obj: any, name: string): (...a: any[]) => any {
  for (let p = Object.getPrototypeOf(obj); p; p = Object.getPrototypeOf(p)) {
    const f = ORIG.get(p)?.get(name);
    if (f) return f;
    if (Object.prototype.hasOwnProperty.call(p, name)) return p[name];
  }
  return obj[name];
}

/** Oldest playwright-core whose client internals the engine relies on. */
export const MIN_PLAYWRIGHT = '1.53.0';

function playwrightVersion(): string {
  try {
    return createRequire(import.meta.url)('playwright-core/package.json').version ?? 'unknown';
  } catch { return 'unknown'; }
}

function versionAtLeast(v: string, min: string): boolean {
  const a = v.split('.').map((x) => parseInt(x, 10)), b = min.split('.').map((x) => parseInt(x, 10));
  for (let i = 0; i < b.length; i++) {
    if ((a[i] ?? 0) !== b[i]) return (a[i] ?? 0) > b[i];
  }
  return true;
}

function unsupported(reason: string): Error {
  return new Error(
    `cloakbrowser humanize requires playwright-core >= ${MIN_PLAYWRIGHT} ` +
    `(installed: ${playwrightVersion()}; ${reason}). Upgrade with: npm install playwright-core@latest`);
}

function install(page: Page): void {
  const p: any = page;
  const version = playwrightVersion();
  if (version !== 'unknown' && !versionAtLeast(version, MIN_PLAYWRIGHT)) throw unsupported('version too old');
  // Internals the engine uses on a real client object (Frame._timeout,
  // Connection._createRemoteObject). Fail loudly when one is missing instead of
  // letting actions fall back to Playwright's own.
  const conn = p._connection;
  if (conn) {
    if (typeof (page.mainFrame() as any)._timeout !== 'function') throw unsupported('missing Frame._timeout');
    if (typeof conn._createRemoteObject !== 'function') throw unsupported('missing Connection._createRemoteObject');
  }
  patchProto('Page', Object.getPrototypeOf(page));
  patchProto('Frame', Object.getPrototypeOf(page.mainFrame()));
  patchProto('Locator', Object.getPrototypeOf(page.locator('html')));
  patchProto('Mouse', Object.getPrototypeOf(page.mouse));
  patchProto('Keyboard', Object.getPrototypeOf(page.keyboard));
  // ElementHandle: the class is only reachable from an instance. Every protocol
  // object is created by Connection._createRemoteObject (all supported
  // playwright-core versions), so wrap it and patch the first handle's prototype.
  // Without this hook handle.click() would silently run Playwright's stock
  // action, so a missing hook is an error, not a skipped patch.
  if (conn && !conn.__cloakEH) {
    conn.__cloakEH = true;
    const create = conn._createRemoteObject;
    conn._createRemoteObject = function (this: any, parentGuid: string, type: string, ...rest: any[]) {
      const obj = create.call(this, parentGuid, type, ...rest);
      if (type === 'ElementHandle' && obj) patchProto('ElementHandle', Object.getPrototypeOf(obj));
      return obj;
    };
  }
}

// ---------------------------------------------------------------------------
// page attachment
// ---------------------------------------------------------------------------

function rawInput(page: Page): RawInput {
  const m: any = page.mouse, k: any = page.keyboard;
  const om = (n: string) => original(m, n).bind(m);
  const ok = (n: string) => original(k, n).bind(k);
  const move = om('move'), down = om('down'), up = om('up'), wheel = om('wheel');
  const kd = ok('down'), ku = ok('up'), kp = ok('press'), it = ok('insertText');
  return {
    move: (x, y, o) => move(x, y, o), down: (o) => down(o), up: (o) => up(o), wheel: (dx, dy) => wheel(dx, dy),
    keyDown: (key) => kd(key), keyUp: (key) => ku(key), keyPress: (key, o) => kp(key, o), insertText: (t) => it(t),
  };
}

const PAGE_ORIGINALS = ['click', 'dblclick', 'hover', 'type', 'fill', 'check', 'uncheck', 'selectOption', 'press', 'tap',
  'focus', 'setChecked', 'dragAndDrop'];

/** `page._original`: raw, un-humanized Playwright calls for this page. */
function originals(page: Page): Record<string, (...a: any[]) => any> {
  const out: Record<string, (...a: any[]) => any> = {};
  // Page methods only delegate to the main frame; call the original Frame
  // method directly so the humanized Frame wrapper is never re-entered.
  for (const name of PAGE_ORIGINALS) {
    out[name] = (...a: any[]) => { const f = page.mainFrame(); return original(f, name).apply(f, a); };
  }
  out.goto = (...a: any[]) => (page.goto as any)(...a);
  out.isChecked = (...a: any[]) => (page.isChecked as any)(...a);
  const m: any = page.mouse, k: any = page.keyboard;
  for (const n of ['move', 'click', 'dblclick', 'wheel', 'down', 'up']) {
    out[`mouse${n[0].toUpperCase()}${n.slice(1)}`] = original(m, n).bind(m);
  }
  for (const n of ['type', 'down', 'up', 'press', 'insertText']) {
    out[`keyboard${n[0].toUpperCase()}${n.slice(1)}`] = original(k, n).bind(k);
  }
  return out;
}

/** Humanize one page. */
export function patchPage(page: Page, cfg: HumanConfig, cursor: CursorState = new CursorState()): Human {
  install(page);
  const p: any = page;
  let human: Human = p._cloakHuman;
  if (!human) {
    human = new Human(page, cfg, cursor, rawInput(page));
    Object.defineProperty(p, '_cloakHuman', { value: human, configurable: true, writable: true });
  }
  p._original = originals(page);
  p._humanCfg = cfg;
  p._humanCursor = cursor;
  p._stealth = {
    evaluate: (expression: string) => human.worlds.evaluate(page.mainFrame(), expression),
    invalidate: () => human.worlds.invalidate(),
    getCdpSession: () => human.worlds.session(),
  };
  if (!cursor.initialized) {
    // Start near the address bar instead of (0, 0).
    cursor.x = rand(cfg.initial_cursor_x[0], cfg.initial_cursor_x[1]);
    cursor.y = rand(cfg.initial_cursor_y[0], cfg.initial_cursor_y[1]);
    cursor.initialized = true;
    human.raw.move(cursor.x, cursor.y).catch(() => { cursor.initialized = false; });
  }
  return human;
}

export function patchContext(context: BrowserContext, cfg: HumanConfig): void {
  const ctx: any = context;
  if (ctx._humanPatched) return;
  ctx._humanPatched = true;
  const cursor = new CursorState();
  for (const page of context.pages()) patchPage(page, cfg, cursor);
  context.on('page', (page: Page) => { if (!(page as any)._original) patchPage(page, cfg, new CursorState()); });
  const origNewPage = context.newPage.bind(context);
  ctx.newPage = async (...a: any[]) => {
    const page = await (origNewPage as any)(...a);
    if (!page._original) patchPage(page, cfg, new CursorState());
    return page;
  };
}

export function patchBrowser(browser: Browser, cfg: HumanConfig): void {
  for (const context of browser.contexts()) patchContext(context, cfg);
  const origNewContext = browser.newContext.bind(browser);
  (browser as any).newContext = async (...a: any[]) => {
    const context = await (origNewContext as any)(...a);
    patchContext(context, cfg);
    return context;
  };
  const origNewPage = browser.newPage.bind(browser);
  (browser as any).newPage = async (...a: any[]) => {
    const page = await (origNewPage as any)(...a);
    patchContext(page.context(), cfg);
    if (!page._original) patchPage(page, cfg, new CursorState());
    return page;
  };
}
