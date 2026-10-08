namespace CloakBrowser.Human;

/// <summary>
/// Helper library evaluated after the InjectedScript in every isolated world.
/// Byte-identical copy of <c>cloakbrowser/human/world.py</c> (<c>_HELPERS_JS</c>) and
/// <c>js/src/human/worldHelpers.ts</c>; checked by tests/test_resolver_sources_match.py.
/// Edit all three together.
/// </summary>
internal static class WorldHelpers
{
    public const string Name = "__cloakH";

    public const string Js = """
(() => {
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
})()
""";
}
