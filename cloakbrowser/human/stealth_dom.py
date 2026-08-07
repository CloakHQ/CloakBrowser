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
  * a trailing ``>> nth=N`` (what ``.first`` / ``.nth(k)`` / ``.last`` append)

Anything richer (``>>`` chaining, ``internal:*`` engines from ``get_by_*``,
``:visible``, ``:nth-match``, layout pseudos, …) returns ``unsupported`` so the
caller keeps using the regular Playwright read for that call. Correctness wins on
tie: a mis-resolved element yields wrong coordinates, so uncertain grammar always
defers to Playwright rather than guessing.

The JS builders and :func:`parse_result` are pure and shared by the sync and
async call sites; only the ``world.evaluate`` await differs.
"""

from __future__ import annotations

import json
from typing import Any, Optional, Tuple

# Status returned to callers.
OK = "ok"
NOT_FOUND = "not_found"
UNSUPPORTED = "unsupported"

# ---------------------------------------------------------------------------
# JS: selector resolution inside the isolated world
# ---------------------------------------------------------------------------
# Defines ``__resolve(sel)`` returning the matched Element, ``null`` (no match),
# or the string ``'UNSUPPORTED'`` (grammar we don't reimplement). ``__SEL`` is
# inlined by the Python builders below.

_RESOLVER_BODY = r"""
const __UNS = 'UNSUPPORTED';
function __normWS(s){ return (s || '').replace(/\s+/g, ' ').trim(); }
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
  // Playwright's text engine targets the smallest matching element: drop any
  // element that has a descendant which also matches.
  return matches.filter(el => !matches.some(o => o !== el && el.contains(o)));
}
function __extractHasText(css){
  // Only quoted string args are supported; a regex arg (/re/) or bare arg is not.
  if (/:has-text\(\s*[^'"]/.test(css)) return __UNS;
  const texts = [];
  const out = css.replace(/:has-text\(\s*(['"])([\s\S]*?)\1\s*\)/g, function(w, q, inner){ texts.push(__normWS(inner)); return ''; });
  if (out.indexOf(':has-text') !== -1) return __UNS;
  return { css: out.trim() || '*', texts: texts };
}
function __resolve(sel){
  sel = sel.trim();
  // Trailing ">> nth=N" (.first => nth=0, .last => nth=-1, .nth(k) => nth=k).
  let nth = 0, hasNth = false;
  const m = sel.match(/^([\s\S]*?)\s*>>\s*nth=(-?\d+)\s*$/);
  if (m) { sel = m[1].trim(); nth = parseInt(m[2], 10); hasNth = true; }
  if (sel.indexOf('>>') !== -1) return __UNS;        // chaining we don't reimplement
  if (sel.indexOf('internal:') !== -1) return __UNS; // get_by_* engines
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
"""

# ---------------------------------------------------------------------------
# JS: per-operation reads (each returns {r: 'ok'|'not_found'|'unsupported', ...})
# ---------------------------------------------------------------------------

_BOX_OP = r"""
const __el = __resolve(__SEL);
if (__el === 'UNSUPPORTED') return { r: 'unsupported' };
if (!__el) return { r: 'not_found' };
const __rc = __el.getBoundingClientRect();
// Playwright's bounding_box returns null for elements with no box (display:none).
if (__rc.width === 0 && __rc.height === 0 && __rc.x === 0 && __rc.y === 0) return { r: 'not_found' };
return { r: 'ok', box: { x: __rc.x, y: __rc.y, width: __rc.width, height: __rc.height } };
"""

_ACTIONABLE_OP = r"""
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
"""

_VIEWPORT_JS = "(() => ({ width: window.innerWidth, height: window.innerHeight }))()"


def _wrap(selector: str, op: str) -> str:
    """Assemble a full isolated-world expression: resolver + one op."""
    return (
        "(() => {\n"
        "const __SEL = " + json.dumps(selector) + ";\n"
        + _RESOLVER_BODY + "\n" + op + "\n})()"
    )


def build_box_js(selector: str) -> str:
    """JS reading the element's bounding box (getBoundingClientRect, viewport-space)."""
    return _wrap(selector, _BOX_OP)


def build_actionable_js(selector: str) -> str:
    """JS reading visible/enabled/editable for the element."""
    return _wrap(selector, _ACTIONABLE_OP)


def build_pointer_js(selector: str, x: float, y: float) -> str:
    """JS hit-testing elementFromPoint(x, y) against the resolved element.

    ``x``/``y`` are viewport coordinates (same space as getBoundingClientRect and
    the CDP mouse), so no iframe offset is needed — the isolated world runs in the
    main frame's document.
    """
    op = (
        "const __el = __resolve(__SEL);\n"
        "if (__el === 'UNSUPPORTED') return { r: 'unsupported' };\n"
        "if (!__el) return { r: 'not_found' };\n"
        "const __t = document.elementFromPoint(" + repr(float(x)) + ", " + repr(float(y)) + ");\n"
        "if (!__t) return { r: 'ok', hit: false, covering: 'none' };\n"
        "let __n = __t;\n"
        "while (__n) { if (__n === __el) return { r: 'ok', hit: true }; __n = __n.parentNode; }\n"
        "if (__el.contains(__t)) return { r: 'ok', hit: true };\n"
        "return { r: 'ok', hit: false, covering: __t.tagName || 'unknown' };\n"
    )
    return _wrap(selector, op)


def parse_result(raw: Any) -> Tuple[str, Optional[dict]]:
    """Normalize an isolated-world evaluate() result into (status, data).

    ``world.evaluate`` returns ``None`` on any CDP error / JS exception, so a
    non-dict result is treated as ``unsupported`` (fall back to Playwright) —
    never as ``not_found`` (which would suppress a real element).
    """
    if not isinstance(raw, dict):
        return (UNSUPPORTED, None)
    r = raw.get("r")
    if r == OK:
        return (OK, raw)
    if r == NOT_FOUND:
        return (NOT_FOUND, None)
    return (UNSUPPORTED, None)


def eval_parsed(world: Any, expression: str) -> Tuple[str, Optional[dict]]:
    """Evaluate ``expression`` in the world and parse it. Any exception from the
    world (e.g. the CDP session/context can't be created) is treated as
    ``unsupported`` so the caller falls back to the regular Playwright read rather
    than propagating the error out of the humanized action."""
    try:
        return parse_result(world.evaluate(expression))
    except Exception:
        return (UNSUPPORTED, None)


async def async_eval_parsed(world: Any, expression: str) -> Tuple[str, Optional[dict]]:
    """Async variant of :func:`eval_parsed`."""
    try:
        return parse_result(await world.evaluate(expression))
    except Exception:
        return (UNSUPPORTED, None)
