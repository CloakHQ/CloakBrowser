"""
Unit + integration tests for the humanize layer.

Fast unit tests (config, Bézier math, mocks) are proper test_ functions
that pytest discovers automatically.

Browser-dependent tests are marked @pytest.mark.slow and skipped in CI
unless explicitly requested (pytest -m slow).

Can also run directly: python tests/test_humanize_unit.py
"""
import math
import time
import sys
import asyncio
import pytest
from unittest.mock import MagicMock


def _mock_el_evaluate(is_input=False):
    """Mock evaluate that returns is_input for tagName checks and {hit: True} for pointer events."""
    def _eval(js, *args, **kwargs):
        if isinstance(js, str) and "elementFromPoint" in js:
            return {"hit": True}
        return is_input
    return MagicMock(side_effect=_eval)


def _async_mock_el_evaluate(is_input=False):
    """Async version of _mock_el_evaluate."""
    from unittest.mock import AsyncMock
    async def _eval(js, *args, **kwargs):
        if isinstance(js, str) and "elementFromPoint" in js:
            return {"hit": True}
        return is_input
    return AsyncMock(side_effect=_eval)


# =========================================================================
# Helper: ensure Locator class is patched before mock tests
# =========================================================================


# =========================================================================
# Helper: fake RawMouse for Bézier tests
# =========================================================================

class _FakeRawMouse:
    def __init__(self):
        self.moves = []
    def move(self, x, y, **kw):
        self.moves.append((x, y))
    def down(self, **kw):
        pass
    def up(self, **kw):
        pass
    def wheel(self, dx, dy):
        pass


# =========================================================================
# 1. Config resolution
# =========================================================================

class TestConfigResolution:
    def test_default_config_resolves(self):
        from cloakbrowser.human.config import resolve_config, HumanConfig
        cfg = resolve_config("default", None)
        assert isinstance(cfg, HumanConfig)
        assert cfg.mouse_min_steps > 0
        assert cfg.mouse_max_steps > cfg.mouse_min_steps
        assert len(cfg.initial_cursor_x) == 2
        assert len(cfg.initial_cursor_y) == 2
        assert cfg.typing_delay > 0

    def test_careful_config_resolves(self):
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("careful", None)
        default_cfg = resolve_config("default", None)
        assert cfg.mouse_min_steps > 0
        assert cfg.typing_delay >= default_cfg.typing_delay

    def test_custom_override(self):
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default", {"mouse_min_steps": 100, "mouse_max_steps": 200})
        assert cfg.mouse_min_steps == 100
        assert cfg.mouse_max_steps == 200

    def test_invalid_preset_raises(self):
        from cloakbrowser.human.config import resolve_config
        with pytest.raises(ValueError, match="Unknown humanize preset"):
            resolve_config("nonexistent", None)

    def test_rand_within_bounds(self):
        from cloakbrowser.human.config import rand, rand_range
        for _ in range(200):
            v = rand(10, 20)
            assert 10 <= v <= 20
        for _ in range(200):
            v = rand_range([5, 15])
            assert 5 <= v <= 15

    def test_sleep_ms_timing(self):
        from cloakbrowser.human.config import sleep_ms
        t0 = time.time()
        sleep_ms(50)
        elapsed = (time.time() - t0) * 1000
        assert elapsed >= 40
        assert elapsed < 200


# =========================================================================
# 2. Bézier math
# =========================================================================

class TestBezierMath:
    def test_generates_multiple_points(self):
        from cloakbrowser.human.mouse import human_move
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default", None)
        raw = _FakeRawMouse()
        human_move(raw, 0, 0, 500, 300, cfg)
        assert len(raw.moves) >= 10
        last_x, last_y = raw.moves[-1]
        assert abs(last_x - 500) < 10
        assert abs(last_y - 300) < 10

    def test_smoothness_no_large_jumps(self):
        from cloakbrowser.human.mouse import human_move
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default", None)
        raw = _FakeRawMouse()
        human_move(raw, 0, 0, 400, 400, cfg)
        total_dist = math.sqrt(400**2 + 400**2)
        max_jump = total_dist * 0.5
        for i in range(1, len(raw.moves)):
            dx = raw.moves[i][0] - raw.moves[i-1][0]
            dy = raw.moves[i][1] - raw.moves[i-1][1]
            assert math.sqrt(dx*dx + dy*dy) < max_jump

    def test_short_distance(self):
        from cloakbrowser.human.mouse import human_move
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default", None)
        raw = _FakeRawMouse()
        human_move(raw, 100, 100, 103, 102, cfg)
        assert len(raw.moves) >= 1

    def test_not_straight_line(self):
        from cloakbrowser.human.mouse import human_move
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default", None)
        max_dev = 0
        for _ in range(5):
            raw = _FakeRawMouse()
            human_move(raw, 0, 0, 500, 0, cfg)
            dev = max(abs(y) for _, y in raw.moves)
            if dev > max_dev:
                max_dev = dev
        assert max_dev > 0.5

    def test_click_target_within_box(self):
        from cloakbrowser.human.mouse import click_target
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default", None)
        box = {"x": 100, "y": 200, "width": 150, "height": 40}
        for _ in range(50):
            t = click_target(box, False, cfg)
            assert 100 <= t.x <= 250
            assert 200 <= t.y <= 240

    def test_click_target_input_mode(self):
        from cloakbrowser.human.mouse import click_target
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default", None)
        box = {"x": 50, "y": 50, "width": 200, "height": 30}
        for _ in range(20):
            t = click_target(box, True, cfg)
            assert 50 <= t.x <= 250
            assert 50 <= t.y <= 80


# =========================================================================
# 3. Async compatibility
# =========================================================================


# =========================================================================
# 4. Focus check — press / clear / pressSequentially
# =========================================================================


# =========================================================================
# 5. check/uncheck idle
# =========================================================================


# =========================================================================
# 6. Frame patching completeness
# =========================================================================


# =========================================================================
# 6b. iframe humanize routing (#428)
# =========================================================================


# =========================================================================
# 7. drag_to safety
# =========================================================================


# =========================================================================
# 8. Page config persistence
# =========================================================================

class TestPageConfigPersistence:
    def test_resolve_config_has_all_fields(self):
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default")
        required = ["mouse_min_steps", "mouse_max_steps", "typing_delay",
                    "initial_cursor_x", "initial_cursor_y", "idle_between_actions",
                    "idle_between_duration", "field_switch_delay",
                    "mistype_chance", "mistype_delay_notice", "mistype_delay_correct"]
        for field in required:
            assert hasattr(cfg, field), f"Config missing field: {field}"


# =========================================================================
# 9. Mistype config
# =========================================================================

class TestMistypeConfig:
    def test_default_mistype_chance(self):
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default")
        assert 0 < cfg.mistype_chance < 1
        assert len(cfg.mistype_delay_notice) == 2
        assert len(cfg.mistype_delay_correct) == 2

    def test_careful_mistype_higher(self):
        from cloakbrowser.human.config import resolve_config
        default = resolve_config("default")
        careful = resolve_config("careful")
        assert careful.mistype_chance >= default.mistype_chance

    def test_digit_neighbors_are_digits(self):
        # #573: a letter typo is rejected by <input type=number>, so the
        # correcting Backspace would delete the previous real digit.
        from cloakbrowser.human.keyboard import NEARBY_KEYS
        for d in "0123456789":
            assert NEARBY_KEYS[d].isdigit(), (d, NEARBY_KEYS[d])


# =========================================================================
# 10. Select-all platform detection
# =========================================================================


# =========================================================================
# 11. Non-ASCII keyboard input
# =========================================================================

class TestNonAsciiKeyboard:
    def test_cyrillic_uses_insert_text(self):
        from cloakbrowser.human.keyboard import human_type
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", {"mistype_chance": 0})
        page = MagicMock()
        raw = MagicMock()

        down_keys = []
        inserted = []
        raw.down = MagicMock(side_effect=lambda k: down_keys.append(k))
        raw.up = MagicMock()
        raw.insert_text = MagicMock(side_effect=lambda t: inserted.append(t))

        human_type(page, raw, "Привет", cfg)

        assert "".join(inserted) == "Привет"
        for k in down_keys:
            assert ord(k[0]) < 128 or k in ("Shift", "Backspace")

    def test_mixed_ascii_cyrillic(self):
        from cloakbrowser.human.keyboard import human_type
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", {"mistype_chance": 0})
        page = MagicMock()
        raw = MagicMock()

        down_keys = []
        inserted = []
        raw.down = MagicMock(side_effect=lambda k: down_keys.append(k))
        raw.up = MagicMock()
        raw.insert_text = MagicMock(side_effect=lambda t: inserted.append(t))

        human_type(page, raw, "Hi Мир", cfg)

        assert "H" in down_keys
        assert "i" in down_keys
        assert "М" in "".join(inserted)

    def test_cjk_uses_insert_text(self):
        from cloakbrowser.human.keyboard import human_type
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", {"mistype_chance": 0})
        page = MagicMock()
        raw = MagicMock()

        inserted = []
        raw.down = MagicMock()
        raw.up = MagicMock()
        raw.insert_text = MagicMock(side_effect=lambda t: inserted.append(t))

        human_type(page, raw, "你好", cfg)

        assert "".join(inserted) == "你好"

    def test_mistype_only_ascii(self):
        from cloakbrowser.human.keyboard import human_type
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", {"mistype_chance": 1.0})
        page = MagicMock()
        raw = MagicMock()

        down_keys = []
        raw.down = MagicMock(side_effect=lambda k: down_keys.append(k))
        raw.up = MagicMock()
        raw.insert_text = MagicMock()

        human_type(page, raw, "AБ", cfg)

        assert "Backspace" in down_keys

    def test_no_error_on_cyrillic(self):
        from cloakbrowser.human.keyboard import human_type
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", {"mistype_chance": 0})
        page = MagicMock()
        raw = MagicMock()
        raw.down = MagicMock()
        raw.up = MagicMock()
        raw.insert_text = MagicMock()

        # Should not raise
        human_type(page, raw, "Тест кириллицы", cfg)


# =========================================================================
# SLOW TESTS — require browser (skipped in CI unless pytest -m slow)
# =========================================================================

@pytest.mark.slow
class TestBrowserFill:
    def test_fill_clears_existing(self):
        from cloakbrowser import launch
        browser = launch(headless=False, humanize=True)
        page = browser.new_page()
        page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        time.sleep(1)
        page.locator('#searchInput').type('initial text')
        time.sleep(0.5)
        page.locator('#searchInput').fill('replaced text')
        time.sleep(0.5)
        val = page.locator('#searchInput').input_value()
        assert val == 'replaced text'
        assert 'initial' not in val
        browser.close()

    def test_fill_timing_humanized(self):
        from cloakbrowser import launch
        browser = launch(headless=False, humanize=True)
        page = browser.new_page()
        page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        time.sleep(1)
        t0 = time.time()
        page.locator('#searchInput').fill('Human speed test')
        elapsed_ms = int((time.time() - t0) * 1000)
        assert elapsed_ms > 1000
        browser.close()

    def test_clear_empties_field(self):
        from cloakbrowser import launch
        browser = launch(headless=False, humanize=True)
        page = browser.new_page()
        page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        time.sleep(1)
        page.locator('#searchInput').fill('some text')
        time.sleep(0.5)
        page.locator('#searchInput').clear()
        time.sleep(0.5)
        val = page.locator('#searchInput').input_value()
        assert val == ''
        browser.close()


# =========================================================================
# 6c. iframe humanize end-to-end (#428) — real same-origin iframe over HTTP
# =========================================================================

import threading
import http.server
import socketserver
import contextlib
from urllib.parse import quote

_IFRAME_PARENT = (
    b"<html><body><h1>parent</h1>"
    b"<iframe name='myframe' src='/child.html' width=400 height=250></iframe>"
    b"</body></html>"
)
_IFRAME_CHILD = (
    b"<html><body>"
    b"<button id='btn' onclick=\"this.textContent='CLICKED'\">Click Me</button>"
    b"<input id='inp'>"
    b"</body></html>"
)


@contextlib.contextmanager
def _iframe_server():
    """Serve a parent page + same-origin child page with a button/input."""
    class _H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = _IFRAME_CHILD if self.path.startswith("/child") else _IFRAME_PARENT
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), _H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}/"
    finally:
        srv.shutdown()


@pytest.mark.slow
class TestBrowserIframeHumanize:
    """Regression for #428: humanize=True must interact with elements inside
    sub-frames instead of misrouting to the top document."""

    def test_humanized_click_inside_iframe(self):
        from cloakbrowser import launch
        with _iframe_server() as url:
            browser = launch(headless=True, humanize=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="networkidle")
                frame = page.frame(name="myframe")
                assert frame is not None
                # the #428 case: a Locator obtained from a sub-frame
                frame.locator("#btn").click(timeout=5000)
                assert frame.locator("#btn").text_content() == "CLICKED"
            finally:
                browser.close()

    def test_humanized_fill_inside_iframe(self):
        from cloakbrowser import launch
        with _iframe_server() as url:
            browser = launch(headless=True, humanize=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="networkidle")
                frame = page.frame(name="myframe")
                frame.locator("#inp").fill("hello", timeout=5000)
                assert frame.locator("#inp").input_value() == "hello"
            finally:
                browser.close()

    def test_humanized_click_inside_dynamically_attached_iframe(self):
        from cloakbrowser import launch
        with _iframe_server() as url:
            browser = launch(headless=True, humanize=True)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="networkidle")
                with page.expect_event("frameattached") as event:
                    page.evaluate("""() => {
                        const iframe = document.createElement('iframe');
                        iframe.src = '/child.html';
                        document.body.appendChild(iframe);
                    }""")
                frame = event.value
                frame.wait_for_load_state("domcontentloaded")
                frame.evaluate("window.__moves = 0; addEventListener('mousemove', () => __moves++)")
                frame.click("#btn", timeout=5000)
                assert frame.evaluate("__moves") > 0, "frame click was not preceded by mouse movement"
                assert frame.locator("#btn").text_content() == "CLICKED"
            finally:
                browser.close()

    def test_native_control_click_inside_iframe(self):
        """Control: humanize=False must also work (parity)."""
        from cloakbrowser import launch
        with _iframe_server() as url:
            browser = launch(headless=True, humanize=False)
            try:
                page = browser.new_page()
                page.goto(url, wait_until="networkidle")
                frame = page.frame(name="myframe")
                frame.locator("#btn").click(timeout=5000)
                assert frame.locator("#btn").text_content() == "CLICKED"
            finally:
                browser.close()


@pytest.mark.slow
class TestBrowserIframeHumanizeAsync:
    @pytest.mark.asyncio
    async def test_async_humanized_click_inside_iframe(self):
        from cloakbrowser import launch_async
        with _iframe_server() as url:
            browser = await launch_async(headless=True, humanize=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle")
                frame = page.frame(name="myframe")
                assert frame is not None
                await frame.locator("#btn").click(timeout=5000)
                assert await frame.locator("#btn").text_content() == "CLICKED"
            finally:
                await browser.close()

    @pytest.mark.asyncio
    async def test_async_humanized_click_inside_dynamically_attached_iframe(self):
        from cloakbrowser import launch_async
        with _iframe_server() as url:
            browser = await launch_async(headless=True, humanize=True)
            try:
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle")
                async with page.expect_event("frameattached") as event:
                    await page.evaluate("""() => {
                        const iframe = document.createElement('iframe');
                        iframe.src = '/child.html';
                        document.body.appendChild(iframe);
                    }""")
                frame = await event.value
                await frame.wait_for_load_state("domcontentloaded")
                await frame.evaluate("window.__moves = 0; addEventListener('mousemove', () => __moves++)")
                await frame.click("#btn", timeout=5000)
                assert await frame.evaluate("__moves") > 0, "frame click was not preceded by mouse movement"
                assert await frame.locator("#btn").text_content() == "CLICKED"
            finally:
                await browser.close()


# page.set_content timed out in local runs of this test, so the page is loaded as a data: URL.
_WIDE_ROW_HTML = """
<body style="margin:0">
  <div style="display:flex">
    <div style="min-width:800px">left</div>
    <button id="target" style="min-width:800px"
            onclick="this.textContent = 'CLICKED'">right</button>
  </div>
</body>
"""


@pytest.mark.slow
class TestBrowserHorizontalScroll:
    """Regression for #521: a target off the right edge of a horizontally
    overflowing page must be scrolled into view on the x axis, not rejected
    as "covered by <none>"."""

    def test_humanized_click_scrolls_x_axis(self):
        from cloakbrowser import launch
        browser = launch(headless=True, humanize=True, geoip=False)
        try:
            page = browser.new_page(viewport={"width": 1000, "height": 700})
            page.goto("data:text/html," + quote(_WIDE_ROW_HTML))
            page.click("#target", timeout=5000)
            assert page.locator("#target").text_content() == "CLICKED"
        finally:
            browser.close()

    @pytest.mark.asyncio
    async def test_async_humanized_click_scrolls_x_axis(self):
        from cloakbrowser import launch_async
        browser = await launch_async(headless=True, humanize=True, geoip=False)
        try:
            page = await browser.new_page(viewport={"width": 1000, "height": 700})
            await page.goto("data:text/html," + quote(_WIDE_ROW_HTML))
            await page.click("#target", timeout=5000)
            assert await page.locator("#target").text_content() == "CLICKED"
        finally:
            await browser.close()


@pytest.mark.slow
class TestBrowserBotDetection:
    PROXY = None

    def test_behavioral_checks_pass(self):
        from cloakbrowser import launch
        browser = launch(headless=False, humanize=True, proxy=self.PROXY, geoip=True)
        page = browser.new_page()
        page.goto('https://deviceandbrowserinfo.com/are_you_a_bot_interactions',
                   wait_until='domcontentloaded')
        time.sleep(3)
        page.locator('#email').click()
        time.sleep(0.3)
        page.locator('#email').fill('test@example.com')
        time.sleep(0.5)
        page.locator('#password').click()
        time.sleep(0.3)
        page.locator('#password').fill('SecurePass!123')
        time.sleep(0.5)
        page.locator('#loginForm button[type="submit"]').click()
        time.sleep(5)
        body = page.locator('body').text_content()
        assert '"superHumanSpeed": true' not in body
        assert '"suspiciousClientSideBehavior": true' not in body
        browser.close()

    def test_form_timing(self):
        from cloakbrowser import launch
        browser = launch(headless=False, humanize=True, proxy=self.PROXY, geoip=True)
        page = browser.new_page()
        page.goto('https://deviceandbrowserinfo.com/are_you_a_bot_interactions',
                   wait_until='domcontentloaded')
        time.sleep(2)
        t0 = time.time()
        page.locator('#email').fill('test@example.com')
        page.locator('#password').fill('MyPassword!99')
        page.locator('#loginForm button[type="submit"]').click()
        elapsed_ms = int((time.time() - t0) * 1000)
        time.sleep(3)
        assert elapsed_ms > 3000
        browser.close()


@pytest.mark.slow
class TestAsyncEndToEnd:
    @pytest.mark.asyncio
    async def test_async_launch_click_fill(self):
        """launch_async(humanize=True) — async page.click and page.fill work end-to-end."""
        from cloakbrowser import launch_async
        
        browser = await launch_async(headless=False, humanize=True)
        page = await browser.new_page()
        assert hasattr(page, '_original'), "async page not patched"
        assert hasattr(page, '_human_cfg'), "async page missing _human_cfg"

        await page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        await asyncio.sleep(1)

        t0 = time.time()
        await page.locator('#searchInput').fill('async test')
        elapsed_ms = int((time.time() - t0) * 1000)
        assert elapsed_ms > 500, f"async fill too fast: {elapsed_ms}ms"

        val = await page.locator('#searchInput').input_value()
        assert val == 'async test', f"async fill wrong value: {val}"

        await browser.close()


# =========================================================================
# 12. ElementHandle patching — SYNC
# =========================================================================


# =========================================================================
# 13. ElementHandle patching — ASYNC
# =========================================================================


# =========================================================================
# 14. SLOW: Browser ElementHandle end-to-end
# =========================================================================

@pytest.mark.slow
class TestBrowserElementHandle:
    def test_query_selector_click_humanized(self):
        """page.query_selector() returns a patched handle — el.click() uses human curves."""
        from cloakbrowser import launch
        browser = launch(headless=False, humanize=True)
        page = browser.new_page()
        page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        time.sleep(1)

        el = page.query_selector('#searchInput')
        assert el is not None

        t0 = time.time()
        el.click()
        click_ms = int((time.time() - t0) * 1000)
        assert click_ms > 100, f"ElementHandle click too fast: {click_ms}ms (not humanized)"
        browser.close()

    def test_query_selector_type_humanized(self):
        """el.type() should type character-by-character with human timing."""
        from cloakbrowser import launch
        browser = launch(headless=False, humanize=True)
        page = browser.new_page()
        page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        time.sleep(1)

        el = page.query_selector('#searchInput')
        assert el is not None

        t0 = time.time()
        el.type('ElementHandle test')
        type_ms = int((time.time() - t0) * 1000)
        assert type_ms > 1000, f"ElementHandle type too fast: {type_ms}ms"

        val = page.locator('#searchInput').input_value()
        assert val == 'ElementHandle test'
        browser.close()

    def test_query_selector_fill_humanized(self):
        """el.fill() should clear + type with human timing."""
        from cloakbrowser import launch
        browser = launch(headless=False, humanize=True)
        page = browser.new_page()
        page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        time.sleep(1)

        el = page.query_selector('#searchInput')
        el.type('initial')
        time.sleep(0.3)

        t0 = time.time()
        el.fill('replaced')
        fill_ms = int((time.time() - t0) * 1000)
        assert fill_ms > 500, f"ElementHandle fill too fast: {fill_ms}ms"

        val = page.locator('#searchInput').input_value()
        assert val == 'replaced'
        browser.close()

    def test_query_selector_all_returns_patched(self):
        """page.query_selector_all() handles are humanized: clicks move the mouse first."""
        from cloakbrowser import launch
        browser = launch(headless=False, humanize=True)
        try:
            page = browser.new_page()
            page.evaluate("""() => {
                document.body.innerHTML = '<input type="checkbox" id="a"><input type="checkbox" id="b">';
                window.__moves = 0; addEventListener('mousemove', () => __moves++);
            }""")
            els = page.query_selector_all('input[type="checkbox"]')
            assert len(els) == 2
            for el in els:
                el.click()
            assert page.evaluate("__moves") > 0, "handle clicks were not preceded by mouse movement"
            assert page.evaluate("[a.checked, b.checked]") == [True, True]
        finally:
            browser.close()

    def test_query_selector_hover_humanized(self):
        """el.hover() should move cursor with human Bezier curve."""
        from cloakbrowser import launch
        browser = launch(headless=False, humanize=True)
        page = browser.new_page()
        page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        time.sleep(1)

        el = page.query_selector('#searchInput')
        t0 = time.time()
        el.hover()
        hover_ms = int((time.time() - t0) * 1000)
        assert hover_ms > 50, f"ElementHandle hover too fast: {hover_ms}ms"
        browser.close()


@pytest.mark.slow
class TestAsyncElementHandle:
    @pytest.mark.asyncio
    async def test_async_query_selector_click(self):
        from cloakbrowser import launch_async
        
        browser = await launch_async(headless=False, humanize=True)
        page = await browser.new_page()
        await page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        await asyncio.sleep(1)

        el = await page.query_selector('#searchInput')
        assert el is not None

        t0 = time.time()
        await el.click()
        click_ms = int((time.time() - t0) * 1000)
        assert click_ms > 100, f"Async ElementHandle click too fast: {click_ms}ms"

        await browser.close()


# =========================================================================
# 15. Per-call timeout forwarding (issue #137)
# =========================================================================


# =========================================================================
# 16. Per-call human_config override (typing speed customization)
# =========================================================================


# =========================================================================
# 17. scroll_into_view_if_needed humanization
# =========================================================================


# =========================================================================
# Issue #307: frame/page click timeout should not multiply
# =========================================================================


# =========================================================================
# framenavigated -> isolated-world invalidation (#507)
# =========================================================================


# =========================================================================
# Direct runner (backwards compat)
# =========================================================================

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short", "-x"]))


def test_error_classes_stay_importable():
    """Same compatibility set as JS errors.ts / .NET Actionability.cs."""
    from cloakbrowser import human as h

    for name in ("ElementNotAttachedError", "ElementNotVisibleError", "ElementNotStableError",
                 "ElementNotEnabledError", "ElementNotEditableError",
                 "ElementNotReceivingEventsError", "ElementTargetChangedError"):
        cls = getattr(h, name)
        assert issubclass(cls, h.ActionabilityError) and issubclass(cls, RuntimeError)
    e = h.ElementNotReceivingEventsError("#b", "div")
    assert (e.selector, e.check, e.covering_tag) == ("#b", "pointer_events", "div")
    assert str(e) == "Element '#b' failed pointer_events check: element is covered by <div>"
    for name in ("UnsupportedHumanizeSelectorError", "StealthWorldUnavailableError",
                 "StealthEvaluationError"):
        assert issubclass(getattr(h, name), h.StealthDomError)
