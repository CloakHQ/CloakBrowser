"""Isolated-world DOM reads for the humanize layer.

The pre-click helpers (``ensure_actionable``, ``scroll_to_element`` geometry,
``check_pointer_events``) read element state and geometry. This module performs
those reads inside the CDP isolated execution context (``page._stealth_world``,
created via ``Page.createIsolatedWorld``) rather than through Playwright's
selector/evaluate machinery.

The isolated world resolves elements with plain DOM APIs (``document.querySelector``
etc.), so this module reimplements the subset of Playwright's selector grammar the
humanize layer commonly receives:

  * plain CSS / ``css=`` — including the ``:has-text("...")`` pseudo
  * ``text=`` engine (quoted = exact, unquoted = case-insensitive substring)
  * ``xpath=`` / leading ``//``
  * ``internal:testid=`` / ``internal:attr=`` (``get_by_test_id``,
    ``get_by_placeholder``, ``get_by_alt_text``, ``get_by_title``)
  * ``internal:text=`` / ``internal:label=`` (``get_by_text``, ``get_by_label``)
  * a trailing ``>> nth=N`` (what ``.first`` / ``.nth(k)`` / ``.last`` append)

Anything richer returns ``unsupported`` and the caller raises a typed error:
``>>`` chaining (so ``.filter()``, ``.and_()``, ``.or_()`` and chained locators),
``internal:role=`` (``get_by_role`` — a faithful port needs Playwright's whole
accessible-name algorithm), ``internal:has*``, ``internal:control=``
(``frame_locator``), ``:visible``, ``:nth-match``, and layout pseudos.
Correctness and stealth win on ties: uncertain grammar never falls back to
Playwright DOM reads, because a mis-resolved element means clicking the wrong
coordinates.

The JS builders and :func:`parse_result` are pure and shared by the sync and
async call sites; only the ``world.evaluate`` await differs.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Tuple

# Versioned protocol returned by the isolated-world DOM helper.
PROTOCOL_VERSION = 2

# Status returned to callers.
OK = "ok"
NOT_FOUND = "not_found"
UNSUPPORTED = "unsupported"
STALE = "stale"
EVALUATION_FAILED = "evaluation_failed"


class StealthDomError(RuntimeError):
    """Base for isolated-world DOM helper failures."""


class UnsupportedHumanizeSelectorError(StealthDomError):
    """Raised for selector grammar the isolated-world resolver cannot resolve.

    The humanize layer resolves selectors inside the isolated world so page
    scripts cannot observe the read. Grammar it cannot resolve is refused rather
    than handed back to Playwright, whose locator predicates run in the page's
    main world and are observable.
    """

    def __init__(self, selector: str):
        super().__init__(
            f"Humanized selector {selector!r} is not supported by the isolated-world "
            f"resolver. Supported: CSS, text=, xpath=, get_by_test_id, "
            f"get_by_placeholder, get_by_alt_text, get_by_title, get_by_text, "
            f"get_by_label, and a trailing .first/.nth()/.last. Not supported: "
            f"get_by_role, chained locators (a >> b, .filter(), .and_(), .or_()), "
            f"frame_locator, :visible and :nth-match. Use a CSS or text= selector "
            f"for this action, or humanize=False to fall back to Playwright."
        )


class StealthWorldUnavailableError(StealthDomError):
    def __init__(self):
        super().__init__("Humanized DOM read requires an active isolated world")


class StealthEvaluationError(StealthDomError):
    def __init__(self, selector: str):
        super().__init__(f"Isolated-world DOM evaluation failed for {selector!r}")

# ---------------------------------------------------------------------------
# JS: selector resolution inside the isolated world
# ---------------------------------------------------------------------------
# Defines ``__resolve(sel)`` returning the matched Element, ``null`` (no match),
# or the string ``'UNSUPPORTED'`` (grammar we don't reimplement). ``__SEL`` is
# inlined by the Python builders below.

_RESOLVER_BODY = r"""
const __UNS = 'UNSUPPORTED';
const __V = 2;
const __STATE_KEY = '__cloakHumanDomV1';
function __state(){
  let s = globalThis[__STATE_KEY];
  if (!s) {
    // Element ids restart at 1 in every new world, and the world is recreated on
    // navigation (#507), so an id alone can name a different element after a nav.
    // The generation makes that cross-world reuse detectable as 'stale'.
    // 11 bits of wall clock + 20 bits of randomness. The maximum is exactly
    // Int32.MaxValue, because the .NET wrapper carries the value as an Int32.
    s = { ids: new WeakMap(), nextId: 1,
          gen: (Date.now() & 2047) * 1048576 + Math.floor(Math.random() * 1048576) };
    Object.defineProperty(globalThis, __STATE_KEY, { value: s, configurable: false, enumerable: false });
  }
  return s;
}
function __gen(){ return __state().gen; }
function __targetId(el){
  const s = __state();
  let id = s.ids.get(el);
  if (!id) { id = s.nextId++; s.ids.set(el, id); }
  return id;
}
function __visibleTextNode(node){
  const range = node.ownerDocument.createRange();
  range.selectNode(node);
  const rect = range.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}
function __isVisible(el){
  const style = getComputedStyle(el);
  if (!style) return true;
  if (style.display === 'contents') {
    for (let child = el.firstChild; child; child = child.nextSibling) {
      if (child.nodeType === 1 && __isVisible(child)) return true;
      if (child.nodeType === 3 && style.visibility === 'visible' && __visibleTextNode(child)) return true;
    }
    return false;
  }
  try {
    if (typeof el.checkVisibility === 'function' && !el.checkVisibility()) return false;
  } catch (e) {
    // Older engines fall through to computed style + geometry.
  }
  if (style.visibility !== 'visible') return false;
  const rect = el.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}
function __visBox(el){
  const style = getComputedStyle(el);
  if (style && style.display === 'contents') {
    let x1 = Infinity, y1 = Infinity, x2 = -Infinity, y2 = -Infinity;
    let found = false;
    for (let child = el.firstChild; child; child = child.nextSibling) {
      let box = null;
      if (child.nodeType === 1 && __isVisible(child)) {
        box = __visBox(child);
      } else if (child.nodeType === 3 && style.visibility === 'visible' &&
                 __normWS(child.nodeValue)) {
        const range = child.ownerDocument.createRange();
        range.selectNode(child);
        const rect = range.getBoundingClientRect();
        if (rect.width > 0 && rect.height > 0) {
          box = { x: rect.x, y: rect.y, width: rect.width, height: rect.height };
        }
      }
      if (!box) continue;
      found = true;
      x1 = Math.min(x1, box.x);
      y1 = Math.min(y1, box.y);
      x2 = Math.max(x2, box.x + box.width);
      y2 = Math.max(y2, box.y + box.height);
    }
    return found ? { x: x1, y: y1, width: x2 - x1, height: y2 - y1 } : null;
  }
  const rect = el.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0
    ? { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
    : null;
}
const __ARIA_DISABLED_ROLES = new Set([
  'application','button','composite','gridcell','group','input','link','menuitem',
  'scrollbar','separator','tab','checkbox','columnheader','combobox','grid','listbox',
  'menu','menubar','menuitemcheckbox','menuitemradio','option','radio','radiogroup',
  'row','rowheader','searchbox','select','slider','spinbutton','switch','tablist',
  'textbox','toolbar','tree','treegrid','treeitem'
]);
const __ARIA_READONLY_ROLES = new Set([
  'checkbox','combobox','grid','gridcell','listbox','radiogroup','slider','spinbutton',
  'textbox','columnheader','rowheader','searchbox','switch','treegrid'
]);
function __role(el){
  const explicit = (el.getAttribute('role') || '').trim().split(/\s+/)[0];
  if (explicit) return explicit;
  const tag = el.tagName.toLowerCase();
  if (tag === 'button') return 'button';
  if (tag === 'textarea') return 'textbox';
  if (tag === 'select') return el.multiple ? 'listbox' : 'combobox';
  if (tag === 'option') return 'option';
  if ((tag === 'a' || tag === 'area') && el.hasAttribute('href')) return 'link';
  if (tag === 'input') {
    const type = (el.type || 'text').toLowerCase();
    if (['button','submit','reset','image'].includes(type)) return 'button';
    if (type === 'checkbox') return 'checkbox';
    if (type === 'radio') return 'radio';
    if (type === 'range') return 'slider';
    if (type === 'number') return 'spinbutton';
    if (type === 'search') return 'searchbox';
    if (!['hidden','file','color'].includes(type)) return 'textbox';
  }
  return '';
}
function __nativeDisabled(el){
  const tag = el.tagName.toLowerCase();
  if (!['button','input','select','textarea','option','optgroup'].includes(tag)) return false;
  if (el.hasAttribute('disabled')) return true;
  if (tag === 'option' && el.closest('optgroup[disabled]')) return true;
  const fieldset = el.closest('fieldset[disabled]');
  if (!fieldset) return false;
  const legend = fieldset.querySelector(':scope > legend');
  return !legend || !legend.contains(el);
}
function __ariaDisabled(el){
  if (!__ARIA_DISABLED_ROLES.has(__role(el))) return false;
  let current = el;
  while (current) {
    const value = (current.getAttribute('aria-disabled') || '').toLowerCase();
    if (value === 'true') return true;
    if (value === 'false') return false;
    current = __composedParent(current);
  }
  return false;
}
function __isEnabled(el){ return !(__nativeDisabled(el) || __ariaDisabled(el)); }
function __readonly(el){
  const tag = el.tagName.toLowerCase();
  if (tag === 'input' || tag === 'textarea' || tag === 'select') return el.hasAttribute('readonly');
  if (__ARIA_READONLY_ROLES.has(__role(el))) return el.getAttribute('aria-readonly') === 'true';
  if (el.isContentEditable) return false;
  return null;
}
function __isEditable(el, enabled){
  const readonly = __readonly(el);
  return readonly === null ? false : enabled && !readonly;
}
function __normWS(s){
  return (s || '').replace(/[\u200b\u00ad]/g, '').replace(/\s+/g, ' ').trim();
}
function __skipText(el){
  const tag = el && el.tagName ? el.tagName.toLowerCase() : '';
  return tag === 'script' || tag === 'style' || tag === 'noscript' ||
    (document.head && document.head.contains(el));
}
function __elementText(el, cache){
  if (cache.has(el)) return cache.get(el);
  let out = { full: '', normalized: '', immediate: [] };
  cache.set(el, out);
  if (__skipText(el)) return out;
  const tag = el.tagName ? el.tagName.toLowerCase() : '';
  if (tag === 'input' && ['button', 'submit', 'reset'].includes((el.type || '').toLowerCase())) {
    const value = el.value || '';
    out = { full: value, normalized: __normWS(value), immediate: [value] };
    cache.set(el, out);
    return out;
  }
  if (!el.childNodes) {
    const value = el.textContent || '';
    out = { full: value, normalized: __normWS(value), immediate: value ? [value] : [] };
    cache.set(el, out);
    return out;
  }
  let full = '', immediate = '';
  const fragments = [];
  for (const child of el.childNodes) {
    if (child.nodeType === 3) {
      const value = child.nodeValue || '';
      full += value;
      immediate += value;
    } else if (child.nodeType === 8) {
      continue;
    } else {
      if (immediate) { fragments.push(immediate); immediate = ''; }
      if (child.nodeType === 1) full += __elementText(child, cache).full;
    }
  }
  if (immediate) fragments.push(immediate);
  if (el.shadowRoot) full += __elementText(el.shadowRoot, cache).full;
  out = { full: full, normalized: __normWS(full), immediate: fragments };
  cache.set(el, out);
  return out;
}
function __byXPath(xp){
  try {
    const r = document.evaluate(xp, document, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
    const out = [];
    for (let i = 0; i < r.snapshotLength; i++) { out.push(r.snapshotItem(i)); }
    return out;
  } catch (e) { return __UNS; }
}
function __parseTextMatcher(arg){
  arg = arg.trim();
  if (arg.charAt(0) === '/') {
    let end = -1, escaped = false;
    for (let i = 1; i < arg.length; i++) {
      const ch = arg.charAt(i);
      if (!escaped && ch === '/') end = i;
      escaped = !escaped && ch === '\\';
      if (ch !== '\\') escaped = false;
    }
    if (end > 0) {
      try { return { kind: 'regex', regex: new RegExp(arg.slice(1, end), arg.slice(end + 1)) }; }
      catch (e) { return __UNS; }
    }
  }
  const q = arg.charAt(0);
  if ((q === '"' || q === "'") && arg.charAt(arg.length - 1) === q) {
    let value;
    try {
      value = q === '"' ? JSON.parse(arg) : arg.slice(1, -1).replace(/\\(['"\\])/g, '$1');
    } catch (e) { return __UNS; }
    return { kind: 'exact', value: __normWS(value) };
  }
  return { kind: 'lax', value: __normWS(arg).toLowerCase() };
}
function __matchTextValue(text, matcher){
  if (matcher.kind === 'regex') { matcher.regex.lastIndex = 0; return matcher.regex.test(text.full); }
  // The public engine's exact rule compares immediate text-node runs, unlike
  // internal:text which compares the full normalized subtree text.
  if (matcher.kind === 'exact') return text.immediate.some(x => __normWS(x) === matcher.value);
  return text.normalized.toLowerCase().includes(matcher.value);
}
function __matchText(el, matcher, cache){
  return __matchTextValue(__elementText(el, cache), matcher);
}
function __publicTextMatches(el, matcher, cache){
  // Playwright's elementMatchesText for the public text= engine.
  if (__skipText(el)) return 'none';
  if (!__matchText(el, matcher, cache)) return 'none';
  for (const child of el.children || []) {
    if (__matchText(child, matcher, cache)) return 'selfAndChildren';
  }
  // A host whose shadow content also matches is not the smallest match. This
  // cannot be expressed with contains(), which does not pierce shadow roots.
  if (el.shadowRoot && __matchTextValue(__elementText(el.shadowRoot, cache), matcher))
    return 'selfAndChildren';
  return 'self';
}
function __byText(arg){
  const matcher = __parseTextMatcher(arg);
  if (matcher === __UNS) return __UNS;
  const out = [], cache = new Map();
  let lastMiss = null;
  for (const el of __allElements()) {
    // Nothing under a non-matching ancestor can match in lax mode.
    if (matcher.kind === 'lax' && lastMiss && lastMiss.contains(el)) continue;
    const m = __publicTextMatches(el, matcher, cache);
    if (m === 'none') lastMiss = el;
    // The public engine also keeps an ancestor when the match is exact.
    if (m === 'self' || (m === 'selfAndChildren' && matcher.kind === 'exact')) out.push(el);
  }
  return out;
}
function __attrUnquote(s, i){
  // parseAttributeSelector.readQuotedString: a backslash is dropped and the next
  // character taken verbatim -- NOT JSON escapes, so "a\\nb" decodes to 'anb'.
  const quote = s.charAt(i);
  if (quote !== '"' && quote !== "'") return __UNS;
  let out = '';
  i++;
  while (i < s.length && s.charAt(i) !== quote) {
    if (s.charAt(i) === '\\') {
      i++;
      if (i >= s.length) return __UNS;
    }
    out += s.charAt(i++);
  }
  if (s.charAt(i) !== quote) return __UNS;
  return { value: out, end: i + 1 };
}
function __parseAttrBody(body){
  // [name="value"i] | [name="value"s] | [name=/re/flags]
  body = body.trim();
  if (body.charAt(0) !== '[' || body.charAt(body.length - 1) !== ']') return __UNS;
  const inner = body.slice(1, -1);
  const eq = inner.indexOf('=');
  if (eq <= 0) return __UNS;
  let name = inner.slice(0, eq).trim();
  if (name.charAt(0) === '"' || name.charAt(0) === "'") {
    const un = __attrUnquote(name, 0);
    if (un === __UNS || un.end !== name.length) return __UNS;
    name = un.value;
  }
  // isCSSNameChar, plus ',' for the comma-joined test-id name list. Also rejects
  // the *= ^= $= |= ~= operators, whose extra character lands in the name.
  if (!/^[\w\u0080-\uFFFF,-]+$/.test(name)) return __UNS;
  const rest = inner.slice(eq + 1);
  let j = 0;
  while (j < rest.length && /\s/.test(rest.charAt(j))) j++;
  if (rest.charAt(j) === '/') {
    const end = rest.lastIndexOf('/');
    if (end <= j) return __UNS;
    const flags = rest.slice(end + 1).trim();
    if (!/^[dgimsuvy]*$/.test(flags)) return __UNS;
    try { return { name: name, regex: new RegExp(rest.slice(j + 1, end), flags), value: null, caseSensitive: true }; }
    catch (e) { return __UNS; }
  }
  const un = __attrUnquote(rest, j);
  if (un === __UNS) return __UNS;
  let k = un.end, caseSensitive = true;
  const flag = rest.charAt(k);
  if (flag === 'i' || flag === 'I') { caseSensitive = false; k++; }
  else if (flag === 's' || flag === 'S') { caseSensitive = true; k++; }
  while (k < rest.length && /\s/.test(rest.charAt(k))) k++;
  if (k !== rest.length) return __UNS;
  return { name: name, regex: null, value: un.value, caseSensitive: caseSensitive };
}
function __byAttr(body){
  // Serves internal:attr (placeholder/alt/title) AND internal:testid -- the
  // attribute name comes from the selector. The 'i' flag means case-insensitive
  // SUBSTRING, and the RAW attribute value is compared: no trim, no whitespace
  // normalization. get_by_test_id always emits 's', so it is strict equality.
  const parsed = __parseAttrBody(body);
  if (parsed === __UNS) return __UNS;
  const names = parsed.name.split(',');
  const lower = (parsed.regex || parsed.caseSensitive) ? null : parsed.value.toLowerCase();
  const out = [];
  try {
    for (const el of __allElements()) {
      if (!el.getAttribute) continue;
      for (const name of names) {
        const actual = el.getAttribute(name);
        if (actual === null || actual === undefined) continue;
        let hit;
        if (parsed.regex) { parsed.regex.lastIndex = 0; hit = !!String(actual).match(parsed.regex); }
        else if (parsed.caseSensitive) hit = actual === parsed.value;
        else hit = String(actual).toLowerCase().indexOf(lower) !== -1;
        if (hit) { out.push(el); break; }
      }
    }
  } catch (e) { return __UNS; }
  return out;
}
function __parseInternalTextMatcher(arg){
  // createTextMatcher(selector, internal=true). Playwright does not trim here.
  if (arg.charAt(0) === '/' && arg.lastIndexOf('/') > 0) {
    const end = arg.lastIndexOf('/');
    try { return { kind: 'regex', regex: new RegExp(arg.slice(1, end), arg.slice(end + 1)) }; }
    catch (e) { return __UNS; }
  }
  if (arg.length > 1 && arg.charAt(0) === '"') {
    let body = null, strict = false;
    const last = arg.charAt(arg.length - 1);
    if (last === '"') { body = arg; strict = true; }
    else if (arg.charAt(arg.length - 2) === '"' && (last === 's' || last === 'i')) {
      body = arg.slice(0, -1); strict = last === 's';
    } else return __UNS;
    let value;
    try { value = JSON.parse(body); } catch (e) { return __UNS; }
    if (typeof value !== 'string') return __UNS;
    const norm = __normWS(value);
    return strict ? { kind: 'strict', value: norm } : { kind: 'lax', value: norm.toLowerCase() };
  }
  // A single-quoted body reaches unquote=JSON.parse in Playwright and throws.
  if (arg.length > 1 && arg.charAt(0) === "'" && arg.charAt(arg.length - 1) === "'") return __UNS;
  return { kind: 'lax', value: __normWS(arg).toLowerCase() };
}
function __matchInternalText(text, matcher){
  if (matcher.kind === 'regex') { matcher.regex.lastIndex = 0; return matcher.regex.test(text.full); }
  // strict compares the FULL normalized subtree text. The public text= engine
  // compares immediate fragments instead (__matchText) -- genuinely different.
  if (matcher.kind === 'strict') return text.normalized === matcher.value;
  return text.normalized.toLowerCase().indexOf(matcher.value) !== -1;
}
function __internalTextMatches(el, matcher, cache){
  if (__skipText(el)) return 'none';
  if (!__matchInternalText(__elementText(el, cache), matcher)) return 'none';
  // Direct children only, plus the shadow-root probe -- NOT contains() over the
  // match set, which would drop an outer element matched only via a grandchild.
  for (const child of el.children || []) {
    if (__matchInternalText(__elementText(child, cache), matcher)) return 'selfAndChildren';
  }
  if (el.shadowRoot && __matchInternalText(__elementText(el.shadowRoot, cache), matcher)) return 'selfAndChildren';
  return 'self';
}
function __byInternalText(arg){
  const matcher = __parseInternalTextMatcher(arg);
  if (matcher === __UNS) return __UNS;
  const cache = new Map(), out = [];
  let lastMiss = null;
  for (const el of __allElements()) {
    // lastDidNotMatchSelf: in lax mode nothing under a non-matching ancestor matches.
    if (matcher.kind === 'lax' && lastMiss && lastMiss.contains(el)) continue;
    const m = __internalTextMatches(el, matcher, cache);
    if (m === 'none') lastMiss = el;
    if (m === 'self') out.push(el);
  }
  return out;
}
function __idRefRoot(el){
  const root = el.getRootNode ? el.getRootNode() : null;
  return (root && typeof root.getElementById === 'function') ? root : document;
}
function __labelledByElements(el){
  const ref = el.getAttribute ? el.getAttribute('aria-labelledby') : null;
  if (ref === null || ref === undefined) return null;
  const root = __idRefRoot(el), out = [];
  for (const id of ref.split(/\s+/)) {
    if (!id) continue;
    const target = root.getElementById(id);
    if (target && out.indexOf(target) === -1) out.push(target);
  }
  return out.length ? out : null;
}
function __elementLabels(el, cache){
  // First non-empty source wins: aria-labelledby, then aria-label, then .labels.
  const refs = __labelledByElements(el);
  if (refs) return refs.map(function(x){ return __elementText(x, cache); });
  const aria = el.getAttribute ? el.getAttribute('aria-label') : null;
  if (aria !== null && aria !== undefined && aria.trim())
    return [{ full: aria, normalized: __normWS(aria), immediate: [aria] }];
  const tag = el.tagName ? el.tagName.toUpperCase() : '';
  const nonHiddenInput = tag === 'INPUT' && String(el.type || '').toLowerCase() !== 'hidden';
  if (nonHiddenInput || ['BUTTON','METER','OUTPUT','PROGRESS','SELECT','TEXTAREA'].indexOf(tag) !== -1) {
    // Native .labels already resolves both for/id and a wrapping <label>.
    const labels = el.labels;
    if (labels) return Array.prototype.slice.call(labels).map(function(x){ return __elementText(x, cache); });
  }
  return [];
}
function __byLabel(arg){
  const matcher = __parseInternalTextMatcher(arg);
  if (matcher === __UNS) return __UNS;
  const cache = new Map(), out = [];
  try {
    for (const el of __allElements()) {
      const labels = __elementLabels(el, cache);
      for (const label of labels) {
        if (__matchInternalText(label, matcher)) { out.push(el); break; }
      }
    }
  } catch (e) { return __UNS; }
  return out;
}
function __allElements(){
  if (!document.children && document.querySelectorAll)
    return Array.prototype.slice.call(document.querySelectorAll('*'));
  const out = [];
  function visitRoot(root){
    const light = [];
    function collectLight(parent){
      for (const el of parent.children || []) {
        out.push(el);
        light.push(el);
        collectLight(el);
      }
    }
    collectLight(root);
    for (const host of light) {
      if (host.shadowRoot) visitRoot(host.shadowRoot);
    }
  }
  visitRoot(document);
  return out;
}
function __readQuoted(value){
  value = value.trim();
  const q = value.charAt(0);
  if ((q !== '"' && q !== "'") || value.charAt(value.length - 1) !== q) return __UNS;
  try {
    return q === '"' ? JSON.parse(value) : value.slice(1, -1).replace(/\\(['"\\])/g, '$1');
  } catch (e) { return __UNS; }
}
function __parseCompound(compound){
  let css = '', i = 0;
  const texts = [];
  while (i < compound.length) {
    if (compound.slice(i, i + 10) !== ':has-text(') { css += compound.charAt(i++); continue; }
    let j = i + 10, quote = '', escaped = false, depth = 1;
    for (; j < compound.length; j++) {
      const ch = compound.charAt(j);
      if (quote) {
        if (!escaped && ch === quote) quote = '';
        escaped = !escaped && ch === '\\';
        if (ch !== '\\') escaped = false;
        continue;
      }
      if (ch === '"' || ch === "'") { quote = ch; continue; }
      if (ch === '(') depth++;
      else if (ch === ')' && --depth === 0) break;
    }
    if (depth !== 0) return __UNS;
    const text = __readQuoted(compound.slice(i + 10, j));
    if (text === __UNS) return __UNS;
    texts.push(__normWS(text).toLowerCase());
    i = j + 1;
  }
  css = css.trim() || '*';
  if (css.includes(':has-text') || /:(?:text|text-is|text-matches|visible|nth-match)\b/.test(css)) return __UNS;
  return { css: css, texts: texts };
}
function __splitSelectorList(css){
  const parts = [];
  let buf = '', quote = '', escaped = false, brackets = 0, parens = 0;
  for (let i = 0; i < css.length; i++) {
    const ch = css.charAt(i);
    if (escaped) { buf += ch; escaped = false; continue; }
    if (ch === '\\') { buf += ch; escaped = true; continue; }
    if (quote) {
      buf += ch;
      if (ch === quote) quote = '';
      continue;
    }
    if (ch === '"' || ch === "'") { quote = ch; buf += ch; continue; }
    if (ch === '[') brackets++;
    else if (ch === ']') brackets--;
    else if (ch === '(') parens++;
    else if (ch === ')') parens--;
    if (ch === ',' && brackets === 0 && parens === 0) {
      if (!buf.trim()) return __UNS;
      parts.push(buf.trim()); buf = ''; continue;
    }
    buf += ch;
  }
  if (quote || brackets !== 0 || parens !== 0 || !buf.trim()) return __UNS;
  parts.push(buf.trim());
  return parts;
}
function __parseCss(css){
  const compounds = [], combinators = [];
  let buf = '', quote = '', escaped = false, brackets = 0, parens = 0;
  function pushCompound(){
    const value = buf.trim();
    if (!value) return false;
    const parsed = __parseCompound(value);
    if (parsed === __UNS) return __UNS;
    compounds.push(parsed); buf = ''; return true;
  }
  for (let i = 0; i < css.length; i++) {
    const ch = css.charAt(i);
    if (quote) {
      buf += ch;
      if (!escaped && ch === quote) quote = '';
      escaped = !escaped && ch === '\\';
      if (ch !== '\\') escaped = false;
      continue;
    }
    if (ch === '"' || ch === "'") { quote = ch; buf += ch; continue; }
    if (ch === '[') { brackets++; buf += ch; continue; }
    if (ch === ']') { brackets--; buf += ch; continue; }
    if (ch === '(') { parens++; buf += ch; continue; }
    if (ch === ')') { parens--; buf += ch; continue; }
    if (brackets === 0 && parens === 0 && (ch === '>' || ch === '+' || ch === '~')) {
      const pushed = pushCompound();
      if (pushed === __UNS || !pushed) return __UNS;
      combinators.push(ch);
      while (i + 1 < css.length && /\s/.test(css.charAt(i + 1))) i++;
      continue;
    }
    if (brackets === 0 && parens === 0 && /\s/.test(ch)) {
      let j = i;
      while (j + 1 < css.length && /\s/.test(css.charAt(j + 1))) j++;
      const next = css.charAt(j + 1);
      if (buf.trim() && next !== '>' && next !== '+' && next !== '~') {
        const pushed = pushCompound();
        if (pushed === __UNS) return __UNS;
        combinators.push(' ');
      }
      i = j;
      continue;
    }
    buf += ch;
  }
  const pushed = pushCompound();
  if (pushed === __UNS) return __UNS;
  if (!compounds.length || combinators.length !== compounds.length - 1) return __UNS;
  return { compounds: compounds, combinators: combinators };
}
function __composedParent(el){
  if (el.parentElement) return el.parentElement;
  const root = el.getRootNode ? el.getRootNode() : null;
  return root && root.host ? root.host : null;
}
function __matchesCompound(el, compound, cache){
  try { if (typeof el.matches === 'function' && !el.matches(compound.css)) return false; }
  catch (e) { return false; }
  if (!compound.texts.length) return true;
  const text = __elementText(el, cache).normalized.toLowerCase();
  return compound.texts.every(x => text.includes(x));
}
function __matchesCss(el, parsed, cache){
  let idx = parsed.compounds.length - 1, current = el;
  if (!__matchesCompound(current, parsed.compounds[idx], cache)) return false;
  while (idx > 0) {
    const comb = parsed.combinators[idx - 1];
    idx--;
    if (comb === '>') {
      current = __composedParent(current);
      if (!current || !__matchesCompound(current, parsed.compounds[idx], cache)) return false;
    } else if (comb === ' ') {
      let parent = __composedParent(current), found = null;
      while (parent) {
        if (__matchesCompound(parent, parsed.compounds[idx], cache)) { found = parent; break; }
        parent = __composedParent(parent);
      }
      if (!found) return false;
      current = found;
    } else {
      let sibling = current.previousElementSibling;
      if (comb === '+') {
        if (!sibling || !__matchesCompound(sibling, parsed.compounds[idx], cache)) return false;
        current = sibling;
      } else {
        let found = null;
        while (sibling) {
          if (__matchesCompound(sibling, parsed.compounds[idx], cache)) { found = sibling; break; }
          sibling = sibling.previousElementSibling;
        }
        if (!found) return false;
        current = found;
      }
    }
  }
  return true;
}
function __byCss(css){
  if (css.includes(':scope')) return __UNS;
  const branches = __splitSelectorList(css);
  if (branches === __UNS) return __UNS;
  const parsed = branches.map(__parseCss);
  if (parsed.some(x => x === __UNS)) return __UNS;
  const cache = new Map();
  return __allElements().filter(
    el => parsed.some(branch => __matchesCss(el, branch, cache))
  );
}
function __deepElementFromPoint(x, y){
  let target = document.elementFromPoint(x, y);
  while (target && target.shadowRoot &&
         typeof target.shadowRoot.elementFromPoint === 'function') {
    const inner = target.shadowRoot.elementFromPoint(x, y);
    if (!inner || inner === target) break;
    target = inner;
  }
  return target;
}
function __deepActiveElement(){
  let active = document.activeElement;
  while (active && active.shadowRoot && active.shadowRoot.activeElement) {
    active = active.shadowRoot.activeElement;
  }
  return active;
}
function __resolve(sel){
  sel = sel.trim();
  // Trailing ">> nth=N" (.first => nth=0, .last => nth=-1, .nth(k) => nth=k).
  let nth = 0, hasNth = false;
  const m = sel.match(/^([\s\S]*?)\s*>>\s*nth=(-?\d+)\s*$/);
  if (m) { sel = m[1].trim(); nth = parseInt(m[2], 10); hasNth = true; }
  if (sel.indexOf('>>') !== -1) return __UNS;        // chaining we don't reimplement
  let list;
  // get_by_* engines we reimplement. Anything else under internal: (role, has,
  // has-text, and, or, chain, control, describe) stays unsupported.
  if (sel.indexOf('internal:testid=') === 0) { list = __byAttr(sel.slice(16)); }
  else if (sel.indexOf('internal:attr=') === 0) { list = __byAttr(sel.slice(14)); }
  else if (sel.indexOf('internal:text=') === 0) { list = __byInternalText(sel.slice(14)); }
  else if (sel.indexOf('internal:label=') === 0) { list = __byLabel(sel.slice(15)); }
  else if (sel.indexOf('internal:') !== -1) return __UNS;
  else if (sel.indexOf('xpath=') === 0) { list = __byXPath(sel.slice(6)); }
  else if (sel.indexOf('//') === 0 || sel.indexOf('(//') === 0 || sel.indexOf('..') === 0) { list = __byXPath(sel); }
  else if (sel.indexOf('text=') === 0) { list = __byText(sel.slice(5)); }
  else {
    const css = (sel.indexOf('css=') === 0) ? sel.slice(4) : sel;
    list = __byCss(css);
  }
  if (list === __UNS) return __UNS;
  if (!list || !list.length) return null;
  let idx = hasNth ? (nth < 0 ? list.length + nth : nth) : 0;
  if (idx < 0 || idx >= list.length) return null;
  return list[idx];
}
"""

# ---------------------------------------------------------------------------
# JS: per-operation reads (versioned payload; DOM semantics evolve below)
# ---------------------------------------------------------------------------

_SNAPSHOT_OP = r"""
const __el = __resolve(__SEL);
if (__el === 'UNSUPPORTED') return { v: __V, r: 'unsupported' };
if (!__el) return { v: __V, r: 'not_found' };
const __box = __visBox(__el);
const __hasBox = __box !== null;
const __tag = __el.tagName.toLowerCase();
const __enabled = __isEnabled(__el);
const __editable = __isEditable(__el, __enabled);
return {
  v: __V,
  r: 'ok',
  targetId: __targetId(__el),
  gen: __gen(),
  attached: __el.isConnected === true,
  visible: __isVisible(__el),
  enabled: __enabled,
  editable: __editable,
  isInput: __tag === 'input' || __tag === 'textarea' || __el.isContentEditable === true,
  focused: __deepActiveElement() === __el,
  checked: typeof __el.checked === 'boolean' ? __el.checked : null,
  box: __box
};
"""

_VIEWPORT_JS = "(() => ({ width: window.innerWidth, height: window.innerHeight }))()"


def _wrap(selector: str, op: str) -> str:
    """Assemble a full isolated-world expression: resolver + one op."""
    return (
        "(() => {\n"
        "const __SEL = " + json.dumps(selector) + ";\n"
        + _RESOLVER_BODY + "\n" + op + "\n})()"
    )


def build_snapshot_js(selector: str) -> str:
    """JS resolving one element into the versioned isolated-world payload."""
    return _wrap(selector, _SNAPSHOT_OP)


def build_box_js(selector: str) -> str:
    """JS reading the element's bounding box (getBoundingClientRect, viewport-space)."""
    op = _SNAPSHOT_OP.replace(
        "return {\n  v: __V,\n  r: 'ok',",
        "return {\n  v: __V,\n  r: __hasBox ? 'ok' : 'not_found',",
    )
    return _wrap(selector, op)


def build_actionable_js(selector: str) -> str:
    """JS reading visible/enabled/editable for the element."""
    return build_snapshot_js(selector)


def build_validate_js(
    selector: str, target_id: int, gen: int, x: float, y: float
) -> str:
    """Revalidate the same isolated-world element identity at a click point.

    ``gen`` pins the isolated world the ``target_id`` was minted in. The world is
    recreated on navigation and its id counter restarts at 1, so without this a
    *different* element could answer to the same id and pass the identity check.
    """
    op = (
        "const __el = __resolve(__SEL);\n"
        "if (__el === 'UNSUPPORTED') return { v: __V, r: 'unsupported' };\n"
        "if (!__el) return { v: __V, r: 'not_found' };\n"
        "const __g = __gen();\n"
        "const __id = __targetId(__el);\n"
        "if (__g !== " + repr(int(gen)) + ") return { v: __V, r: 'stale', targetId: __id, gen: __g };\n"
        "if (__id !== " + repr(int(target_id)) + ") return { v: __V, r: 'stale', targetId: __id, gen: __g };\n"
        "if (__el.isConnected !== true) return { v: __V, r: 'stale', targetId: __id, gen: __g };\n"
        "const __t = __deepElementFromPoint(" + repr(float(x)) + ", " + repr(float(y)) + ");\n"
        "let __n = __t;\n"
        "while (__n) { if (__n === __el) return { v: __V, r: 'ok', targetId: __id, gen: __g, hit: true }; __n = __composedParent(__n); }\n"
        "if (__t && __el.contains(__t)) return { v: __V, r: 'ok', targetId: __id, gen: __g, hit: true };\n"
        "return { v: __V, r: 'ok', targetId: __id, gen: __g, hit: false, covering: __t ? (__t.tagName || 'unknown') : 'none' };\n"
    )
    return _wrap(selector, op)


def build_pointer_js(selector: str, x: float, y: float) -> str:
    """JS hit-testing elementFromPoint(x, y) against the resolved element.

    ``x``/``y`` are viewport coordinates (same space as getBoundingClientRect and
    the CDP mouse), so no iframe offset is needed — the isolated world runs in the
    main frame's document.
    """
    op = (
        "const __el = __resolve(__SEL);\n"
        "if (__el === 'UNSUPPORTED') return { v: __V, r: 'unsupported' };\n"
        "if (!__el) return { v: __V, r: 'not_found' };\n"
        "const __id = __targetId(__el);\n"
        "const __t = __deepElementFromPoint(" + repr(float(x)) + ", " + repr(float(y)) + ");\n"
        "if (!__t) return { v: __V, r: 'ok', targetId: __id, gen: __gen(), hit: false, covering: 'none' };\n"
        "let __n = __t;\n"
        "while (__n) { if (__n === __el) return { v: __V, r: 'ok', targetId: __id, gen: __gen(), hit: true }; __n = __composedParent(__n); }\n"
        "if (__el.contains(__t)) return { v: __V, r: 'ok', targetId: __id, gen: __gen(), hit: true };\n"
        "return { v: __V, r: 'ok', targetId: __id, gen: __gen(), hit: false, covering: __t.tagName || 'unknown' };\n"
    )
    return _wrap(selector, op)


def parse_result(raw: Any) -> Tuple[str, Optional[dict]]:
    """Validate and normalize one versioned isolated-world payload."""
    if not isinstance(raw, dict) or raw.get("v") != PROTOCOL_VERSION:
        return (EVALUATION_FAILED, None)
    r = raw.get("r")
    if r == OK:
        if not isinstance(raw.get("targetId"), int) or not isinstance(raw.get("gen"), int):
            return (EVALUATION_FAILED, None)
        return (OK, raw)
    if r == NOT_FOUND:
        return (NOT_FOUND, None)
    if r == STALE:
        if not isinstance(raw.get("targetId"), int) or not isinstance(raw.get("gen"), int):
            return (EVALUATION_FAILED, None)
        return (STALE, raw)
    if r == UNSUPPORTED:
        return (UNSUPPORTED, None)
    return (EVALUATION_FAILED, None)


def eval_parsed(world: Any, expression: str) -> Tuple[str, Optional[dict]]:
    """Evaluate and validate a payload; evaluation errors fail explicitly."""
    try:
        return parse_result(world.evaluate(expression))
    except Exception:
        return (EVALUATION_FAILED, None)


async def async_eval_parsed(world: Any, expression: str) -> Tuple[str, Optional[dict]]:
    """Async variant of :func:`eval_parsed`."""
    try:
        return parse_result(await world.evaluate(expression))
    except Exception:
        return (EVALUATION_FAILED, None)
