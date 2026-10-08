"""CDP isolated worlds for every frame of a page (main, same-process, OOPIF).

Each frame gets one isolated world per document, created through
``Page.createIsolatedWorld`` on the CDP session that owns the frame.  Into
that world we install Playwright's InjectedScript (see ``injected.py``) and a
small helper object.  Nothing here runs in, or is observable from, the page's
main world:

* frame <-> CDP frame id mapping uses ``Page.getFrameTree`` only;
* iframe owner elements are reached via ``DOM.getFrameOwner`` +
  ``DOM.resolveNode`` straight into the parent frame's isolated world;
* elements are kept in a world-local registry and addressed by integer ids.

Everything is async and works on Playwright *impl* objects; the sync API calls
into it through ``SyncBase._sync``.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional, Tuple

from playwright._impl._errors import Error

from .injected import GLOBAL, build_install_js, find_injected_literal

HELPERS = "__cloakH"

_decoded_source: Optional[str] = None


class StealthWorldError(Error):
    """An isolated-world evaluation failed (never falls back to the page)."""


# Helper library evaluated after the InjectedScript in every world.
_HELPERS_JS = r"""(() => {
if (globalThis.__cloakH) return true;
const I = globalThis.__cloakInjected;
const els = new Map(); let seq = 0;
const put = (e) => { const id = ++seq; els.set(id, e); return id; };
const get = (id) => { const e = els.get(id); if (!e) throw new Error('cloak:stale-element'); return e; };
const textValue = (t) => t.isContentEditable ? t.textContent : ('value' in t ? String(t.value) : null);
// display:contents elements have no box: use the union of what they render.
const contentsBox = (root) => {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const add = (r) => { if (!r.width && !r.height) return;
    x0 = Math.min(x0, r.left); y0 = Math.min(y0, r.top); x1 = Math.max(x1, r.right); y1 = Math.max(y1, r.bottom); };
  const walk = (n) => {
    for (const c of n.childNodes) {
      if (c.nodeType === 3) {
        if (!c.textContent.trim()) continue;
        const p = c.parentElement;
        if (p && getComputedStyle(p).visibility !== 'visible') continue;
        const rg = document.createRange(); rg.selectNodeContents(c);
        for (const r of rg.getClientRects()) add(r);
      } else if (c.nodeType === 1) {
        const s = getComputedStyle(c);
        if (s.display === 'contents') { walk(c); continue; }
        if (s.visibility !== 'visible' || s.display === 'none') continue;
        add(c.getBoundingClientRect());
      }
    }
  };
  walk(root);
  return x0 === Infinity ? null : { left: x0, top: y0, width: x1 - x0, height: y1 - y0 };
};
const parentOrHost = (n) => n.parentElement || (n.parentNode && n.parentNode.host) || null;
const H = {
  el: (id) => get(id),
  adopt() { return put(this); },
  matchRect(x, y, w, h) {
    // ElementHandles carry no DOM identity we can read without touching the
    // main world, but Playwright reports their border box through CDP
    // (bounding_box, page-invisible). Find the element with exactly that box.
    const out = [];
    const visit = (root) => {
      for (const e of root.querySelectorAll('*')) {
        if (e.shadowRoot) visit(e.shadowRoot);
        const b = e.getBoundingClientRect();
        if (Math.abs(b.left - x) < 0.6 && Math.abs(b.top - y) < 0.6 &&
            Math.abs(b.width - w) < 0.6 && Math.abs(b.height - h) < 0.6) out.push(e);
      }
    };
    visit(document);
    // Exactly one element must have this box. A wrapper and its child with the
    // same box (or two overlapping siblings) are ambiguous: the caller raises
    // rather than guessing and acting on the wrong one.
    if (out.length !== 1) return { count: out.length };
    return { count: 1, id: put(out[0]) };
  },
  release(ids) { for (const id of ids) els.delete(id); },
  resolve(selector, strict, rootId) {
    const root = rootId ? get(rootId) : document;
    let parsed, all;
    try { parsed = I.parseSelector(selector); all = I.querySelectorAll(parsed, root); }
    catch (e) { return { status: 'error', message: e.message }; }
    if (!all.length) return { status: 'none' };
    if (strict && all.length > 1)
      return { status: 'strict', message: I.strictModeViolationError(parsed, all).message };
    return { status: 'ok', id: put(all[0]), count: all.length };
  },
  fromPath(path) {
    let cur = document;
    for (const step of path) {
      if (step === 'S') { cur = cur.shadowRoot; if (!cur) return { status: 'closed-shadow' }; continue; }
      cur = cur.childNodes[step];
      if (!cur) return { status: 'none' };
    }
    if (cur.nodeType !== 1) return { status: 'none' };
    return { status: 'ok', id: put(cur) };
  },
  retarget(id, behavior) { const t = I.retarget(get(id), behavior); return t ? put(t) : 0; },
  info(id) {
    const e = get(id);
    const t = I.retarget(e, 'follow-label') || e;
    const root = t.getRootNode();
    return {
      connected: e.isConnected,
      tag: t.nodeName.toLowerCase(),
      type: t.nodeName === 'INPUT' ? String(t.type).toLowerCase() : null,
      editable: !!t.isContentEditable,
      focused: !!root && root.activeElement === t,
      value: textValue(t),
      preview: I.previewNode(e),
    };
  },
  connected(id) { return get(id).isConnected; },
  value(id) { const e = get(id); return textValue(I.retarget(e, 'follow-label') || e); },
  activeValue() {
    const a = document.activeElement;
    if (!a || a === document.body) return { tag: null };
    return { tag: a.nodeName.toLowerCase(), type: a.nodeName === 'INPUT' ? String(a.type).toLowerCase() : null,
             editable: !!a.isContentEditable, value: textValue(a) };
  },
  async states(id, states) {
    const e = get(id);
    try {
      if (I.checkElementStates) {
        const r = await I.checkElementStates(e, states);
        if (r === undefined) return null;
        if (r === 'error:notconnected') return { missing: 'attached' };
        return { missing: r.missingState };
      }
      for (const s of states) {
        if (s === 'stable') continue;
        const r = I.elementState(e, s);
        if (r === 'error:notconnected' || r.received === 'error:notconnected') return { missing: 'attached' };
        if (!(r.matches !== undefined ? r.matches : r)) return { missing: s };
      }
      return null;
    } catch (err) { return { error: err.message }; }
  },
  checked(id) {
    try {
      const e = get(id), r = I.elementState(e, 'checked');
      if (typeof r === 'object') return { checked: r.received === 'checked', radio: !!r.isRadio };
      // Playwright < 1.50 returns a boolean here.
      const t = I.retarget(e, 'follow-label');
      return { checked: r === true, radio: !!t && t.nodeName === 'INPUT' && t.type === 'radio' };
    }
    catch (err) { return { error: err.message }; }
  },
  geometry(id) {
    const e = get(id);
    if (!e.isConnected) return null;
    let b = e.getBoundingClientRect();
    const st = getComputedStyle(e);
    if (st.display === 'contents') b = contentsBox(e) || b;
    return { x: b.left, y: b.top, width: b.width, height: b.height,
             bl: parseFloat(st.borderLeftWidth) || 0, bt: parseFloat(st.borderTopWidth) || 0 };
  },
  scroller(id) {
    const e = get(id);
    const b = e.getBoundingClientRect();
    const top = document.scrollingElement || document.documentElement;
    for (let p = parentOrHost(e); p && p !== top && p !== document.body; p = parentOrHost(p)) {
      const s = getComputedStyle(p);
      const sy = /(auto|scroll|overlay)/.test(s.overflowY) && p.scrollHeight > p.clientHeight;
      const sx = /(auto|scroll|overlay)/.test(s.overflowX) && p.scrollWidth > p.clientWidth;
      if (!sy && !sx) continue;
      const r = p.getBoundingClientRect();
      const x = r.left + p.clientLeft, y = r.top + p.clientTop, w = p.clientWidth, h = p.clientHeight;
      if ((sy && (b.top < y || b.bottom > y + h)) || (sx && (b.left < x || b.right > x + w)))
        return { x, y, width: w, height: h };
    }
    return null;
  },
  doc() {
    const e = document.scrollingElement || document.documentElement;
    const rangeX = Math.max(0, e.scrollWidth - e.clientWidth);
    const rtl = getComputedStyle(document.body || e).direction === 'rtl';
    return { y: scrollY, maxY: Math.max(0, e.scrollHeight - e.clientHeight), x: scrollX,
             minX: rtl ? -rangeX : 0, maxX: rtl ? 0 : rangeX, width: innerWidth, height: innerHeight };
  },
  hit(id, x, y) {
    const r = I.expectHitTarget({ x, y }, get(id));
    return r === 'done' ? null : r.hitTargetDescription;
  },
  fill(id, value) {
    try { return { result: I.fill(get(id), value) }; } catch (err) { return { error: err.message }; }
  },
  select(id, options, elementIds) {
    const opts = options.concat(elementIds.map(get));
    try {
      const r = I.selectOptions(get(id), opts);
      return Array.isArray(r) ? { values: r } : { error: String(r) };
    } catch (err) { return { error: err.message }; }
  },
  focus(id) { const e = I.retarget(get(id), 'follow-label') || get(id); I.focusNode(e, false); return true; },
  caretAtEnd(id) {
    const t = I.retarget(get(id), 'follow-label') || get(id);
    if ('selectionStart' in t && t.selectionStart !== null) return t.selectionStart === String(t.value).length;
    return false;
  },
  platform() { return navigator.platform || ''; },
  rangeInfo(id) {
    const e = I.retarget(get(id), 'follow-label') || get(id);
    const n = (v, d) => { const x = parseFloat(v); return Number.isFinite(x) ? x : d; };
    const min = n(e.min, 0), max = Math.max(n(e.max, 100), n(e.min, 0));
    const step = e.step === 'any' ? 0 : n(e.step, 1);
    const st = getComputedStyle(e);
    const vertical = st.writingMode.startsWith('vertical') || st.appearance === 'slider-vertical';
    return { min, max, step, value: n(e.value, min), vertical, rtl: st.direction === 'rtl' };
  },
  // The options a select_option() call targets, without changing anything.
  selectPlan(id, options, elementIds) {
    const sel = I.retarget(get(id), 'follow-label') || get(id);
    if (sel.nodeName !== 'SELECT') return { error: 'Element is not a <select> element' };
    const opts = [...sel.options];
    const wanted = options.concat(elementIds.map(get));
    const norm = (s) => s.replace(/\s+/g, ' ').trim();
    const match = (o, i, w) => {
      if (w instanceof Node) return o === w;
      const lbl = (l) => l === o.label || norm(l) === norm(o.label);
      let ok = true;
      if (w.valueOrLabel !== undefined) ok = ok && (w.valueOrLabel === o.value || lbl(w.valueOrLabel));
      if (w.value !== undefined) ok = ok && w.value === o.value;
      if (w.label !== undefined) ok = ok && lbl(w.label);
      if (w.index !== undefined) ok = ok && w.index === i;
      return ok;
    };
    const enabled = (o) => !o.disabled && !(o.parentElement && o.parentElement.nodeName === 'OPTGROUP' && o.parentElement.disabled);
    let remaining = wanted.slice(); const targets = [];
    for (let i = 0; i < opts.length && remaining.length; i++) {
      if (!remaining.some(w => match(opts[i], i, w))) continue;
      if (!enabled(opts[i])) return { retry: 'option being selected is not enabled' };
      targets.push(i);
      remaining = sel.multiple ? remaining.filter(w => !match(opts[i], i, w)) : [];
    }
    if (remaining.length) return { retry: 'did not find some options' };
    return { targets, multiple: sel.multiple, listbox: sel.multiple || sel.size > 1,
             navigable: opts.map(o => enabled(o) && !o.hidden && getComputedStyle(o).display !== 'none'),
             values: targets.map(i => opts[i].value) };
  },
  optionId(id, index) { const sel = I.retarget(get(id), 'follow-label') || get(id); return put(sel.options[index]); },
  selectState(id) {
    const sel = I.retarget(get(id), 'follow-label') || get(id);
    return { current: sel.selectedIndex, selected: [...sel.options].map((o, i) => o.selected ? i : -1).filter(i => i >= 0),
             values: [...sel.selectedOptions].map(o => o.value) };
  },
  ownerContent() {
    // Runs with this = the <iframe> owner element: viewport-relative content box.
    const r = this.getBoundingClientRect(); const s = getComputedStyle(this);
    const bl = parseFloat(s.borderLeftWidth) || 0, bt = parseFloat(s.borderTopWidth) || 0;
    const pl = parseFloat(s.paddingLeft) || 0, pt = parseFloat(s.paddingTop) || 0;
    const pr = parseFloat(s.paddingRight) || 0, pb = parseFloat(s.paddingBottom) || 0;
    return { x: r.left + bl + pl, y: r.top + bt + pt,
             width: Math.max(0, this.clientWidth - pl - pr), height: Math.max(0, this.clientHeight - pt - pb) };
  },
};
Object.defineProperty(globalThis, '__cloakH', { value: H });
return true;
})()"""


def _stale(exc: BaseException) -> bool:
    msg = str(exc)
    return any(s in msg for s in (
        "Cannot find context", "Execution context was destroyed", "Inspected target navigated",
        "cloak:stale-world", "Cannot find default execution context",
    ))


class _FrameRec:
    __slots__ = ("session", "cdp_id", "ctx")

    def __init__(self, session: Any, cdp_id: str) -> None:
        self.session = session
        self.cdp_id = cdp_id
        self.ctx: Optional[int] = None


class Worlds:
    """Isolated worlds for all frames of one Playwright (impl) page."""

    def __init__(self, page: Any) -> None:
        self.page = page
        self._session: Any = None
        self._frames: Dict[Any, _FrameRec] = {}
        self._lock: Optional[asyncio.Lock] = None
        try:
            page.on("framenavigated", self.invalidate)
            page.on("framedetached", self.invalidate)
        except Exception:  # pragma: no cover - emitter missing in mocks
            pass

    # -- sessions / frame mapping -------------------------------------------

    async def session(self) -> Any:
        if self._session is None:
            self._session = await self.page.context.new_cdp_session(self.page)
        return self._session

    def invalidate(self, frame: Any = None) -> None:
        """Forget worlds of ``frame`` and its descendants (all when None)."""
        if frame is None:
            self._frames.clear()
            return
        doomed = [f for f in self._frames if f is frame or _is_descendant(f, frame)]
        for f in doomed:
            self._frames.pop(f, None)

    async def _locate(self, frame: Any) -> _FrameRec:
        rec = self._frames.get(frame)
        if rec is not None:
            return rec
        if frame.is_detached():
            raise Error("Frame was detached")
        parent = frame.parent_frame
        if parent is None:
            session = await self.session()
            tree = await session.send("Page.getFrameTree")
            rec = _FrameRec(session, tree["frameTree"]["frame"]["id"])
        else:
            rec = await self._locate_child(frame, parent)
        self._frames[frame] = rec
        return rec

    async def _locate_child(self, frame: Any, parent: Any) -> _FrameRec:
        try:  # out-of-process iframe: it has its own target/session
            own = await self.page.context.new_cdp_session(frame)
        except Error:
            own = None
        if own is not None:
            tree = await own.send("Page.getFrameTree")
            return _FrameRec(own, tree["frameTree"]["frame"]["id"])
        prec = await self._locate(parent)
        tree = await prec.session.send("Page.getFrameTree")
        node = _find_node(tree["frameTree"], prec.cdp_id)
        kids = [k["frame"] for k in (node or {}).get("childFrames", [])]
        cdp_id = _match_child(frame, parent, kids)
        if cdp_id is None:
            raise Error("cloakbrowser humanize: could not map the frame to a CDP frame")
        return _FrameRec(prec.session, cdp_id)

    async def cdp_frame_id(self, frame: Any) -> str:
        return (await self._locate(frame)).cdp_id

    async def frame_for_cdp_id(self, parent: Any, cdp_id: str) -> Optional[Any]:
        for child in parent.child_frames:
            try:
                if (await self._locate(child)).cdp_id == cdp_id:
                    return child
            except Error:
                continue
        return None

    # -- world lifecycle ----------------------------------------------------

    async def _ready(self, frame: Any) -> _FrameRec:
        rec = await self._locate(frame)
        if rec.ctx is not None:
            return rec
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if rec.ctx is not None:
                return rec
            res = await rec.session.send("Page.createIsolatedWorld", {
                "frameId": rec.cdp_id, "worldName": "", "grantUniveralAccess": True,
            })
            ctx = res["executionContextId"]
            await self._install(rec.session, ctx)
            rec.ctx = ctx
        return rec

    async def _install(self, session: Any, ctx: int) -> None:
        global _decoded_source
        if _decoded_source is None:
            _decoded_source = await self._raw_eval(session, ctx, find_injected_literal())
        await self._raw_eval(session, ctx, build_install_js(_decoded_source))
        await self._raw_eval(session, ctx, _HELPERS_JS)

    @staticmethod
    async def _raw_eval(session: Any, ctx: int, expression: str, by_value: bool = True,
                        await_promise: bool = True) -> Any:
        res = await session.send("Runtime.evaluate", {
            "expression": expression, "contextId": ctx,
            "returnByValue": by_value, "awaitPromise": await_promise,
        })
        if "exceptionDetails" in res:
            det = res["exceptionDetails"]
            desc = (det.get("exception") or {}).get("description") or det.get("text", "")
            if "cloak:stale-element" in desc:
                raise StaleElement()
            raise StealthWorldError(f"cloakbrowser humanize: isolated-world script failed: {desc.splitlines()[0]}")
        return res["result"].get("value") if by_value else res["result"]

    # -- evaluation -----------------------------------------------------------

    async def evaluate(self, frame: Any, expression: str, by_value: bool = True) -> Any:
        """Evaluate in ``frame``'s isolated world; recreate the world once if stale."""
        for attempt in (0, 1):
            rec = await self._ready(frame)
            try:
                return await self._raw_eval(rec.session, rec.ctx, expression, by_value)
            except StaleElement:
                raise
            except Error as exc:
                if attempt == 0 and _stale(exc):
                    rec.ctx = None
                    continue
                raise
        raise StealthWorldError("cloakbrowser humanize: isolated world unavailable")  # pragma: no cover

    async def call(self, frame: Any, method: str, *args: Any) -> Any:
        return await self.evaluate(frame, f"{HELPERS}.{method}({', '.join(json.dumps(a) for a in args)})")

    async def element_object_id(self, frame: Any, element_id: int) -> Tuple[Any, str]:
        rec = await self._ready(frame)
        obj = await self._raw_eval(rec.session, rec.ctx, f"{HELPERS}.el({int(element_id)})", by_value=False)
        return rec.session, obj["objectId"]

    async def adopt(self, frame: Any, backend_node_id: int) -> int:
        """Register the DOM node ``backend_node_id`` in ``frame``'s world."""
        rec = await self._ready(frame)
        try:
            obj = (await rec.session.send("DOM.resolveNode", {
                "backendNodeId": backend_node_id, "executionContextId": rec.ctx,
            }))["object"]
        except Error as exc:
            raise StaleElement() from exc
        try:
            res = await rec.session.send("Runtime.callFunctionOn", {
                "objectId": obj["objectId"], "returnByValue": True,
                "functionDeclaration": f"function () {{ return globalThis.{HELPERS}.adopt.call(this); }}",
            })
        finally:
            await _release(rec.session, obj["objectId"])
        if "exceptionDetails" in res:
            raise StaleElement()
        return res["result"]["value"]

    async def editor_fields(self, frame: Any, element_id: int) -> List[Dict[str, Any]]:
        """Segments of a native date/time editor (``<input type=date>`` ...) in
        visual order, with centres relative to the input's border box.

        The segments live in the input's closed user-agent shadow root, which
        neither page scripts nor our isolated world can see. CDP's DOM domain
        can (``pierce``), and reading it runs no script in the page.
        """
        session, object_id = await self.element_object_id(frame, element_id)
        try:
            node = (await session.send("DOM.describeNode", {"objectId": object_id, "depth": -1, "pierce": True}))["node"]
            own = (await session.send("DOM.getBoxModel", {"objectId": object_id}))["model"]["border"]
        finally:
            await _release(session, object_id)
        out: List[Dict[str, Any]] = []

        async def walk(n: Dict[str, Any]) -> None:
            attrs = n.get("attributes") or []
            pseudo = dict(zip(attrs[::2], attrs[1::2])).get("pseudo", "")
            if pseudo.startswith("-webkit-datetime-edit-") and pseudo.endswith("-field") and "wrapper" not in pseudo:
                quad = (await session.send("DOM.getBoxModel", {"backendNodeId": n["backendNodeId"]}))["model"]["border"]
                out.append({"kind": pseudo[len("-webkit-datetime-edit-"):-len("-field")],
                            "dx": (quad[0] + quad[2]) / 2 - own[0], "dy": (quad[1] + quad[5]) / 2 - own[1]})
            for c in (n.get("children") or []) + (n.get("shadowRoots") or []):
                await walk(c)

        await walk(node)
        out.sort(key=lambda f: (round(f["dy"] / 4), f["dx"]))
        return out

    async def owner_element(self, frame: Any) -> int:
        """Register ``frame``'s <iframe> element in the parent frame's world."""
        rec = await self._locate(frame)
        prec = await self._ready(frame.parent_frame)
        owner = await prec.session.send("DOM.getFrameOwner", {"frameId": rec.cdp_id})
        return await self.adopt(frame.parent_frame, owner["backendNodeId"])

    async def content_frame(self, frame: Any, element_id: int) -> Optional[Any]:
        """Child frame owned by the <iframe> element ``element_id`` in ``frame``."""
        session, object_id = await self.element_object_id(frame, element_id)
        try:
            node = (await session.send("DOM.describeNode", {"objectId": object_id}))["node"]
        finally:
            await _release(session, object_id)
        cdp_id = node.get("frameId")
        if not cdp_id:
            return None
        return await self.frame_for_cdp_id(frame, cdp_id)

    # -- geometry across frames ---------------------------------------------

    async def _owner_call(self, frame: Any, declaration: str, *args: Any) -> Any:
        """Call ``declaration`` with ``this`` = the frame's <iframe> element,
        inside the parent frame's isolated world."""
        parent = frame.parent_frame
        rec = await self._locate(frame)
        prec = await self._ready(parent)
        owner = await prec.session.send("DOM.getFrameOwner", {"frameId": rec.cdp_id})
        obj = (await prec.session.send("DOM.resolveNode", {
            "backendNodeId": owner["backendNodeId"], "executionContextId": prec.ctx,
        }))["object"]
        try:
            res = await prec.session.send("Runtime.callFunctionOn", {
                "objectId": obj["objectId"], "functionDeclaration": declaration,
                "arguments": [{"value": a} for a in args], "returnByValue": True,
            })
        finally:
            await _release(prec.session, obj["objectId"])
        if "exceptionDetails" in res:
            raise StealthWorldError("cloakbrowser humanize: frame owner evaluation failed")
        return res["result"].get("value")

    async def viewport(self) -> Dict[str, float]:
        size = getattr(self.page, "_viewport_size", None)
        if size and size.get("width"):
            return {"width": size["width"], "height": size["height"]}
        doc = await self.call(self.page.main_frame, "doc")
        return {"width": doc["width"], "height": doc["height"]}

    async def frame_geometry(self, frame: Any) -> Tuple[float, float, Dict[str, float]]:
        """``(offset_x, offset_y, clip)``: the frame's origin in viewport
        coordinates and the visible part of it (intersection of all ancestor
        iframe content boxes and the viewport)."""
        parent = frame.parent_frame
        if parent is None:
            vp = await self.viewport()
            return 0.0, 0.0, {"x": 0.0, "y": 0.0, "width": float(vp["width"]), "height": float(vp["height"])}
        px, py, pclip = await self.frame_geometry(parent)
        box = await self._owner_call(frame, f"function () {{ return {HELPERS}.ownerContent.call(this); }}")
        ox, oy = px + box["x"], py + box["y"]
        clip = intersect(pclip, {"x": ox, "y": oy, "width": box["width"], "height": box["height"]})
        return ox, oy, clip

    async def owners_hit(self, frame: Any, vx: float, vy: float) -> Optional[str]:
        """Check that the viewport point hits each ancestor <iframe> owner."""
        child = frame
        while child.parent_frame is not None:
            px, py, _ = await self.frame_geometry(child.parent_frame)
            desc = await self._owner_call(
                child,
                "function (x, y) { const r = globalThis.%s.expectHitTarget({ x, y }, this);"
                " return r === 'done' ? null : r.hitTargetDescription; }" % GLOBAL,
                vx - px, vy - py,
            )
            if desc:
                return desc
            child = child.parent_frame
        return None


class StaleElement(Error):
    def __init__(self) -> None:
        super().__init__("element is not attached to the DOM")


async def _release(session: Any, object_id: str) -> None:
    try:
        await session.send("Runtime.releaseObject", {"objectId": object_id})
    except Error:
        pass


def intersect(a: Dict[str, float], b: Dict[str, float]) -> Dict[str, float]:
    x0, y0 = max(a["x"], b["x"]), max(a["y"], b["y"])
    x1 = min(a["x"] + a["width"], b["x"] + b["width"])
    y1 = min(a["y"] + a["height"], b["y"] + b["height"])
    return {"x": x0, "y": y0, "width": max(0.0, x1 - x0), "height": max(0.0, y1 - y0)}


def _is_descendant(frame: Any, ancestor: Any) -> bool:
    p = getattr(frame, "parent_frame", None)
    while p is not None:
        if p is ancestor:
            return True
        p = p.parent_frame
    return False


def _find_node(tree: Dict[str, Any], cdp_id: str) -> Optional[Dict[str, Any]]:
    if tree["frame"]["id"] == cdp_id:
        return tree
    for child in tree.get("childFrames", []):
        found = _find_node(child, cdp_id)
        if found is not None:
            return found
    return None


def _match_child(frame: Any, parent: Any, kids: List[Dict[str, Any]]) -> Optional[str]:
    """Pick the CDP child frame for a Playwright frame.

    Playwright and CDP list child frames in attach order; frames sharing the
    same (name, url) are matched by their position within that group.
    """
    def key_pw(f: Any) -> Tuple[str, str]:
        return f.name, f.url

    def key_cdp(k: Dict[str, Any]) -> Tuple[str, str]:
        return k.get("name", ""), k.get("url", "") + k.get("urlFragment", "")

    want = key_pw(frame)
    cands = [k for k in kids if key_cdp(k) == want]
    peers = [f for f in parent.child_frames if key_pw(f) == want]
    if cands and frame in peers and len(cands) == len(peers):
        return cands[peers.index(frame)]["id"]
    if len(cands) == 1:
        return cands[0]["id"]
    siblings = list(parent.child_frames)
    if len(kids) == len(siblings) and frame in siblings:
        return kids[siblings.index(frame)]["id"]
    return None
