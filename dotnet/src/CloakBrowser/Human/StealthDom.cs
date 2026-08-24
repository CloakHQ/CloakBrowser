using System;
using System.Globalization;
using System.Text.Json;
using System.Threading.Tasks;

namespace CloakBrowser.Human;

/// <summary>
/// Isolated-world DOM reads for the humanize layer.
///
/// The pre-click helpers (actionability, scroll geometry, pointer-events) read
/// element state and geometry. This performs those reads inside the CDP isolated
/// execution context (<see cref="IsolatedWorld"/>) rather than through Playwright's
/// selector/evaluate machinery.
///
/// The isolated world resolves elements with plain DOM APIs, so this reimplements
/// the subset of Playwright's selector grammar the humanize layer commonly receives:
/// plain CSS / <c>css=</c> (incl. the <c>:has-text("...")</c> pseudo), the <c>text=</c>
/// engine, <c>xpath=</c> / leading <c>//</c>, and a trailing <c>&gt;&gt; nth=N</c>.
/// Anything richer (chaining, <c>internal:*</c> engines, layout pseudos) yields
/// <see cref="StealthStatus.Unsupported"/> so the caller keeps using the regular
/// Playwright read. A mis-resolved element yields wrong coordinates, so uncertain
/// grammar always defers to Playwright rather than guessing.
///
/// Mirror of the Python/JS wrappers; the resolver JavaScript string is identical
/// across wrappers.
/// </summary>
internal enum StealthStatus { Ok, NotFound, Unsupported }

internal static class StealthDom
{
    // Defines __resolve(sel) returning the matched Element, null (no match), or the
    // string 'UNSUPPORTED' (grammar not reimplemented). __SEL is inlined by Wrap().
    private const string ResolverBody = @"
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
  if ((q === '""' || q === ""'"") && arg.charAt(arg.length - 1) === q) { exact = true; needle = arg.slice(1, -1); }
  needle = __normWS(needle);
  const matches = [];
  const all = document.querySelectorAll('*');
  for (const el of all) { if (__matchText(el, needle, exact)) matches.push(el); }
  return matches.filter(el => !matches.some(o => o !== el && el.contains(o)));
}
function __extractHasText(css){
  if (/:has-text\(\s*[^'""]/.test(css)) return __UNS;
  const texts = [];
  const out = css.replace(/:has-text\(\s*(['""])([\s\S]*?)\1\s*\)/g, function(w, q, inner){ texts.push(__normWS(inner)); return ''; });
  if (out.indexOf(':has-text') !== -1) return __UNS;
  return { css: out.trim() || '*', texts: texts };
}
function __resolve(sel){
  sel = sel.trim();
  let nth = 0, hasNth = false;
  const m = sel.match(/^([\s\S]*?)\s*>>\s*nth=(-?\d+)\s*$/);
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
// display:contents elements have no box of their own (getBoundingClientRect is
// always all-zero) even though their children/text render normally -- Playwright's
// own actionability engine recurses into children for this case, so we mirror it
// here rather than reporting a false negative for e.g. reset ""li { display: contents }""
// patterns used by custom dropdown/menu widgets (#560).
function __visBox(el){
  const st = getComputedStyle(el);
  if (st.display === 'contents') {
    let ux1 = Infinity, uy1 = Infinity, ux2 = -Infinity, uy2 = -Infinity, found = false;
    for (let child = el.firstChild; child; child = child.nextSibling) {
      let r = null;
      if (child.nodeType === 1) {
        const cv = __visBox(child);
        if (cv.visible) r = cv.box;
      } else if (child.nodeType === 3 && __normWS(child.textContent)) {
        const rng = document.createRange();
        rng.selectNode(child);
        const rr = rng.getBoundingClientRect();
        if (rr.width > 0 || rr.height > 0) r = { x: rr.x, y: rr.y, width: rr.width, height: rr.height };
      }
      if (r) {
        found = true;
        ux1 = Math.min(ux1, r.x); uy1 = Math.min(uy1, r.y);
        ux2 = Math.max(ux2, r.x + r.width); uy2 = Math.max(uy2, r.y + r.height);
      }
    }
    if (!found) return { visible: false, box: null };
    return { visible: true, box: { x: ux1, y: uy1, width: ux2 - ux1, height: uy2 - uy1 } };
  }
  const rc = el.getBoundingClientRect();
  const hasBox = rc.width > 0 || rc.height > 0;
  const box = hasBox ? { x: rc.x, y: rc.y, width: rc.width, height: rc.height } : null;
  const visible = hasBox && st.visibility !== 'hidden' && st.display !== 'none';
  return { visible, box };
}
";

    private const string BoxOp = @"
const __el = __resolve(__SEL);
if (__el === 'UNSUPPORTED') return { r: 'unsupported' };
if (!__el) return { r: 'not_found' };
const __vb = __visBox(__el);
if (!__vb.box) return { r: 'not_found' };
return { r: 'ok', box: __vb.box };
";

    private const string ActionableOp = @"
const __el = __resolve(__SEL);
if (__el === 'UNSUPPORTED') return { r: 'unsupported' };
if (!__el) return { r: 'not_found' };
const __vb = __visBox(__el);
const __tag = __el.tagName.toLowerCase();
const __enabled = !(__el.disabled === true || __el.getAttribute('aria-disabled') === 'true');
const __editable = __enabled && !__el.readOnly &&
  (__tag === 'input' || __tag === 'textarea' || __tag === 'select' || __el.isContentEditable === true);
return { r: 'ok', visible: __vb.visible, enabled: __enabled, editable: __editable, box: __vb.box };
";

    /// <summary>Live window dimensions, read in the isolated world (no_viewport headed mode).</summary>
    public const string ViewportJs = "(() => ({ width: window.innerWidth, height: window.innerHeight }))()";

    private static string Wrap(string selector, string op) =>
        "(() => {\n" + "const __SEL = " + IsolatedWorld.JsonEncode(selector) + ";\n" + ResolverBody + "\n" + op + "\n})()";

    public static string BuildBoxJs(string selector) => Wrap(selector, BoxOp);

    public static string BuildActionableJs(string selector) => Wrap(selector, ActionableOp);

    public static string BuildPointerJs(string selector, double x, double y)
    {
        string op =
            "const __el = __resolve(__SEL);\n" +
            "if (__el === 'UNSUPPORTED') return { r: 'unsupported' };\n" +
            "if (!__el) return { r: 'not_found' };\n" +
            "const __t = document.elementFromPoint(" +
                x.ToString(CultureInfo.InvariantCulture) + ", " + y.ToString(CultureInfo.InvariantCulture) + ");\n" +
            "if (!__t) return { r: 'ok', hit: false, covering: 'none' };\n" +
            "let __n = __t;\n" +
            "while (__n) { if (__n === __el) return { r: 'ok', hit: true }; __n = __n.parentNode; }\n" +
            "if (__el.contains(__t)) return { r: 'ok', hit: true };\n" +
            "return { r: 'ok', hit: false, covering: __t.tagName || 'unknown' };\n";
        return Wrap(selector, op);
    }

    // -----------------------------------------------------------------------
    // Typed reads (each: evaluate in the world, parse; any throw -> Unsupported)
    // -----------------------------------------------------------------------

    private static (StealthStatus Status, JsonElement? Data) Classify(JsonElement? raw)
    {
        if (raw == null || raw.Value.ValueKind != JsonValueKind.Object) return (StealthStatus.Unsupported, null);
        if (!raw.Value.TryGetProperty("r", out var r) || r.ValueKind != JsonValueKind.String)
            return (StealthStatus.Unsupported, null);
        return r.GetString() switch
        {
            "ok" => (StealthStatus.Ok, raw),
            "not_found" => (StealthStatus.NotFound, null),
            _ => (StealthStatus.Unsupported, null),
        };
    }

    private static async Task<(StealthStatus Status, JsonElement? Data)> EvalAsync(IsolatedWorld world, string expr)
    {
        try { return Classify(await world.EvaluateAsync(expr).ConfigureAwait(false)); }
        catch (Exception) { return (StealthStatus.Unsupported, null); }
    }

    public static async Task<(StealthStatus Status, BoundingBox? Box)> BoxAsync(IsolatedWorld world, string selector)
    {
        var (status, data) = await EvalAsync(world, BuildBoxJs(selector)).ConfigureAwait(false);
        if (status != StealthStatus.Ok) return (status, null);
        var b = data!.Value.GetProperty("box");
        return (status, new BoundingBox(
            b.GetProperty("x").GetDouble(), b.GetProperty("y").GetDouble(),
            b.GetProperty("width").GetDouble(), b.GetProperty("height").GetDouble()));
    }

    private static BoundingBox? ParseBox(JsonElement data)
    {
        if (!data.TryGetProperty("box", out var b) || b.ValueKind != JsonValueKind.Object) return null;
        return new BoundingBox(
            b.GetProperty("x").GetDouble(), b.GetProperty("y").GetDouble(),
            b.GetProperty("width").GetDouble(), b.GetProperty("height").GetDouble());
    }

    public static async Task<(StealthStatus Status, bool Visible, bool Enabled, bool Editable, BoundingBox? Box)> ActionableAsync(
        IsolatedWorld world, string selector)
    {
        var (status, data) = await EvalAsync(world, BuildActionableJs(selector)).ConfigureAwait(false);
        if (status != StealthStatus.Ok) return (status, false, false, false, null);
        return (status,
            data!.Value.GetProperty("visible").GetBoolean(),
            data.Value.GetProperty("enabled").GetBoolean(),
            data.Value.GetProperty("editable").GetBoolean(),
            ParseBox(data.Value));
    }

    private const string IsInputOp = @"
const __el = __resolve(__SEL);
if (__el === 'UNSUPPORTED') return { r: 'unsupported' };
if (!__el) return { r: 'not_found' };
const __tag = __el.tagName.toLowerCase();
return { r: 'ok', value: (__tag === 'input' || __tag === 'textarea' || __el.getAttribute('contenteditable') === 'true') };
";

    private const string IsFocusedOp = @"
const __el = __resolve(__SEL);
if (__el === 'UNSUPPORTED') return { r: 'unsupported' };
if (!__el) return { r: 'not_found' };
return { r: 'ok', value: (__el === document.activeElement) };
";

    private static async Task<(StealthStatus Status, bool Value)> BoolReadAsync(IsolatedWorld world, string js)
    {
        var (status, data) = await EvalAsync(world, js).ConfigureAwait(false);
        if (status != StealthStatus.Ok) return (status, false);
        return (status, data!.Value.TryGetProperty("value", out var v) && v.ValueKind == JsonValueKind.True);
    }

    /// <summary>Whether the resolved element is an input/textarea/contenteditable.</summary>
    public static Task<(StealthStatus Status, bool Value)> IsInputAsync(IsolatedWorld world, string selector) =>
        BoolReadAsync(world, Wrap(selector, IsInputOp));

    /// <summary>Whether the resolved element is the active element.</summary>
    public static Task<(StealthStatus Status, bool Value)> IsFocusedAsync(IsolatedWorld world, string selector) =>
        BoolReadAsync(world, Wrap(selector, IsFocusedOp));

    public static async Task<(StealthStatus Status, bool Hit, string Covering)> PointerAsync(
        IsolatedWorld world, string selector, double x, double y)
    {
        var (status, data) = await EvalAsync(world, BuildPointerJs(selector, x, y)).ConfigureAwait(false);
        if (status != StealthStatus.Ok) return (status, false, "unknown");
        bool hit = data!.Value.TryGetProperty("hit", out var h) && h.ValueKind == JsonValueKind.True;
        string covering = data.Value.TryGetProperty("covering", out var c) && c.ValueKind == JsonValueKind.String
            ? c.GetString()! : "unknown";
        return (status, hit, covering);
    }
}
