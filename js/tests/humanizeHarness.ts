/**
 * Test page and helpers for the real-browser humanize tests (JS).
 *
 * The page logs every input event into window.__log and main-world DOM reads
 * into window.__mainWorldHits. It is served from 127.0.0.1 so its iframe is
 * same-origin. Same page as tests/test_humanize_engine.py and the .NET tests.
 */

import http from 'node:http';
import type { AddressInfo } from 'node:net';

/** Fast, deterministic humanize settings (same code paths, no long sleeps). */
export const FAST = {
  mistype_chance: 0,
  field_switch_delay: [0, 0] as [number, number],
  typing_delay: 5,
  typing_delay_spread: 0,
  typing_pause_chance: 0,
  key_hold: [5, 5] as [number, number],
  shift_down_delay: [5, 5] as [number, number],
  shift_up_delay: [5, 5] as [number, number],
  mouse_min_steps: 4,
  mouse_max_steps: 4,
  mouse_burst_pause: [0, 0] as [number, number],
  mouse_overshoot_chance: 0,
  click_aim_delay_input: [5, 5] as [number, number],
  click_aim_delay_button: [5, 5] as [number, number],
  click_hold_input: [20, 20] as [number, number],
  click_hold_button: [20, 20] as [number, number],
  idle_between_actions: false,
  scroll_pause_fast: [5, 5] as [number, number],
  scroll_pause_slow: [5, 5] as [number, number],
  scroll_settle_delay: [50, 50] as [number, number],
  scroll_pre_move_delay: [5, 5] as [number, number],
  scroll_overshoot_chance: 0,
};

const INDEX_HTML = `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>humanize fixture</title>
<script>
// Records DOM reads that only a main-world evaluate makes into window.__mainWorldHits.
(function () {
  const hits = [];
  window.__mainWorldHits = hits;
  const note = (probe, detail) => hits.push({ probe, detail: String(detail ?? '') });

  const origGetAttribute = Element.prototype.getAttribute;
  Element.prototype.getAttribute = function (name) {
    if (name === 'contenteditable') note('getAttribute(contenteditable)', this.id || this.tagName);
    return origGetAttribute.call(this, name);
  };

  const activeDesc = Object.getOwnPropertyDescriptor(Document.prototype, 'activeElement');
  Object.defineProperty(Document.prototype, 'activeElement', {
    configurable: true,
    get() {
      note('document.activeElement', '');
      return activeDesc.get.call(this);
    },
  });

  const origFromPoint = Document.prototype.elementFromPoint;
  Document.prototype.elementFromPoint = function (x, y) {
    note('elementFromPoint', x + ',' + y);
    return origFromPoint.call(this, x, y);
  };

  const origQS = Document.prototype.querySelector;
  Document.prototype.querySelector = function (sel) {
    note('document.querySelector', sel);
    return origQS.call(this, sel);
  };
})();
</script>
<script>
// Records every input event (capture phase) into window.__log.
(function () {
  const log = [];
  window.__log = log;
  window.__reset = () => { log.length = 0; };

  const TYPES = [
    'pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click', 'dblclick',
    'contextmenu', 'auxclick', 'mousemove', 'keydown', 'keyup', 'beforeinput',
    'input', 'wheel', 'focus',
  ];
  const idOf = (el) => {
    if (el === window) return 'window';
    if (!el || el === document) return 'document';
    return el.id || (el.tagName ? el.tagName.toLowerCase() : '?');
  };
  for (const type of TYPES) {
    document.addEventListener(type, (e) => {
      const rec = { t: type, ts: e.timeStamp, trusted: e.isTrusted, target: idOf(e.target) };
      if ('clientX' in e) { rec.x = e.clientX; rec.y = e.clientY; }
      if ('button' in e) rec.button = e.button;
      if ('detail' in e && type !== 'focus') rec.detail = e.detail;
      if ('key' in e) { rec.key = e.key; rec.code = e.code; }
      if ('shiftKey' in e) {
        rec.shift = e.shiftKey; rec.ctrl = e.ctrlKey; rec.meta = e.metaKey; rec.alt = e.altKey;
      }
      if ('inputType' in e) { rec.inputType = e.inputType; rec.data = e.data; }
      if (type === 'wheel') { rec.dx = e.deltaX; rec.dy = e.deltaY; }
      log.push(rec);
    }, true);
  }
  window.addEventListener('scroll', () => {
    log.push({ t: 'scroll', ts: performance.now(), sx: scrollX, sy: scrollY });
  }, true);

})();
</script>
<style>
  body { margin: 0; font: 14px sans-serif; }
  section { padding: 8px 12px; border-bottom: 1px solid #ddd; }
  input, select, button, textarea { font: inherit; margin: 2px 6px 2px 0; }
  button { min-width: 140px; min-height: 36px; }
  #neg { position: absolute; top: -600px; left: -600px; }
  .wrap { position: relative; display: inline-block; }
  .over { position: absolute; inset: 0; background: rgba(255,0,0,.3); }
</style>
</head>
<body>
<section id="text">
  <h4>Text inputs</h4>
  <input id="name" value="firstname">
  <input id="long" value="hello world">
  <!-- Masked field: the page strips anything that is not hex (card/IBAN/serial-style mask). -->
  <input id="hex" oninput="this.value=this.value.replace(/[^0-9a-f]/gi,'')">
  <textarea id="ta">old text</textarea>
</section>
<section id="special">
  <h4>Non-text inputs</h4>
  <input id="date" type="date">
  <input id="range" type="range" min="0" max="100" value="10">
  <input id="color" type="color" value="#000000">
</section>
<section id="focus">
  <h4>Focus targets</h4>
  <input id="fa" placeholder="A (focused first)">
  <input id="fb" placeholder="B (handle target)">
</section>
<section id="buttons">
  <h4>Buttons</h4>
  <button id="btn">Press me</button>
  <button class="dup" id="dup1">Duplicate</button>
  <button class="dup" id="dup2">Duplicate</button>
  <input id="chk" type="checkbox">
  <select id="sel"><option value="a">a</option><option value="b">b</option></select>
</section>
<section id="covered-sec">
  <h4>Covered button (transparent overlay on top)</h4>
  <span class="wrap"><button id="covered">covered</button><div class="over" id="over"></div></span>
</section>
<input id="neg" name="neg">
<canvas id="cv" width="200" height="40" style="border:1px solid #999"></canvas>
<section id="frames">
  <h4>Frame</h4>
  <iframe id="frame" name="f" src="frame.html" style="width:420px;height:200px"></iframe>
</section>
<div style="height:200px"></div>
</body>
</html>
`;

const FRAME_HTML = `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<script>
// Records DOM reads that only a main-world evaluate makes into window.__mainWorldHits.
(function () {
  const hits = [];
  window.__mainWorldHits = hits;
  const note = (probe, detail) => hits.push({ probe, detail: String(detail ?? '') });

  const origGetAttribute = Element.prototype.getAttribute;
  Element.prototype.getAttribute = function (name) {
    if (name === 'contenteditable') note('getAttribute(contenteditable)', this.id || this.tagName);
    return origGetAttribute.call(this, name);
  };

  const activeDesc = Object.getOwnPropertyDescriptor(Document.prototype, 'activeElement');
  Object.defineProperty(Document.prototype, 'activeElement', {
    configurable: true,
    get() {
      note('document.activeElement', '');
      return activeDesc.get.call(this);
    },
  });

  const origFromPoint = Document.prototype.elementFromPoint;
  Document.prototype.elementFromPoint = function (x, y) {
    note('elementFromPoint', x + ',' + y);
    return origFromPoint.call(this, x, y);
  };

  const origQS = Document.prototype.querySelector;
  Document.prototype.querySelector = function (sel) {
    note('document.querySelector', sel);
    return origQS.call(this, sel);
  };
})();
</script>
<script>
// Records every input event (capture phase) into window.__log.
(function () {
  const log = [];
  window.__log = log;
  window.__reset = () => { log.length = 0; };

  const TYPES = [
    'pointerdown', 'pointerup', 'mousedown', 'mouseup', 'click', 'dblclick',
    'contextmenu', 'auxclick', 'mousemove', 'keydown', 'keyup', 'beforeinput',
    'input', 'wheel', 'focus',
  ];
  const idOf = (el) => {
    if (el === window) return 'window';
    if (!el || el === document) return 'document';
    return el.id || (el.tagName ? el.tagName.toLowerCase() : '?');
  };
  for (const type of TYPES) {
    document.addEventListener(type, (e) => {
      const rec = { t: type, ts: e.timeStamp, trusted: e.isTrusted, target: idOf(e.target) };
      if ('clientX' in e) { rec.x = e.clientX; rec.y = e.clientY; }
      if ('button' in e) rec.button = e.button;
      if ('detail' in e && type !== 'focus') rec.detail = e.detail;
      if ('key' in e) { rec.key = e.key; rec.code = e.code; }
      if ('shiftKey' in e) {
        rec.shift = e.shiftKey; rec.ctrl = e.ctrlKey; rec.meta = e.metaKey; rec.alt = e.altKey;
      }
      if ('inputType' in e) { rec.inputType = e.inputType; rec.data = e.data; }
      if (type === 'wheel') { rec.dx = e.deltaX; rec.dy = e.deltaY; }
      log.push(rec);
    }, true);
  }
  window.addEventListener('scroll', () => {
    log.push({ t: 'scroll', ts: performance.now(), sx: scrollX, sy: scrollY });
  }, true);

})();
</script>
<style>
  body { margin: 0; font: 14px sans-serif; }
  .wrap { position: relative; display: inline-block; }
  .over { position: absolute; inset: 0; background: rgba(255,0,0,.3); }
</style>
</head>
<body>
<input id="finput" value="old">
<span class="wrap"><button id="fcovered">covered</button><div class="over" id="fover"></div></span>
<div style="height:1200px"></div>
<button id="fbottom">bottom</button>
</body>
</html>
`;

const PAGES: Record<string, string> = { '/index.html': INDEX_HTML, '/frame.html': FRAME_HTML };

export async function startServer(): Promise<{ url: string; close: () => Promise<void> }> {
  const srv = http.createServer((req, res) => {
    const body = PAGES[(req.url ?? '/').split('?')[0]];
    res.writeHead(body ? 200 : 404, { 'content-type': 'text/html; charset=utf-8' });
    res.end(body ?? '');
  });
  await new Promise<void>((r) => srv.listen(0, '127.0.0.1', r));
  const { port } = srv.address() as AddressInfo;
  return { url: `http://127.0.0.1:${port}/`, close: () => new Promise((r) => srv.close(() => r())) };
}

/** Recorded input events, optionally filtered by type. */
export async function events(target: any, ...types: string[]): Promise<any[]> {
  const log: any[] = await target.evaluate('window.__log.slice()');
  return types.length ? log.filter((e) => types.includes(e.t)) : log;
}

export async function reset(target: any): Promise<void> {
  await target.evaluate('window.__reset(); window.__mainWorldHits.length = 0');
}

export async function value(target: any, selector: string): Promise<string> {
  return target.evaluate(
    (s: string) => { const e: any = document.querySelector(s); return e.isContentEditable ? e.textContent : e.value; },
    selector,
  );
}
