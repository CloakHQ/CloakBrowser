/** Versioned isolated-world DOM selector protocol; mirrors stealth_dom.py. */
export const PROTOCOL_VERSION = 1;
export const OK = 'ok';
export const NOT_FOUND = 'not_found';
export const UNSUPPORTED = 'unsupported';
export const STALE = 'stale';
export const EVALUATION_FAILED = 'evaluation_failed';
export type StealthStatus = typeof OK | typeof NOT_FOUND | typeof UNSUPPORTED | typeof STALE | typeof EVALUATION_FAILED;

export class StealthDomError extends Error { constructor(message: string) { super(message); this.name = new.target.name; } }
export class UnsupportedHumanizeSelectorError extends StealthDomError { constructor(selector: string) { super(`Humanized selector ${JSON.stringify(selector)} is not supported by the isolated-world resolver`); } }
export class StealthWorldUnavailableError extends StealthDomError { constructor() { super('Humanized DOM read requires an active isolated world'); } }
export class StealthEvaluationError extends StealthDomError { constructor(selector: string) { super(`Isolated-world DOM evaluation failed for ${JSON.stringify(selector)}`); } }

export interface StealthWorld { evaluate(expression: string): Promise<any>; }
export function getWorld(pageOrFrame: unknown): StealthWorld | null { return (pageOrFrame as any)?._stealth ?? null; }
export interface StealthBox { x: number; y: number; width: number; height: number; }
export interface StealthSnapshot { v: typeof PROTOCOL_VERSION; r: typeof OK; targetId: number; attached: boolean; visible: boolean; enabled: boolean; editable: boolean; isInput: boolean; focused: boolean; checked: boolean | null; box: StealthBox | null; }
/** Compatibility name used by the humanized action layer. */
export type SnapshotPayload = StealthSnapshot;
export interface StealthPointerPayload { v: typeof PROTOCOL_VERSION; r: typeof OK; targetId: number; hit: boolean; covering?: string; }
export interface ParsedResult { status: StealthStatus; data?: any; }

const RESOLVER_BODY = String.raw`
const __UNS = 'UNSUPPORTED';
const __V = 1;
const __STATE_KEY = '__cloakHumanDomV1';
function __state(){
  let s = globalThis[__STATE_KEY];
  if (!s) {
    s = { ids: new WeakMap(), nextId: 1 };
    Object.defineProperty(globalThis, __STATE_KEY, { value: s, configurable: false, enumerable: false });
  }
  return s;
}
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
      if (child.nodeType === 1) {
        full += __elementText(child, cache).full;
        if (child.tagName && child.tagName.toLowerCase() === 'br') full += '\n';
      }
    }
  }
  if (immediate) fragments.push(immediate);
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
function __matchText(el, matcher, cache){
  const text = __elementText(el, cache);
  if (matcher.kind === 'regex') { matcher.regex.lastIndex = 0; return matcher.regex.test(text.full); }
  if (matcher.kind === 'exact') return text.immediate.some(x => __normWS(x) === matcher.value);
  return text.normalized.toLowerCase().includes(matcher.value);
}
function __byText(arg){
  const matcher = __parseTextMatcher(arg);
  if (matcher === __UNS) return __UNS;
  const matches = [], cache = new Map();
  const all = __allElements();
  for (const el of all) { if (__matchText(el, matcher, cache)) matches.push(el); }
  // Playwright's text engine targets the smallest matching element: drop any
  // element that has a descendant which also matches.
  return matches.filter(el => !matches.some(o => o !== el && el.contains(o)));
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
  if (sel.indexOf('internal:') !== -1) return __UNS; // get_by_* engines
  let list;
  if (sel.indexOf('xpath=') === 0) { list = __byXPath(sel.slice(6)); }
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
`;
const SNAPSHOT_OP=String.raw`
const __el=__resolve(__SEL);if(__el==='UNSUPPORTED')return {v:__V,r:'unsupported'};if(!__el)return {v:__V,r:'not_found'};const __box=__visBox(__el),__hasBox=__box!==null,__tag=__el.tagName.toLowerCase(),__enabled=__isEnabled(__el),__editable=__isEditable(__el,__enabled);return {v:__V,r:'ok',targetId:__targetId(__el),attached:__el.isConnected===true,visible:__isVisible(__el),enabled:__enabled,editable:__editable,isInput:__tag==='input'||__tag==='textarea'||__el.isContentEditable===true,focused:__deepActiveElement()===__el,checked:typeof __el.checked==='boolean'?__el.checked:null,box:__box};`;
export const VIEWPORT_JS='(() => ({ width: window.innerWidth, height: window.innerHeight }))()';
function wrap(selector:string,op:string){return `(() => {\nconst __SEL = ${JSON.stringify(selector)};\n${RESOLVER_BODY}\n${op}\n})()`;}
export function buildSnapshotJs(selector:string){return wrap(selector,SNAPSHOT_OP);}
export function buildBoxJs(selector:string){return wrap(selector,SNAPSHOT_OP.replace("r:'ok'","r:__hasBox?'ok':'not_found'"));}
export function buildActionableJs(selector:string){return buildSnapshotJs(selector);}
function pointer(selector:string,targetId:number|undefined,x:number,y:number,validate:boolean){const check=validate?`if(__id!==${Math.trunc(targetId!)})return {v:__V,r:'stale',targetId:__id};if(__el.isConnected!==true)return {v:__V,r:'stale',targetId:__id};`:'';return wrap(selector,`const __el=__resolve(__SEL);if(__el==='UNSUPPORTED')return {v:__V,r:'unsupported'};if(!__el)return {v:__V,r:'not_found'};const __id=__targetId(__el);${check}const __t=__deepElementFromPoint(${Number(x)},${Number(y)});let __n=__t;while(__n){if(__n===__el)return {v:__V,r:'ok',targetId:__id,hit:true};__n=__composedParent(__n);}if(__t&&__el.contains(__t))return {v:__V,r:'ok',targetId:__id,hit:true};return {v:__V,r:'ok',targetId:__id,hit:false,covering:__t?(__t.tagName||'unknown'):'none'};`);}
export function buildValidateJs(selector:string,targetId:number,x:number,y:number){return pointer(selector,targetId,x,y,true);}
export function buildPointerJs(selector:string,x:number,y:number){return pointer(selector,undefined,x,y,false);}
export function parseResult(raw:any):ParsedResult{if(!raw||typeof raw!=='object'||Array.isArray(raw)||raw.v!==PROTOCOL_VERSION)return{status:EVALUATION_FAILED};if(raw.r===OK)return Number.isInteger(raw.targetId)?{status:OK,data:raw}:{status:EVALUATION_FAILED};if(raw.r===NOT_FOUND)return{status:NOT_FOUND};if(raw.r===STALE)return Number.isInteger(raw.targetId)?{status:STALE,data:raw}:{status:EVALUATION_FAILED};if(raw.r===UNSUPPORTED)return{status:UNSUPPORTED};return{status:EVALUATION_FAILED};}
export async function evalParsed(world:StealthWorld,expression:string):Promise<ParsedResult>{try{return parseResult(await world.evaluate(expression));}catch{return{status:EVALUATION_FAILED};}}
export async function readSnapshot(world:StealthWorld|null|undefined,selector:string):Promise<StealthSnapshot>{if(!world)throw new StealthWorldUnavailableError();const r=await evalParsed(world,buildSnapshotJs(selector));if(r.status===OK)return r.data as StealthSnapshot;if(r.status===UNSUPPORTED)throw new UnsupportedHumanizeSelectorError(selector);throw new StealthEvaluationError(selector);}
