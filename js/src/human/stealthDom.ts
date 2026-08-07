/**
 * Isolated-world DOM reads for the humanize layer.
 *
 * The pre-click helpers (`ensureActionable`, `scrollToElement` geometry,
 * `checkPointerEvents`) read element state and geometry. This module performs
 * those reads inside the CDP isolated execution context (`(page as any)._stealth`,
 * a `StealthEval` created via `Page.createIsolatedWorld`) rather than through
 * Playwright's selector/evaluate machinery.
 *
 * The isolated world resolves elements with plain DOM APIs (`document.querySelector`
 * etc.), so this module reimplements the subset of Playwright's selector grammar
 * the humanize layer commonly receives:
 *
 *   - plain CSS / `css=` — including the `:has-text("...")` pseudo
 *   - `text=` engine (quoted = exact, unquoted = case-insensitive substring)
 *   - `xpath=` / leading `//`
 *   - a trailing `>> nth=N` (what `.first()` / `.nth(k)` / `.last()` append)
 *
 * Anything richer (`>>` chaining, `internal:*` engines from `getByRole`/`getByText`,
 * `:visible`, `:nth-match`, layout pseudos, …) returns `unsupported` so the caller
 * keeps using the regular Playwright read for that call. Correctness wins on tie:
 * a mis-resolved element yields wrong coordinates, so uncertain grammar always
 * defers to Playwright rather than guessing.
 *
 * Mirror of the Python wrapper's `cloakbrowser/human/stealth_dom.py`; the resolver
 * JavaScript string is identical across wrappers.
 */

export const OK = 'ok';
export const NOT_FOUND = 'not_found';
export const UNSUPPORTED = 'unsupported';

export interface StealthWorld {
  evaluate(expression: string): Promise<any>;
}

/** The isolated-world evaluator attached to a Page (or null when absent). */
export function getWorld(pageOrFrame: unknown): StealthWorld | null {
  const w = (pageOrFrame as any)?._stealth;
  return w ?? null;
}

// Defines `__resolve(sel)` returning the matched Element, `null` (no match), or
// the string 'UNSUPPORTED' (grammar not reimplemented). `__SEL` is inlined below.
const RESOLVER_BODY = `
const __UNS = 'UNSUPPORTED';
function __normWS(s){ return (s || '').replace(/\\s+/g, ' ').trim(); }
function __byXPath(xp){
  try {
    const r = document.evaluate(xp, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
    const out = [];
    for (let i = 0; i < r.snapshotLength; i++) { out.push(r.snapshotItem(i)); }
    return out;
  } catch (e) { return __UNS; }
}
function __matchText(el, needle, exact){
  const t = __normWS(el.textContent);
  if (exact) return t === needle;
  return t.toLowerCase().includes(String(needle).toLowerCase());
}
function __byText(arg){
  arg = arg.trim();
  let exact = false, needle = arg;
  const q = arg.charAt(0);
  if ((q === '"' || q === "'") && arg.charAt(arg.length - 1) === q) { exact = true; needle = arg.slice(1, -1); }
  needle = __normWS(needle);
  const matches = [];
  const all = document.querySelectorAll('*');
  for (const el of all) { if (__matchText(el, needle, exact)) matches.push(el); }
  return matches.filter(el => !matches.some(o => o !== el && el.contains(o)));
}
function __extractHasText(css){
  if (/:has-text\\(\\s*[^'"]/.test(css)) return __UNS;
  const texts = [];
  const out = css.replace(/:has-text\\(\\s*(['"])([\\s\\S]*?)\\1\\s*\\)/g, function(w, q, inner){ texts.push(__normWS(inner)); return ''; });
  if (out.indexOf(':has-text') !== -1) return __UNS;
  return { css: out.trim() || '*', texts: texts };
}
function __resolve(sel){
  sel = sel.trim();
  let nth = 0, hasNth = false;
  const m = sel.match(/^([\\s\\S]*?)\\s*>>\\s*nth=(-?\\d+)\\s*$/);
  if (m) { sel = m[1].trim(); nth = parseInt(m[2], 10); hasNth = true; }
  if (sel.indexOf('>>') !== -1) return __UNS;
  if (sel.indexOf('internal:') !== -1) return __UNS;
  let list;
  if (sel.indexOf('xpath=') === 0) { list = __byXPath(sel.slice(6)); }
  else if (sel.indexOf('//') === 0 || sel.indexOf('(//') === 0 || sel.indexOf('..') === 0) { list = __byXPath(sel); }
  else if (sel.indexOf('text=') === 0) { list = __byText(sel.slice(5)); }
  else {
    let css = (sel.indexOf('css=') === 0) ? sel.slice(4) : sel;
    const ht = __extractHasText(css);
    if (ht === __UNS) return __UNS;
    try { list = Array.prototype.slice.call(document.querySelectorAll(ht.css)); }
    catch (e) { return __UNS; }
    if (ht.texts.length) {
      list = list.filter(function(el){
        const t = __normWS(el.textContent).toLowerCase();
        return ht.texts.every(function(x){ return t.includes(x.toLowerCase()); });
      });
    }
  }
  if (list === __UNS) return __UNS;
  if (!list || !list.length) return null;
  let idx = hasNth ? (nth < 0 ? list.length + nth : nth) : 0;
  if (idx < 0 || idx >= list.length) return null;
  return list[idx];
}
`;

const BOX_OP = `
const __el = __resolve(__SEL);
if (__el === 'UNSUPPORTED') return { r: 'unsupported' };
if (!__el) return { r: 'not_found' };
const __rc = __el.getBoundingClientRect();
if (__rc.width === 0 && __rc.height === 0 && __rc.x === 0 && __rc.y === 0) return { r: 'not_found' };
return { r: 'ok', box: { x: __rc.x, y: __rc.y, width: __rc.width, height: __rc.height } };
`;

const ACTIONABLE_OP = `
const __el = __resolve(__SEL);
if (__el === 'UNSUPPORTED') return { r: 'unsupported' };
if (!__el) return { r: 'not_found' };
const __st = getComputedStyle(__el);
const __rc = __el.getBoundingClientRect();
const __visible = __st.visibility !== 'hidden' && __st.display !== 'none' && (__rc.width > 0 || __rc.height > 0);
const __tag = __el.tagName.toLowerCase();
const __enabled = !(__el.disabled === true || __el.getAttribute('aria-disabled') === 'true');
const __editable = __enabled && !__el.readOnly &&
  (__tag === 'input' || __tag === 'textarea' || __tag === 'select' || __el.isContentEditable === true);
return { r: 'ok', visible: __visible, enabled: __enabled, editable: __editable };
`;

/** Live window dimensions, read in the isolated world (no_viewport headed mode). */
export const VIEWPORT_JS = '(() => ({ width: window.innerWidth, height: window.innerHeight }))()';

function wrap(selector: string, op: string): string {
  return `(() => {\nconst __SEL = ${JSON.stringify(selector)};\n${RESOLVER_BODY}\n${op}\n})()`;
}

/** JS reading the element's bounding box (getBoundingClientRect, viewport-space). */
export function buildBoxJs(selector: string): string {
  return wrap(selector, BOX_OP);
}

/** JS reading visible/enabled/editable for the element. */
export function buildActionableJs(selector: string): string {
  return wrap(selector, ACTIONABLE_OP);
}

/**
 * JS hit-testing elementFromPoint(x, y) against the resolved element. `x`/`y` are
 * viewport coordinates (same space as getBoundingClientRect and the CDP mouse), so
 * no iframe offset is needed — the isolated world runs in the main frame's document.
 */
export function buildPointerJs(selector: string, x: number, y: number): string {
  const op = `
const __el = __resolve(__SEL);
if (__el === 'UNSUPPORTED') return { r: 'unsupported' };
if (!__el) return { r: 'not_found' };
const __t = document.elementFromPoint(${Number(x)}, ${Number(y)});
if (!__t) return { r: 'ok', hit: false, covering: 'none' };
let __n = __t;
while (__n) { if (__n === __el) return { r: 'ok', hit: true }; __n = __n.parentNode; }
if (__el.contains(__t)) return { r: 'ok', hit: true };
return { r: 'ok', hit: false, covering: __t.tagName || 'unknown' };
`;
  return wrap(selector, op);
}

export interface ParsedResult {
  status: typeof OK | typeof NOT_FOUND | typeof UNSUPPORTED;
  data?: any;
}

/**
 * Normalize an isolated-world evaluate() result into { status, data }.
 *
 * `StealthEval.evaluate` returns `undefined` on any CDP error / JS exception, so a
 * non-object result is treated as `unsupported` (fall back to Playwright) — never
 * as `not_found` (which would suppress a real element).
 */
export function parseResult(raw: any): ParsedResult {
  if (raw === null || raw === undefined || typeof raw !== 'object' || Array.isArray(raw)) {
    return { status: UNSUPPORTED };
  }
  if (raw.r === OK) return { status: OK, data: raw };
  if (raw.r === NOT_FOUND) return { status: NOT_FOUND };
  return { status: UNSUPPORTED };
}

/**
 * Evaluate `expression` in the world and parse the result. Any throw from the
 * world (e.g. the CDP session/context can't be created) is treated as
 * `unsupported` so the caller falls back to the regular Playwright read rather
 * than propagating the error out of the humanized action.
 */
export async function evalParsed(world: StealthWorld, expression: string): Promise<ParsedResult> {
  try {
    return parseResult(await world.evaluate(expression));
  } catch {
    return { status: UNSUPPORTED };
  }
}
