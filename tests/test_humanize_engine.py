"""Behaviour tests for the unified humanize engine (real browser, fast config).

These replace the old mock-based tests that asserted on internals of the
previous implementation (private helpers, call forwarding into Playwright).
Every test here drives the real CloakBrowser binary headless against a small
local page (served below; it records every input event the page observes)
with near-zero delays, so the whole file runs in well under a minute.
"""

from __future__ import annotations

import http.server
import socketserver
import sys
import threading
import time
import urllib.parse
from typing import Any

import pytest
from playwright.sync_api import Error, TimeoutError

# Fast, deterministic humanize settings: same code paths, no long sleeps, no
# random typos. Tests that need specific behaviour override per context/call.
FAST: dict[str, Any] = {
    "mistype_chance": 0.0,
    "field_switch_delay": (0, 0),
    "typing_delay": 5,
    "typing_delay_spread": 0,
    "typing_pause_chance": 0.0,
    "key_hold": (5, 5),
    "shift_down_delay": (5, 5),
    "shift_up_delay": (5, 5),
    "mouse_min_steps": 4,
    "mouse_max_steps": 4,
    "mouse_overshoot_chance": 0.0,
    "click_aim_delay_input": (5, 5),
    "click_aim_delay_button": (5, 5),
    "click_hold_input": (20, 20),
    "click_hold_button": (20, 20),
    "idle_between_actions": False,
    "scroll_pause_fast": (5, 5),
    "scroll_pause_slow": (5, 5),
    "scroll_settle_delay": (50, 50),
    "scroll_pre_move_delay": (5, 5),
    "scroll_overshoot_chance": 0.0,
}

# Test page: recorder (window.__log), main-world probes (window.__mainWorldHits),
# inputs of every kind, a covered button, an off-screen input and an iframe.
INDEX_HTML = """<!doctype html>
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
  <!-- Masked field: the page strips anything that is not hex (card/IBAN/serial-style mask). -->
  <input id="hex" oninput="this.value=this.value.replace(/[^0-9a-f]/gi,'')">
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
"""

FRAME_HTML = """<!doctype html>
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
"""

_PAGES = {"/index.html": INDEX_HTML, "/frame.html": FRAME_HTML}


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = _PAGES.get(self.path.split("?")[0])
        self.send_response(200 if body else 404)
        self.send_header("content-type", "text/html; charset=utf-8")
        self.end_headers()
        if body:
            self.wfile.write(body.encode())

    def log_message(self, *args: Any) -> None:  # pragma: no cover
        pass


class SiteServer:
    """Serve the test pages on 127.0.0.1 with a random port (the iframe must be same-origin)."""

    def __init__(self) -> None:
        self._srv = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
        self._srv.daemon_threads = True
        self.url = f"http://127.0.0.1:{self._srv.server_address[1]}/"
        threading.Thread(target=self._srv.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._srv.shutdown()
        self._srv.server_close()


def events(target: Any, *types: str) -> list[dict]:
    """Recorded input events, optionally filtered by type."""
    log = target.evaluate("window.__log.slice()")
    return [e for e in log if not types or e["t"] in types]


def reset(target: Any) -> None:
    target.evaluate("window.__reset(); window.__mainWorldHits.length = 0")


def value(target: Any, selector: str) -> str:
    return target.evaluate(
        "s => { const e = document.querySelector(s);"
        " return e.isContentEditable ? e.textContent : e.value; }",
        selector,
    )

pytestmark = [pytest.mark.timeout(120), pytest.mark.real_browser]


@pytest.fixture(scope="module")
def site():
    srv = SiteServer()
    yield srv
    srv.close()


@pytest.fixture(scope="module")
def browser(site):
    from cloakbrowser import launch

    b = launch(headless=True, humanize=True, human_config=FAST)
    yield b
    b.close()


@pytest.fixture
def page(browser, site):
    p = browser.new_page()
    p.goto(site.url + "index.html")
    yield p
    p.close()


def frame(p):
    f = p.frame(name="f")
    f.wait_for_load_state()
    return f


# --- wiring ---------------------------------------------------------------

def test_page_is_humanized_and_keeps_compat_attributes(page):
    assert page._human_cfg.mistype_chance == 0.0
    assert page._human_cursor.initialized
    assert page._stealth_world.evaluate("1 + 1") == 2
    page._original.click("#btn")  # raw Playwright still reachable


def test_unknown_keyword_still_raises_type_error(page):
    with pytest.raises(TypeError):
        page.click("#btn", no_such_option=True)


# --- pointer actions --------------------------------------------------------

def test_click_moves_along_a_curve_then_presses(page):
    reset(page)
    page.click("#btn")
    moves = events(page, "mousemove")
    clicks = [e["target"] for e in events(page, "click")]
    assert len(moves) >= 3 and clicks == ["btn"]


def test_click_options(page):
    reset(page)
    page.click("#btn", button="right", modifiers=["Shift"])
    down = events(page, "mousedown")[-1]
    assert down["button"] == 2 and down["shift"] is True
    reset(page)
    page.click("#btn", click_count=2)
    assert len(events(page, "dblclick")) == 1
    reset(page)
    page.click("#btn", trial=True)
    assert events(page, "click") == []


def test_hover_does_not_press(page):
    reset(page)
    page.hover("#btn")
    assert events(page, "mousedown") == [] and events(page, "mousemove")


def test_hover_holds_modifiers_during_the_move(page):
    page.hover("#chk")
    reset(page)
    page.hover("#btn", modifiers=["Shift"])
    seq = events(page, "mousemove", "keydown", "keyup")
    moves = [i for i, e in enumerate(seq) if e["t"] == "mousemove"]
    assert moves and all(seq[i]["shift"] for i in moves)
    assert seq[0]["t"] == "keydown" and seq[-1]["t"] == "keyup"
    assert events(page, "mousedown") == []


def test_dblclick_matches_a_real_double_click(page):
    reset(page)
    page.dblclick("#btn")
    seq = [(e["t"], e["detail"]) for e in events(page, "mousedown", "click", "dblclick")]
    assert seq == [("mousedown", 1), ("click", 1), ("mousedown", 2), ("click", 2), ("dblclick", 2)]


def test_covered_element_times_out_with_reason(page):
    with pytest.raises(TimeoutError, match="intercepts pointer events"):
        page.click("#covered", timeout=1000)


def test_strict_mode_violation(page):
    with pytest.raises(Error, match="strict mode violation"):
        page.locator(".dup").click(timeout=1000)
    page.locator(".dup").first.click()  # explicit choice is fine


def test_page_default_timeout_and_zero(page):
    page.set_default_timeout(500)
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        page.click("#missing")
    assert time.monotonic() - t0 < 1.5
    page.click("#btn", timeout=0)


def test_standard_locators(page):
    page.get_by_role("button", name="Press me").click()
    page.locator("#buttons").locator("#btn").click()
    page.locator("button").filter(has_text="Press me").click()
    page.click("#btn:visible")


# --- keyboard ---------------------------------------------------------------

def test_fill_replaces_and_type_appends(page):
    page.fill("#name", "Shaho")
    assert value(page, "#name") == "Shaho"
    page.locator("#name").press_sequentially("!")
    assert value(page, "#name") == "Shaho!"
    page.locator("#name").clear()
    assert value(page, "#name") == ""


def test_value_inputs_are_operated_like_a_person(page):
    """date/time editors are typed segment by segment, sliders clicked and
    nudged with arrows, dropdowns opened and moved with arrow keys. Every
    input/change event the page sees is trusted (no programmatic value)."""
    page.evaluate("""() => { window.__untrusted = 0;
        for (const t of ['input', 'change'])
            document.addEventListener(t, e => { if (!e.isTrusted) __untrusted++; }, true); }""")
    page.fill("#date", "2024-01-31")
    page.fill("#date", "1999-12-05")
    page.fill("#range", "80")
    assert page.select_option("#sel", "b") == ["b"]
    assert (value(page, "#date"), value(page, "#range"), value(page, "#sel")) == ("1999-12-05", "80", "b")
    assert page.evaluate("__untrusted") == 0
    with pytest.raises(Error, match="native colour picker"):
        page.fill("#color", "#ff0000")
    with pytest.raises(Error, match="cannot be filled"):
        page.fill("#chk", "x")


def test_unreachable_element_is_not_focused_programmatically(page):
    """#neg sits at (-600, -600): no scroll can reach it, so a person could
    not click it. No hidden focus() -- a clear timeout instead."""
    with pytest.raises(TimeoutError, match="outside of the viewport"):
        page.fill("#neg", "x", timeout=1500)
    assert value(page, "#neg") == ""


def test_press_focuses_target_first(page):
    page.focus("#fa")
    page.query_selector("#fb").press("x")
    assert (value(page, "#fa"), value(page, "#fb")) == ("", "x")


def test_handle_sharing_its_box_with_a_child_acts_on_the_focusable_one(page):
    """A wrapper and its same-size child form one nested chain. The handle acts on
    the element a real click would focus (the focusable wrapper), not the child."""
    page.evaluate("""() => document.body.insertAdjacentHTML('beforeend',
        '<div id="wrap" tabindex="0" style="display:inline-block"><span id="inner"'
        + ' style="display:block;width:80px;height:20px">x</span></div>')""")
    page.evaluate("() => { window.__kd = []; document.addEventListener('keydown',"
                  " e => __kd.push(e.target.id + ':' + e.key)); }")
    page.query_selector("#wrap").press("a")
    assert page.evaluate("() => __kd") == ["wrap:a"]


def test_stale_handle_after_navigation_fails_fast(page, site):
    """A handle from a previous document raises "not attached" at once, like
    Playwright, instead of waiting out the timeout. A same-document navigation
    keeps the element, so its handle keeps working."""
    h = page.query_selector("#btn")
    h.click()
    page.evaluate("() => history.pushState({}, '', '#spa')")
    h.click()
    page.goto(site.url + "index.html?second")
    page.click("#chk")
    t = time.monotonic()
    with pytest.raises(Error, match="not attached"):
        h.click(timeout=10000)
    assert time.monotonic() - t < 5


def test_handle_click_on_same_box_nesting(page):
    """Common markup where parent and child share a border box: a block link
    wrapping a same-size image, and a list item filled by its link."""
    page.evaluate("""() => { document.body.insertAdjacentHTML('beforeend',
        '<a id="card" href="#c" style="display:block;width:60px"><img id="thumb" width="60" height="60"'
        + ' style="display:block" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"></a>'
        + '<ul style="width:200px;padding:0;margin:0;list-style:none"><li id="li"><a id="nav" href="#n"'
        + ' style="display:block">nav</a></li></ul>');
        window.__clicks = []; document.addEventListener('click', e => { __clicks.push(e.target.id); e.preventDefault(); }); }""")
    page.query_selector("#card").click()
    page.query_selector("#nav").click()
    page.query_selector("#li").click()
    assert page.evaluate("() => __clicks") == ["thumb", "nav", "nav"]


def test_handle_sharing_its_box_with_an_unrelated_element_raises(page):
    """Two unrelated elements stacked on the same box cannot be told apart by the
    box alone: the handle action raises instead of guessing."""
    page.evaluate("""() => document.body.insertAdjacentHTML('beforeend',
        '<div style="position:relative;width:80px;height:20px">'
        + '<span id="s1" style="position:absolute;inset:0"></span>'
        + '<span id="s2" style="position:absolute;inset:0"></span></div>')""")
    with pytest.raises(Error, match="shares its box"):
        page.query_selector("#s1").click()


def test_handle_reads_of_hidden_or_same_box_elements(page):
    """A handle read needs the handle's own element: hidden (no box) and same-box
    handles run Playwright's own read at once; a unique visible one reads in the
    isolated world."""
    page.evaluate("""() => {
        document.head.insertAdjacentHTML('beforeend', '<meta name="csrf" content="tok123">');
        document.body.insertAdjacentHTML('beforeend', '<input id="hid" type="hidden" value="secret">'
            + '<div id="outer" style="width:90px;height:30px"><div id="inner" style="width:90px;height:30px"></div></div>'
            + '<p id="uniq" data-x="shown">u</p>'); }""")
    t = time.monotonic()
    assert page.query_selector('meta[name="csrf"]').get_attribute("content") == "tok123"
    assert page.query_selector("#hid").input_value() == "secret"
    assert time.monotonic() - t < 5
    assert page.query_selector("#inner").get_attribute("id") == "inner"
    assert page.query_selector("#outer").get_attribute("id") == "outer"
    assert page.query_selector("#uniq").get_attribute("data-x") == "shown"


def test_dispatch_event_with_a_js_handle_in_event_init(page):
    """Playwright's documented drag pattern: the DataTransfer handle lives in the
    page's main world, so the dispatch runs Playwright's own call."""
    page.evaluate("""() => { window.__dt = [];
        document.addEventListener('dragstart', e => __dt.push(e.dataTransfer instanceof DataTransfer)); }""")
    dt = page.evaluate_handle("() => new DataTransfer()")
    page.dispatch_event("#btn", "dragstart", {"dataTransfer": dt})
    page.locator("#btn").dispatch_event("dragstart", {"dataTransfer": dt})
    assert page.evaluate("() => __dt") == [True, True]


def test_press_and_type_reach_non_focusable_targets(page):
    """A <canvas> (or a game area with document-level key handlers) does not take
    focus. press()/type() click it and send the keys anyway, like Playwright."""
    page.evaluate("() => { window.__keys = []; document.addEventListener('keydown', e => __keys.push(e.key)); }")
    page.press("#cv", "ArrowUp")
    page.type("#cv", "ab")
    assert page.evaluate("__keys") == ["ArrowUp", "a", "b"]


def test_press_delay_is_forwarded(page):
    reset(page)
    page.press("#name", "a", delay=150)
    ev = events(page, "keydown", "keyup")
    assert ev[-1]["ts"] - ev[-2]["ts"] >= 120


def test_mistypes_are_corrected_and_skip_masked_fields(browser, site):
    p = browser.new_page()
    p.goto(site.url + "index.html")
    try:
        p.fill("#name", "Hello", human_config={"mistype_chance": 1.0})
        assert value(p, "#name") == "Hello"
        p.fill("#hex", "ab", human_config={"mistype_chance": 1.0})
        assert value(p, "#hex") == "ab"
        reset(p)
        p.locator("#name").press_sequentially("AB", human_config={"mistype_chance": 1.0})
        assert all(e["shift"] for e in events(p, "keydown")
                   if len(e["key"]) == 1 and e["key"].isupper())
    finally:
        p.close()


def test_scroll_overshoot_wheels_back(page):
    page.set_viewport_size({"width": 800, "height": 300})
    reset(page)
    page.click("#chk", human_config={"scroll_overshoot_chance": 1.0, "scroll_overshoot_px": (120, 120)})
    dys = [e["dy"] for e in events(page, "wheel")]
    assert any(d > 0 for d in dys) and any(d < 0 for d in dys), dys
    assert [e["target"] for e in events(page, "click")] == ["chk"]
    reset(page)
    page.evaluate("scrollTo(0, 0)")
    page.click("#chk", human_config={"scroll_overshoot_chance": 0.0})
    assert all(e["dy"] > 0 for e in events(page, "wheel"))


def test_wheel_events_are_whole_notches(page):
    """CDP reports every wheel event as one notch (wheelDeltaY = 120), so the
    page-visible deltaY must be a whole notch of the persona's platform too;
    a 20-40 px chunk with wheelDeltaY 120 is something no wheel produces."""
    page.set_viewport_size({"width": 800, "height": 300})
    page.evaluate("""() => { window.__wh = []; document.addEventListener('wheel',
        e => __wh.push([e.deltaY, e.wheelDeltaY]), { capture: true, passive: true }); }""")
    page.click("#chk", human_config={"scroll_notch_px": 0})
    wheels = page.evaluate("__wh")
    assert wheels
    plat = page.evaluate("navigator.platform").lower()
    notch = 40 if plat.startswith("mac") else 100 if plat.startswith("win") else 120
    assert {abs(dy) for dy, _ in wheels} == {notch}, wheels
    assert all(dy * wdy < 0 for dy, wdy in wheels)


def test_typing_uses_human_key_timing(browser, site):
    """Default timings: keys held ~100 ms, the next key often down before the
    previous one is up, Shift usually let go first; never a key down twice."""
    p = browser.new_page()
    p.goto(site.url + "index.html")
    try:
        text = "The Quick brown fox jumps over the lazy dog"
        p.fill("#name", text, human_config={"key_hold": (60, 175), "typing_delay": 150,
                                            "typing_delay_spread": 70, "typing_pause_chance": 0,
                                            "shift_down_delay": (60, 220), "shift_up_delay": (-60, 30)})
        assert value(p, "#name") == text
        down: dict = {}
        holds, rolled, pairs, last = [], 0, 0, None
        for e in events(p, "keydown", "keyup"):
            if e["t"] == "keydown":
                assert e["code"] not in down, e
                down[e["code"]] = e["ts"]
                if last is not None and e["key"] != "Shift":
                    pairs += 1
                    rolled += last in down
                if e["key"] != "Shift":
                    last = e["code"]
            else:
                holds.append(e["ts"] - down.pop(e["code"]))
        assert not down
        holds.sort()
        assert 70 <= holds[len(holds) // 2] <= 140, holds
        assert rolled > 0, "no rollover at all"
    finally:
        p.close()



def test_same_key_lower_then_upper_never_repeats(browser, site):
    """"xX": the capital's key must not go down while the lower-case press of
    the same physical key is still held (a keydown with repeat=true). Same for
    a digit and its shift symbol ("1!")."""
    p = browser.new_page()
    p.goto(site.url + "index.html")
    try:
        p.evaluate("""() => { window.__kd = []; for (const t of ['keydown', 'keyup'])
            document.addEventListener(t, e => __kd.push([t, e.code, e.repeat]), true); }""")
        text = "xX aA zZ 1! qQ"
        cfg = {"key_hold": (60, 175), "typing_delay": 150, "typing_delay_spread": 70,
               "typing_pause_chance": 0, "shift_down_delay": (60, 220), "shift_up_delay": (-60, 30)}
        for _ in range(3):
            p.fill("#name", text, human_config=cfg)
            assert value(p, "#name") == text
        log = p.evaluate("__kd")
        assert not [e for e in log if e[2]], [e for e in log if e[2]]
        held = set()
        for t, code, _ in log:
            if t == "keydown":
                assert code not in held, (code, log)
                held.add(code)
            else:
                held.discard(code)
    finally:
        p.close()

def test_moves_never_report_zero_movement(page):
    page.evaluate("""() => { window.__mm = []; document.addEventListener('mousemove',
        e => __mm.push([e.movementX, e.movementY]), true); }""")
    page.hover("#btn")
    page.hover("#chk")
    mm = page.evaluate("__mm")
    assert mm and not [m for m in mm[1:] if m == [0, 0]], mm


# --- containing-block-aware scroller (#593) ----------------------------------

_CB_CSS = """<!doctype html><style>
  body { margin: 0 } header { height: 215px }
  .content { height: 300px; overflow: auto } .tall { height: 2000px }
  button { width: 44px; height: 44px }
</style><header>header</header>"""

_CB_CASES = {
    # renders on screen, outside the scroller's scrollport: no scrolling
    "fixed_modal": ("""<div class="content"><div class="tall">
        <div style="position: fixed; inset: 0; background: rgba(0,0,0,.4)">
        <button id="t" style="position: absolute; top: 146px; right: 36px">X</button></div></div></div>""", False),
    "absolute_escapes_static_scroller": ("""<div style="position: relative">
        <div class="content"><div class="tall">
        <button id="t" style="position: absolute; top: 320px; left: 10px">X</button></div></div></div>""", False),
    # still clipped by the scroller: must be wheeled into view first
    "normal_child_below_fold": ("""<div class="content"><div class="tall">
        <div style="height: 1500px"></div><button id="t">X</button></div></div>""", True),
    "absolute_in_positioned_scroller": ("""<div class="content" style="position: relative"><div class="tall">
        <button id="t" style="position: absolute; top: 1500px; left: 10px">X</button></div></div>""", True),
    "fixed_in_transformed_scroller": ("""<div class="content" style="transform: translateZ(0)"><div class="tall">
        <button id="t" style="position: fixed; top: 1500px; left: 10px">X</button></div></div>""", True),
}


@pytest.mark.parametrize("name", list(_CB_CASES))
def test_scroller_follows_the_containing_block_chain(page, name):
    """overflow clips only boxes whose containing block sits inside the
    scroller; a fixed modal that is a DOM child of a scrolling panel is on
    screen and must be clicked, not retried as 'outside of the viewport'."""
    body, clipped = _CB_CASES[name]
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("data:text/html," + urllib.parse.quote(_CB_CSS + body))
    page.evaluate("""() => { window.__clicks = 0;
        document.getElementById('t').addEventListener('click', () => __clicks++); }""")
    page.click("#t", timeout=5000)
    assert page.evaluate("__clicks") == 1
    scrolled = page.evaluate("document.querySelector('.content').scrollTop")
    assert (scrolled > 0) == clipped, scrolled


def test_per_call_human_config(page):
    reset(page)
    page.click("#btn", human_config={"click_hold_button": (300, 300)})
    assert events(page, "mouseup")[-1]["ts"] - events(page, "mousedown")[-1]["ts"] >= 250


# --- checkable / select -----------------------------------------------------

def test_check_uncheck_and_select(page):
    page.check("#chk")
    assert page.is_checked("#chk")
    page.locator("#chk").uncheck()
    assert not page.is_checked("#chk")
    page.query_selector("#chk").set_checked(True)
    assert page.is_checked("#chk")
    assert page.select_option("#sel", index=1) == ["b"]


COUNTRIES = ["Afghanistan", "Albania", "Chad", "Chile", "China", "Dominica", "Dominican Republic",
             "Guinea", "Guinea-Bissau", "Niger", "Nigeria", "\u00c5land Islands", "Aaland", "United Arab Emirates",
             "United Kingdom", "United States", "United States Minor Outlying Islands", "Zimbabwe"]


def _blink_typeahead(labels, enabled, start, typed):
    """Blink's TypeAhead::HandleEvent (kMatchPrefix | kCycleFirstChar) for one search."""
    import unicodedata

    def fold(t):
        return "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c)).lower()
    keys = [fold(l.lstrip()) if ok else "" for l, ok in zip(labels, enabled)]
    buf = rep = ""
    sel = start
    for ch in fold(typed):
        buf += ch
        if ch == rep:
            prefix, off = ch, 1
        else:
            prefix = buf
            off = 0 if len(buf) > 1 else 1
            rep = "" if len(buf) > 1 else ch
        i = (max(sel, 0) + off) % len(keys)
        for _ in keys:
            if keys[i] and keys[i].startswith(prefix):
                sel = i
                break
            i = (i + 1) % len(keys)
    return sel


def test_type_ahead_plan_lands_on_the_option_from_any_highlighted_row(page):
    """The plan must not depend on which row the open popup highlights (#580): it
    can sit under the OS pointer, and the page cannot read it."""
    page.evaluate("""(labels) => { const s = document.createElement('select'); s.id = 'ta';
        for (const l of labels) s.add(new Option(l));
        s.options[1].disabled = true; document.body.append(s); }""", COUNTRIES)
    enabled = [i != 1 for i in range(len(COUNTRIES))]
    human = page._impl_obj._cloak_human
    frame = page.main_frame._impl_obj

    async def plans():
        from cloakbrowser.human.engine import Target, _Deadline
        r = await human.resolve(Target(frame, "#ta"), _Deadline(5000))
        return [await human.worlds.call(frame, "typeAheadPlan", r.id, t, 3) for t in range(len(COUNTRIES))]
    for target, plan in enumerate(page._sync(plans())):
        if target == 1:
            assert plan is None  # disabled: not reachable
            continue
        assert plan and not plan.get("home"), (COUNTRIES[target], plan)
        for start in range(len(COUNTRIES)):
            row = _blink_typeahead(COUNTRIES, enabled, start, plan["typed"])
            step = 1 if plan["arrows"] > 0 else -1
            for _ in range(abs(plan["arrows"])):
                row += step
                while not enabled[row]:
                    row += step
            assert row == target, (COUNTRIES[target], plan, COUNTRIES[start])
    got = {COUNTRIES[t]: p for t, p in enumerate(page._sync(plans()))}
    assert got["Chile"] == {"typed": "chil", "arrows": 0}  # its own name, not "cha" + 1 arrow
    assert got["\u00c5land Islands"]["typed"] == "al"  # the browser folds accents: plain "al" finds it
    assert got["Aaland"]["typed"] == "aal"  # "aa" would cycle through the a's instead
    assert all(abs(p["arrows"]) <= 3 for p in got.values() if p)


def test_select_option_on_a_long_dropdown_types_ahead(page):
    """#581: no walk over every row, and the timeout bounds it."""
    page.evaluate("""() => { const s = document.createElement('select'); s.id = 'long';
        for (let i = 0; i < 205; i++) s.add(new Option('Country ' + String(i).padStart(3, '0'), 'v' + i));
        window.__sel = []; for (const t of ['input', 'change']) s.addEventListener(t, () => __sel.push(t));
        document.body.append(s); }""")
    reset(page)
    assert page.select_option("#long", "v150") == ["v150"]
    keys = [e["key"] for e in events(page, "keydown")]
    assert "ArrowDown" not in keys and len(keys) <= 13, keys
    sel = page.evaluate("__sel")
    # A macOS dropdown moves on every typed letter (one input/change each); elsewhere only Enter commits.
    assert sel[-2:] == ["input", "change"] and (sys.platform == "darwin" or len(sel) == 2), sel
    page.evaluate("document.querySelector('#long').selectedIndex = 0")
    with pytest.raises(TimeoutError):
        page.select_option("#long", "v200", timeout=200)


def test_select_option_on_emoji_labels(page):
    """Blink's type-ahead drops a typed emoji, so these options are reached with
    arrows; a macOS popup ignores arrows, so there it refuses."""
    page.evaluate("""() => { const s = document.createElement('select'); s.id = 'emoji';
        for (const [l, v] of [['Pick one', ''], ['\U0001F34E Apple', 'a'], ['\U0001F34C Banana', 'b'],
                              ['\U0001F352 Cherry', 'c']]) s.add(new Option(l, v));
        document.body.append(s); }""")
    if sys.platform == "darwin":
        with pytest.raises(Error, match="cannot be picked with human input"):
            page.select_option("#emoji", "c")
    else:
        assert page.select_option("#emoji", "c") == ["c"]


def test_select_option_that_navigates_the_page(page):
    """#597: a dropdown that submits its form on change; the pick still returns."""
    page.evaluate("""() => { const f = document.createElement('form'); f.method = 'get';
        const s = document.createElement('select'); s.id = 'nav'; s.name = 'city';
        for (const [l, v] of [['Amsterdam', 'a'], ['Berlin', 'b']]) s.add(new Option(l, v));
        s.onchange = () => f.submit(); f.append(s); document.body.prepend(f); }""")
    assert page.select_option("#nav", "b") == ["b"]
    page.wait_for_url("**city=b")


# --- frames and handles ------------------------------------------------------

def test_frame_actions(page):
    f = frame(page)
    f.fill("#finput", "in frame")
    assert value(f, "#finput") == "in frame"
    page.frame_locator("#frame").locator("#finput").press_sequentially("!")
    assert value(f, "#finput") == "in frame!"
    reset(f)
    f.click("#fbottom", timeout=5000)
    assert [e["target"] for e in events(f, "click")] == ["fbottom"]
    # The frame was scrolled to its bottom above; wheeling back up takes time.
    with pytest.raises(TimeoutError, match="intercepts pointer events"):
        f.click("#fcovered", timeout=4000)


def test_element_handle_actions(page):
    h = page.query_selector("#name")
    h.fill("handle")
    assert value(page, "#name") == "handle"
    reset(page)
    page.query_selector("#btn").click()
    assert [e["target"] for e in events(page, "click")] == ["btn"]


def test_mouse_api(page):
    reset(page)
    page.mouse.move(50, 50, steps=1)
    assert len(events(page, "mousemove")) == 1
    box = page.locator("#btn").bounding_box()
    reset(page)
    page.mouse.click(box["x"] + 5, box["y"] + 5, button="right")
    assert [e["button"] for e in events(page, "mousedown")] == [2]


# --- separate browser processes -----------------------------------------------
# Sync Playwright allows one driver per thread, and the module browser above
# owns this one; these scenarios each run in a fresh interpreter.

_PRELUDE = """
import asyncio, sys
sys.path.insert(0, {root!r})
from tests.test_humanize_engine import FAST
URL = {url!r}
"""

_SCENARIOS = {
    "non_humanized_untouched": """
from cloakbrowser import launch
b = launch(headless=True)
p = b.new_page(); p.goto(URL + "index.html")
assert not hasattr(p, "_original")
p.click("#btn"); p.fill("#name", "plain")
assert p.evaluate("document.querySelector('#name').value") == "plain"
b.close()
""",
    "select_all_follows_persona": """
from cloakbrowser import launch
b = launch(headless=True, humanize=True, human_config=FAST, args=["--fingerprint-platform=macos"])
p = b.new_page(); p.goto(URL + "index.html")
assert p.evaluate("navigator.platform") == "MacIntel"
p.fill("#name", "Mac")
assert p.evaluate("document.querySelector('#name').value") == "Mac"
b.close()
""",
    "async_api": """
from cloakbrowser import launch_async
from playwright.async_api import Error
async def main():
    b = await launch_async(headless=True, humanize=True, human_config=FAST)
    try:
        p = await b.new_page(); await p.goto(URL + "index.html")
        await p.get_by_role("button", name="Press me").click()
        await p.fill("#name", "async")
        await p.frame_locator("#frame").locator("#finput").fill("af")
        await (await p.query_selector("#chk")).check()
        try:
            await p.locator(".dup").click(timeout=1000)
            raise AssertionError("strict mode not enforced")
        except Error as e:
            assert "strict mode violation" in str(e)
        assert await p.evaluate("document.querySelector('#name').value") == "async"
        assert await p.frame(name="f").evaluate("document.querySelector('#finput').value") == "af"
        assert await p.is_checked("#chk")
    finally:
        await b.close()
asyncio.run(main())
""",
}


@pytest.mark.parametrize("name", list(_SCENARIOS))
def test_in_fresh_process(site, name):
    import os
    import subprocess
    import sys

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    code = _PRELUDE.format(root=root, url=site.url) + _SCENARIOS[name]
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=100)
    assert res.returncode == 0, res.stderr[-2000:]
