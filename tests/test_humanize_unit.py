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


# =========================================================================
# Helper: ensure Locator class is patched before mock tests
# =========================================================================

def _ensure_locator_patched():
    import cloakbrowser.human as h
    h._locator_sync_patched = False
    h._patch_locator_class_sync()


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

class TestAsyncCompat:
    def test_async_modules_import(self):
        from cloakbrowser.human.mouse_async import AsyncRawMouse, async_human_move
        from cloakbrowser.human.keyboard_async import AsyncRawKeyboard, async_human_type
        from cloakbrowser.human.scroll_async import async_scroll_to_element
        from cloakbrowser.human import patch_page_async, patch_browser_async, patch_context_async
        assert callable(async_human_move)
        assert callable(async_human_type)
        assert callable(async_scroll_to_element)

    def test_async_locator_patch(self):
        import cloakbrowser.human as h
        h._locator_async_patched = False
        h._patch_locator_class_async()
        assert h._locator_async_patched
        from playwright.async_api._generated import Locator as AsyncLocator
        assert 'humanized' in AsyncLocator.fill.__name__

    def test_async_sleep_is_coroutine(self):
        from cloakbrowser.human.config import async_sleep_ms
        import asyncio
        assert asyncio.iscoroutinefunction(async_sleep_ms)


# =========================================================================
# 4. Focus check — press / clear / pressSequentially
# =========================================================================

class TestFocusCheck:
    def test_press_skips_click_when_focused(self):
        _ensure_locator_patched()
        from unittest.mock import MagicMock, patch as mock_patch
        page = MagicMock()
        page._original = MagicMock()
        page._human_cfg = MagicMock()
        page._human_cfg.idle_between_actions = False

        with mock_patch("cloakbrowser.human._is_selector_focused", return_value=True):
            from playwright.sync_api._generated import Locator
            loc = MagicMock()
            loc.page = page
            loc._impl_obj = MagicMock()
            loc._impl_obj._selector = "#test"
            Locator.press(loc, "Enter")

        page.click.assert_not_called()

    def test_press_clicks_when_not_focused(self):
        _ensure_locator_patched()
        from unittest.mock import MagicMock, patch as mock_patch
        page = MagicMock()
        page._original = MagicMock()
        page._human_cfg = MagicMock()
        page._human_cfg.idle_between_actions = False

        with mock_patch("cloakbrowser.human._is_selector_focused", return_value=False):
            from playwright.sync_api._generated import Locator
            loc = MagicMock()
            loc.page = page
            loc._impl_obj = MagicMock()
            loc._impl_obj._selector = "#test"
            Locator.press(loc, "Enter")

        page.click.assert_called_with("#test")


# =========================================================================
# 5. check/uncheck idle
# =========================================================================

class TestCheckUncheckIdle:
    def test_check_calls_idle_when_enabled(self):
        _ensure_locator_patched()
        from unittest.mock import MagicMock, patch as mock_patch
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default", {"idle_between_actions": True, "idle_between_duration": [50, 100]})

        page = MagicMock()
        page._original = MagicMock()
        page._original.mouse_move = MagicMock()
        page._human_cfg = cfg

        idle_called = {"n": 0}
        def fake_idle(*a, **kw):
            idle_called["n"] += 1

        from playwright.sync_api._generated import Locator
        loc = MagicMock()
        loc.page = page
        loc._impl_obj = MagicMock()
        loc._impl_obj._selector = "#checkbox"
        loc.is_checked = MagicMock(return_value=False)

        with mock_patch("cloakbrowser.human.human_idle", fake_idle):
            Locator.check(loc)

        assert idle_called["n"] >= 1

    def test_uncheck_calls_idle_when_enabled(self):
        _ensure_locator_patched()
        from unittest.mock import MagicMock, patch as mock_patch
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default", {"idle_between_actions": True, "idle_between_duration": [50, 100]})

        page = MagicMock()
        page._original = MagicMock()
        page._original.mouse_move = MagicMock()
        page._human_cfg = cfg

        idle_called = {"n": 0}
        def fake_idle(*a, **kw):
            idle_called["n"] += 1

        from playwright.sync_api._generated import Locator
        loc = MagicMock()
        loc.page = page
        loc._impl_obj = MagicMock()
        loc._impl_obj._selector = "#checkbox"
        loc.is_checked = MagicMock(return_value=True)

        with mock_patch("cloakbrowser.human.human_idle", fake_idle):
            Locator.uncheck(loc)

        assert idle_called["n"] >= 1


# =========================================================================
# 6. Frame patching completeness
# =========================================================================

class TestFramePatching:
    def test_all_11_methods_patched(self):
        from cloakbrowser.human import _patch_single_frame_sync, _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", None)
        cursor = _CursorState()
        page = MagicMock()
        page._original = MagicMock()
        frame = MagicMock()
        frame._human_patched = False

        _patch_single_frame_sync(frame, page, cfg, cursor, MagicMock(), MagicMock(), page._original)

        expected = ['click', 'dblclick', 'hover', 'type', 'fill',
                    'check', 'uncheck', 'select_option', 'press',
                    'clear', 'drag_and_drop']
        for method in expected:
            fn = getattr(frame, method)
            assert not isinstance(fn, MagicMock), f"frame.{method} was not patched"


# =========================================================================
# 7. drag_to safety
# =========================================================================

class TestDragToSafety:
    def test_handles_missing_original(self):
        _ensure_locator_patched()
        from playwright.sync_api._generated import Locator
        from unittest.mock import MagicMock

        page = MagicMock()
        page._original = None

        source_loc = MagicMock()
        source_loc.page = page
        source_loc._impl_obj = MagicMock()
        source_loc._impl_obj._selector = "#src"
        source_loc.bounding_box = MagicMock(return_value={"x": 10, "y": 10, "width": 50, "height": 50})

        target_loc = MagicMock()
        target_loc.page = page
        target_loc._impl_obj = MagicMock()
        target_loc._impl_obj._selector = "#tgt"
        target_loc.bounding_box = MagicMock(return_value={"x": 200, "y": 200, "width": 50, "height": 50})

        try:
            Locator.drag_to(source_loc, target_loc)
        except AttributeError:
            pytest.fail("drag_to crashed without page._original")


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


# =========================================================================
# 10. Select-all platform detection
# =========================================================================

class TestSelectAllPlatform:
    def test_select_all_constant_exists(self):
        from cloakbrowser.human import _SELECT_ALL
        assert _SELECT_ALL in ("Meta+a", "Control+a")

    def test_select_all_matches_platform(self):
        import sys
        from cloakbrowser.human import _SELECT_ALL
        if sys.platform == "darwin":
            assert _SELECT_ALL == "Meta+a"
        else:
            assert _SELECT_ALL == "Control+a"


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


class TestNonAsciiKeyboardAsync:
    @pytest.mark.asyncio
    async def test_async_cyrillic_uses_insert_text(self):
        from cloakbrowser.human.keyboard_async import async_human_type
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock, AsyncMock

        cfg = resolve_config("default", {"mistype_chance": 0})
        page = MagicMock()
        raw = MagicMock()

        inserted = []
        raw.down = AsyncMock()
        raw.up = AsyncMock()
        raw.insert_text = AsyncMock(side_effect=lambda t: inserted.append(t))

        await async_human_type(page, raw, "Привет", cfg)

        assert "".join(inserted) == "Привет"



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


@pytest.mark.slow
class TestBrowserPatching:
    def test_page_has_original(self):
        from cloakbrowser import launch
        browser = launch(headless=False, humanize=True)
        page = browser.new_page()
        assert hasattr(page, '_original')
        assert hasattr(page, '_human_cfg')
        browser.close()

    def test_locator_methods_patched(self):
        from cloakbrowser import launch
        browser = launch(headless=False, humanize=True)
        page = browser.new_page()
        from playwright.sync_api._generated import Locator
        methods = ['fill', 'click', 'type', 'dblclick', 'hover', 'check', 'uncheck',
                   'set_checked', 'select_option', 'press', 'press_sequentially',
                   'tap', 'drag_to', 'clear']
        for method in methods:
            fn = getattr(Locator, method)
            assert 'humanized' in fn.__name__, f"{method} not patched"
        browser.close()

    def test_non_humanized_page_normal(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            assert not hasattr(page, '_original')
            browser.close()

    def test_page_human_cfg_persists(self):
        from cloakbrowser import launch
        browser = launch(headless=False, humanize=True)
        page = browser.new_page()
        assert page._human_cfg is not None
        assert hasattr(page._human_cfg, 'idle_between_actions')
        assert hasattr(page._human_cfg, 'mistype_chance')
        browser.close()


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
        page.locator('button[type="submit"]').click()
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
        page.locator('button[type="submit"]').click()
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

class TestElementHandlePatchingSync:
    """Test that ElementHandle objects returned by query_selector etc. are humanized."""

    def test_patch_single_element_handle_marks_patched(self):
        from cloakbrowser.human import _patch_single_element_handle_sync, _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", None)
        cursor = _CursorState()
        cursor.initialized = True
        cursor.x = 100
        cursor.y = 100
        page = MagicMock()
        page._original = MagicMock()
        el = MagicMock()
        el._human_patched = False
        el.bounding_box = MagicMock(return_value={"x": 50, "y": 50, "width": 100, "height": 30})
        el.evaluate = MagicMock(return_value=True)  # is_input
        el.is_checked = MagicMock(return_value=False)
        el.query_selector = MagicMock(return_value=None)
        el.query_selector_all = MagicMock(return_value=[])
        el.wait_for_selector = MagicMock(return_value=None)

        raw_mouse = MagicMock()
        raw_keyboard = MagicMock()

        _patch_single_element_handle_sync(
            el, page, cfg, cursor, raw_mouse, raw_keyboard, page._original, None, None
        )

        assert el._human_patched is True

    def test_element_handle_click_calls_human_move(self):
        from cloakbrowser.human import _patch_single_element_handle_sync, _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", {"idle_between_actions": False})
        cursor = _CursorState()
        cursor.initialized = True
        cursor.x = 100
        cursor.y = 100
        page = MagicMock()
        page._original = MagicMock()

        el = MagicMock()
        el._human_patched = False
        el.bounding_box = MagicMock(return_value={"x": 200, "y": 200, "width": 100, "height": 30})
        el.evaluate = MagicMock(return_value=False)
        el.is_checked = MagicMock(return_value=False)
        el.query_selector = MagicMock(return_value=None)
        el.query_selector_all = MagicMock(return_value=[])
        el.wait_for_selector = MagicMock(return_value=None)

        raw_mouse = MagicMock()
        raw_mouse.move = MagicMock()
        raw_mouse.down = MagicMock()
        raw_mouse.up = MagicMock()
        raw_mouse.wheel = MagicMock()
        raw_keyboard = MagicMock()

        _patch_single_element_handle_sync(
            el, page, cfg, cursor, raw_mouse, raw_keyboard, page._original, None, None
        )

        # Call the patched click
        el.click()

        # Should call raw_mouse.move (Bezier path) and then down/up
        assert raw_mouse.move.called
        assert raw_mouse.down.called
        assert raw_mouse.up.called

    def test_element_handle_hover_moves_cursor_without_click(self):
        from cloakbrowser.human import _patch_single_element_handle_sync, _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", {"idle_between_actions": False})
        cursor = _CursorState()
        cursor.initialized = True
        cursor.x = 50
        cursor.y = 50
        page = MagicMock()
        page._original = MagicMock()

        el = MagicMock()
        el._human_patched = False
        el.bounding_box = MagicMock(return_value={"x": 200, "y": 200, "width": 100, "height": 30})
        el.evaluate = MagicMock(return_value=False)
        el.is_checked = MagicMock(return_value=False)
        el.query_selector = MagicMock(return_value=None)
        el.query_selector_all = MagicMock(return_value=[])
        el.wait_for_selector = MagicMock(return_value=None)

        raw_mouse = MagicMock()
        raw_mouse.move = MagicMock()
        raw_mouse.down = MagicMock()
        raw_mouse.up = MagicMock()
        raw_mouse.wheel = MagicMock()
        raw_keyboard = MagicMock()

        _patch_single_element_handle_sync(
            el, page, cfg, cursor, raw_mouse, raw_keyboard, page._original, None, None
        )

        el.hover()

        # Move should be called, but NOT down/up (hover, not click)
        assert raw_mouse.move.called
        assert not raw_mouse.down.called

    def test_element_handle_type_calls_human_type(self):
        from cloakbrowser.human import _patch_single_element_handle_sync, _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", {"idle_between_actions": False, "mistype_chance": 0})
        cursor = _CursorState()
        cursor.initialized = True
        cursor.x = 50
        cursor.y = 50
        page = MagicMock()
        originals = MagicMock()
        page._original = originals

        el = MagicMock()
        el._human_patched = False
        el.bounding_box = MagicMock(return_value={"x": 200, "y": 200, "width": 100, "height": 30})
        el.evaluate = MagicMock(return_value=True)  # is input
        el.is_checked = MagicMock(return_value=False)
        el.query_selector = MagicMock(return_value=None)
        el.query_selector_all = MagicMock(return_value=[])
        el.wait_for_selector = MagicMock(return_value=None)

        raw_mouse = MagicMock()
        raw_mouse.move = MagicMock()
        raw_mouse.down = MagicMock()
        raw_mouse.up = MagicMock()
        raw_mouse.wheel = MagicMock()
        raw_keyboard = MagicMock()
        raw_keyboard.down = MagicMock()
        raw_keyboard.up = MagicMock()
        raw_keyboard.insert_text = MagicMock()

        _patch_single_element_handle_sync(
            el, page, cfg, cursor, raw_mouse, raw_keyboard, originals, None, None
        )

        el.type("hello")

        # Mouse moved + clicked (to focus), then keyboard used
        assert raw_mouse.move.called
        assert raw_mouse.down.called  # click to focus the input
        # Keyboard events should have fired (down/up for ASCII chars)
        assert raw_keyboard.down.called or raw_keyboard.insert_text.called

    def test_element_handle_fill_clears_and_types(self):
        from cloakbrowser.human import _patch_single_element_handle_sync, _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock, call

        cfg = resolve_config("default", {"idle_between_actions": False, "mistype_chance": 0})
        cursor = _CursorState()
        cursor.initialized = True
        cursor.x = 50
        cursor.y = 50
        page = MagicMock()
        originals = MagicMock()
        page._original = originals

        pressed_keys = []
        originals.keyboard_press = MagicMock(side_effect=lambda k: pressed_keys.append(k))

        el = MagicMock()
        el._human_patched = False
        el.bounding_box = MagicMock(return_value={"x": 200, "y": 200, "width": 100, "height": 30})
        el.evaluate = MagicMock(return_value=True)
        el.is_checked = MagicMock(return_value=False)
        el.query_selector = MagicMock(return_value=None)
        el.query_selector_all = MagicMock(return_value=[])
        el.wait_for_selector = MagicMock(return_value=None)

        raw_mouse = MagicMock()
        raw_mouse.move = MagicMock()
        raw_mouse.down = MagicMock()
        raw_mouse.up = MagicMock()
        raw_mouse.wheel = MagicMock()
        raw_keyboard = MagicMock()
        raw_keyboard.down = MagicMock()
        raw_keyboard.up = MagicMock()
        raw_keyboard.insert_text = MagicMock()

        _patch_single_element_handle_sync(
            el, page, cfg, cursor, raw_mouse, raw_keyboard, originals, None, None
        )

        el.fill("replaced")

        # Should have pressed Select-All and Backspace to clear
        import sys
        expected_select = "Meta+a" if sys.platform == "darwin" else "Control+a"
        assert expected_select in pressed_keys
        assert "Backspace" in pressed_keys

    def test_element_handle_no_double_patching(self):
        from cloakbrowser.human import _patch_single_element_handle_sync, _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", None)
        cursor = _CursorState()
        page = MagicMock()
        page._original = MagicMock()
        el = MagicMock()
        el._human_patched = False
        el.query_selector = MagicMock(return_value=None)
        el.query_selector_all = MagicMock(return_value=[])
        el.wait_for_selector = MagicMock(return_value=None)

        _patch_single_element_handle_sync(
            el, page, cfg, cursor, MagicMock(), MagicMock(), page._original, None, None
        )

        # Save patched click
        first_click = el.click

        # Try to patch again
        _patch_single_element_handle_sync(
            el, page, cfg, cursor, MagicMock(), MagicMock(), page._original, None, None
        )

        # Should be the same — no double wrap
        assert el.click is first_click

    def test_nested_query_selector_returns_patched_handle(self):
        from cloakbrowser.human import _patch_single_element_handle_sync, _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", None)
        cursor = _CursorState()
        page = MagicMock()
        page._original = MagicMock()

        child = MagicMock()
        child._human_patched = False
        child.bounding_box = MagicMock(return_value={"x": 10, "y": 10, "width": 50, "height": 30})
        child.evaluate = MagicMock(return_value=False)
        child.is_checked = MagicMock(return_value=False)
        child.query_selector = MagicMock(return_value=None)
        child.query_selector_all = MagicMock(return_value=[])
        child.wait_for_selector = MagicMock(return_value=None)

        el = MagicMock()
        el._human_patched = False
        el.bounding_box = MagicMock(return_value={"x": 50, "y": 50, "width": 100, "height": 30})
        el.evaluate = MagicMock(return_value=False)
        el.is_checked = MagicMock(return_value=False)
        el.query_selector = MagicMock(return_value=child)
        el.query_selector_all = MagicMock(return_value=[])
        el.wait_for_selector = MagicMock(return_value=None)

        _patch_single_element_handle_sync(
            el, page, cfg, cursor, MagicMock(), MagicMock(), page._original, None, None
        )

        result = el.query_selector("span")
        assert result._human_patched is True

    def test_page_query_selector_patched(self):
        from cloakbrowser.human import _patch_page_element_handles_sync, _patch_single_element_handle_sync, _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", None)
        cursor = _CursorState()

        el = MagicMock()
        el._human_patched = False
        el.bounding_box = MagicMock(return_value={"x": 50, "y": 50, "width": 100, "height": 30})
        el.evaluate = MagicMock(return_value=False)
        el.is_checked = MagicMock(return_value=False)
        el.query_selector = MagicMock(return_value=None)
        el.query_selector_all = MagicMock(return_value=[])
        el.wait_for_selector = MagicMock(return_value=None)

        page = MagicMock()
        page._original = MagicMock()
        page.query_selector = MagicMock(return_value=el)
        page.query_selector_all = MagicMock(return_value=[el])
        page.wait_for_selector = MagicMock(return_value=el)

        _patch_page_element_handles_sync(
            page, cfg, cursor, MagicMock(), MagicMock(), page._original, None, None
        )

        result = page.query_selector("#test")
        assert result._human_patched is True

    def test_page_query_selector_all_patches_all(self):
        from cloakbrowser.human import _patch_page_element_handles_sync, _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", None)
        cursor = _CursorState()

        def make_el():
            e = MagicMock()
            e._human_patched = False
            e.bounding_box = MagicMock(return_value={"x": 10, "y": 10, "width": 50, "height": 30})
            e.evaluate = MagicMock(return_value=False)
            e.is_checked = MagicMock(return_value=False)
            e.query_selector = MagicMock(return_value=None)
            e.query_selector_all = MagicMock(return_value=[])
            e.wait_for_selector = MagicMock(return_value=None)
            return e

        el1, el2, el3 = make_el(), make_el(), make_el()

        page = MagicMock()
        page._original = MagicMock()
        page.query_selector = MagicMock(return_value=None)
        page.query_selector_all = MagicMock(return_value=[el1, el2, el3])
        page.wait_for_selector = MagicMock(return_value=None)

        _patch_page_element_handles_sync(
            page, cfg, cursor, MagicMock(), MagicMock(), page._original, None, None
        )

        results = page.query_selector_all("div")
        for r in results:
            assert r._human_patched is True

    def test_wait_for_selector_patched(self):
        from cloakbrowser.human import _patch_page_element_handles_sync, _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", None)
        cursor = _CursorState()

        el = MagicMock()
        el._human_patched = False
        el.bounding_box = MagicMock(return_value={"x": 50, "y": 50, "width": 100, "height": 30})
        el.evaluate = MagicMock(return_value=False)
        el.is_checked = MagicMock(return_value=False)
        el.query_selector = MagicMock(return_value=None)
        el.query_selector_all = MagicMock(return_value=[])
        el.wait_for_selector = MagicMock(return_value=None)

        page = MagicMock()
        page._original = MagicMock()
        page.query_selector = MagicMock(return_value=None)
        page.query_selector_all = MagicMock(return_value=[])
        page.wait_for_selector = MagicMock(return_value=el)

        _patch_page_element_handles_sync(
            page, cfg, cursor, MagicMock(), MagicMock(), page._original, None, None
        )

        result = page.wait_for_selector("#test")
        assert result._human_patched is True

    def test_element_handle_all_methods_patched(self):
        """Verify all expected interaction methods are replaced."""
        from cloakbrowser.human import _patch_single_element_handle_sync, _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", None)
        cursor = _CursorState()
        page = MagicMock()
        page._original = MagicMock()

        el = MagicMock()
        el._human_patched = False
        el.bounding_box = MagicMock(return_value={"x": 50, "y": 50, "width": 100, "height": 30})
        el.evaluate = MagicMock(return_value=False)
        el.is_checked = MagicMock(return_value=False)
        el.query_selector = MagicMock(return_value=None)
        el.query_selector_all = MagicMock(return_value=[])
        el.wait_for_selector = MagicMock(return_value=None)
        el.set_checked = MagicMock()  # ensure it exists

        _patch_single_element_handle_sync(
            el, page, cfg, cursor, MagicMock(), MagicMock(), page._original, None, None
        )

        expected_methods = ['click', 'dblclick', 'hover', 'type', 'fill', 'press',
                            'select_option', 'check', 'uncheck', 'set_checked',
                            'tap', 'focus', 'query_selector', 'query_selector_all',
                            'wait_for_selector']
        for method in expected_methods:
            fn = getattr(el, method)
            assert not isinstance(fn, MagicMock), f"el.{method} was not patched"


# =========================================================================
# 13. ElementHandle patching — ASYNC
# =========================================================================

class TestElementHandlePatchingAsync:
    @pytest.mark.asyncio
    async def test_async_element_handle_click(self):
        from cloakbrowser.human import _patch_single_element_handle_async, _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock, AsyncMock

        cfg = resolve_config("default", {"idle_between_actions": False})
        cursor = _CursorState()
        cursor.initialized = True
        cursor.x = 100
        cursor.y = 100

        page = MagicMock()
        originals = MagicMock()
        originals.mouse_move = AsyncMock()
        page._original = originals

        el = MagicMock()
        el._human_patched = False
        el.bounding_box = AsyncMock(return_value={"x": 200, "y": 200, "width": 100, "height": 30})
        el.evaluate = AsyncMock(return_value=False)
        el.is_checked = AsyncMock(return_value=False)
        el.query_selector = AsyncMock(return_value=None)
        el.query_selector_all = AsyncMock(return_value=[])
        el.wait_for_selector = AsyncMock(return_value=None)

        raw_mouse = MagicMock()
        raw_mouse.move = AsyncMock()
        raw_mouse.down = AsyncMock()
        raw_mouse.up = AsyncMock()
        raw_mouse.wheel = AsyncMock()
        raw_keyboard = MagicMock()
        raw_keyboard.down = AsyncMock()
        raw_keyboard.up = AsyncMock()
        raw_keyboard.insert_text = AsyncMock()

        stealth = MagicMock()
        stealth.get_cdp_session = AsyncMock(return_value=None)

        _patch_single_element_handle_async(
            el, page, cfg, cursor, raw_mouse, raw_keyboard, originals, stealth, [None]
        )

        await el.click()

        assert raw_mouse.move.called
        assert raw_mouse.down.called
        assert raw_mouse.up.called

    @pytest.mark.asyncio
    async def test_async_page_query_selector_patched(self):
        from cloakbrowser.human import _patch_page_element_handles_async, _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock, AsyncMock

        cfg = resolve_config("default", None)
        cursor = _CursorState()

        el = MagicMock()
        el._human_patched = False
        el.bounding_box = AsyncMock(return_value={"x": 50, "y": 50, "width": 100, "height": 30})
        el.evaluate = AsyncMock(return_value=False)
        el.is_checked = AsyncMock(return_value=False)
        el.query_selector = AsyncMock(return_value=None)
        el.query_selector_all = AsyncMock(return_value=[])
        el.wait_for_selector = AsyncMock(return_value=None)

        page = MagicMock()
        page._original = MagicMock()
        page.query_selector = AsyncMock(return_value=el)
        page.query_selector_all = AsyncMock(return_value=[el])
        page.wait_for_selector = AsyncMock(return_value=el)

        stealth = MagicMock()
        stealth.get_cdp_session = AsyncMock(return_value=None)

        _patch_page_element_handles_async(
            page, cfg, cursor, MagicMock(), MagicMock(), page._original, stealth, [None]
        )

        result = await page.query_selector("#test")
        assert result._human_patched is True


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
        assert getattr(el, '_human_patched', False), "ElementHandle not patched"

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
        """page.query_selector_all() returns all handles patched."""
        from cloakbrowser import launch
        browser = launch(headless=False, humanize=True)
        page = browser.new_page()
        page.goto('https://the-internet.herokuapp.com/checkboxes', wait_until='domcontentloaded')
        time.sleep(1)

        els = page.query_selector_all('input[type="checkbox"]')
        assert len(els) >= 2
        for el in els:
            assert getattr(el, '_human_patched', False), "ElementHandle not patched"
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
        assert getattr(el, '_human_patched', False), "Async ElementHandle not patched"

        t0 = time.time()
        await el.click()
        click_ms = int((time.time() - t0) * 1000)
        assert click_ms > 100, f"Async ElementHandle click too fast: {click_ms}ms"

        await browser.close()


# =========================================================================
# 15. Per-call timeout forwarding (issue #137)
# =========================================================================

class TestPerCallTimeoutForwarding:
    """page.click('#x', timeout=5000) must forward 5000 to bounding_box(),
    not silently use the hardcoded 2000ms in scroll."""

    def test_get_element_box_default_timeout(self):
        """Default timeout matches Playwright's 30000ms."""
        from cloakbrowser.human.scroll import _get_element_box
        from unittest.mock import MagicMock

        page = MagicMock()
        loc = MagicMock()
        loc.bounding_box = MagicMock(return_value={"x": 0, "y": 0, "width": 1, "height": 1})
        page.locator = MagicMock(return_value=MagicMock(first=loc))

        _get_element_box(page, "#x")
        loc.bounding_box.assert_called_once_with(timeout=30000)

    def test_get_element_box_custom_timeout(self):
        """Caller can pass a custom timeout that overrides the default."""
        from cloakbrowser.human.scroll import _get_element_box
        from unittest.mock import MagicMock

        page = MagicMock()
        loc = MagicMock()
        loc.bounding_box = MagicMock(return_value={"x": 0, "y": 0, "width": 1, "height": 1})
        page.locator = MagicMock(return_value=MagicMock(first=loc))

        _get_element_box(page, "#x", timeout=5000)
        loc.bounding_box.assert_called_once_with(timeout=5000)

    def test_scroll_to_element_forwards_timeout(self):
        """scroll_to_element passes timeout through to bounding_box()."""
        from cloakbrowser.human.scroll import scroll_to_element
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", None)
        page = MagicMock()
        page.viewport_size = {"width": 1280, "height": 720}
        loc = MagicMock()
        # Already in viewport so we don't actually scroll — just verify
        # the timeout was forwarded on the first bounding_box() call.
        loc.bounding_box = MagicMock(return_value={"x": 100, "y": 200, "width": 50, "height": 30})
        page.locator = MagicMock(return_value=MagicMock(first=loc))

        raw = MagicMock()
        scroll_to_element(page, raw, "#x", 0, 0, cfg, timeout=7500)
        loc.bounding_box.assert_called_with(timeout=7500)

    def test_page_click_forwards_timeout_kwarg(self):
        """page.click(selector, timeout=...) reaches scroll_to_element.

        Patches scroll_to_element module-side via monkey-patching the
        cloakbrowser.human module attribute used by patch_page.
        """
        import cloakbrowser.human as h
        from cloakbrowser.human import _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock, patch

        cfg = resolve_config("default", {"idle_between_actions": False})
        cursor = _CursorState()
        cursor.initialized = True
        cursor.x = 100
        cursor.y = 100

        # Build a minimal page mock
        page = MagicMock()
        page.click = MagicMock()
        page.dblclick = MagicMock()
        page.hover = MagicMock()
        page.type = MagicMock()
        page.fill = MagicMock()
        page.goto = MagicMock()
        page.is_checked = MagicMock(return_value=False)
        page.viewport_size = {"width": 1280, "height": 720}
        page.evaluate = MagicMock(return_value=False)
        page.context.new_cdp_session = MagicMock(side_effect=Exception("no cdp"))
        page.mouse = MagicMock()
        page.keyboard = MagicMock()
        page.query_selector = MagicMock(return_value=None)
        page.query_selector_all = MagicMock(return_value=[])
        page.wait_for_selector = MagicMock(return_value=None)
        page.main_frame = MagicMock()
        page.main_frame.child_frames = []

        captured = {}
        def fake_scroll(page_arg, raw, selector, cx, cy, cfg_arg, timeout=30000):
            captured["timeout"] = timeout
            return ({"x": 100, "y": 100, "width": 50, "height": 30}, cx, cy)

        with patch.object(h, "scroll_to_element", side_effect=fake_scroll):
            h.patch_page(page, cfg, cursor)
            page.click("#slow-button", timeout=5000)

        assert captured.get("timeout") == 5000, f"expected 5000, got {captured}"


# =========================================================================
# 16. Per-call human_config override (typing speed customization)
# =========================================================================

class TestPerCallHumanConfigOverride:
    """page.type('#email', text, human_config={'typing_delay': 30}) lets users
    override typing speed (and any other HumanConfig field) on a per-call
    basis without re-patching the page."""

    def test_merge_config_creates_new_instance(self):
        from cloakbrowser.human.config import resolve_config, merge_config

        base = resolve_config("default", None)
        merged = merge_config(base, {"typing_delay": 30})

        assert merged.typing_delay == 30
        assert base.typing_delay != 30  # not mutated
        # Non-overridden fields are preserved
        assert merged.mouse_min_steps == base.mouse_min_steps

    def test_merge_config_none_returns_base(self):
        from cloakbrowser.human.config import resolve_config, merge_config

        base = resolve_config("default", None)
        merged = merge_config(base, None)
        assert merged is base

    def test_merge_config_ignores_unknown_keys(self):
        from cloakbrowser.human.config import resolve_config, merge_config

        base = resolve_config("default", None)
        # ``not_a_real_field`` is silently dropped — callers shouldn't crash
        # if they pass typos or future field names.
        merged = merge_config(base, {"typing_delay": 30, "not_a_real_field": 99})
        assert merged.typing_delay == 30

    def test_page_type_uses_per_call_typing_delay(self):
        """page.type(..., human_config={'typing_delay': 30}) reaches human_type
        with cfg.typing_delay == 30 even when patch was done with default 70."""
        import cloakbrowser.human as h
        from cloakbrowser.human import _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock, patch

        cfg = resolve_config("default", {
            "idle_between_actions": False,
            "field_switch_delay": (0, 1),
        })
        assert cfg.typing_delay == 70  # baseline

        cursor = _CursorState()
        cursor.initialized = True
        cursor.x = 100
        cursor.y = 100

        page = MagicMock()
        page.click = MagicMock()
        page.dblclick = MagicMock()
        page.hover = MagicMock()
        page.type = MagicMock()
        page.fill = MagicMock()
        page.goto = MagicMock()
        page.is_checked = MagicMock(return_value=False)
        page.viewport_size = {"width": 1280, "height": 720}
        page.evaluate = MagicMock(return_value=False)
        page.context.new_cdp_session = MagicMock(side_effect=Exception("no cdp"))
        page.mouse = MagicMock()
        page.keyboard = MagicMock()
        page.query_selector = MagicMock(return_value=None)
        page.query_selector_all = MagicMock(return_value=[])
        page.wait_for_selector = MagicMock(return_value=None)
        page.main_frame = MagicMock()
        page.main_frame.child_frames = []

        captured = {}
        def fake_human_type(page_arg, raw, text, cfg_arg, cdp_session=None):
            captured["typing_delay"] = cfg_arg.typing_delay
            captured["mistype_chance"] = cfg_arg.mistype_chance

        def fake_scroll(*args, **kwargs):
            return ({"x": 100, "y": 100, "width": 50, "height": 30}, 100, 100)

        with patch.object(h, "human_type", side_effect=fake_human_type), \
             patch.object(h, "scroll_to_element", side_effect=fake_scroll):
            h.patch_page(page, cfg, cursor)
            page.type(
                "#email", "hi",
                human_config={"typing_delay": 30, "mistype_chance": 0},
            )

        assert captured["typing_delay"] == 30
        assert captured["mistype_chance"] == 0
        # Global cfg untouched — per-call override doesn't leak
        assert cfg.typing_delay == 70

    def test_page_fill_uses_per_call_typing_delay(self):
        """Same as type, but for fill (which also clears the field first)."""
        import cloakbrowser.human as h
        from cloakbrowser.human import _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock, patch

        cfg = resolve_config("default", {
            "idle_between_actions": False,
            "field_switch_delay": (0, 1),
        })
        cursor = _CursorState()
        cursor.initialized = True
        cursor.x = 100
        cursor.y = 100

        page = MagicMock()
        page.viewport_size = {"width": 1280, "height": 720}
        page.is_checked = MagicMock(return_value=False)
        page.evaluate = MagicMock(return_value=False)
        page.context.new_cdp_session = MagicMock(side_effect=Exception("no cdp"))
        page.mouse = MagicMock()
        page.keyboard = MagicMock()
        page.query_selector = MagicMock(return_value=None)
        page.query_selector_all = MagicMock(return_value=[])
        page.wait_for_selector = MagicMock(return_value=None)
        page.main_frame = MagicMock()
        page.main_frame.child_frames = []

        captured = {}
        def fake_human_type(page_arg, raw, text, cfg_arg, cdp_session=None):
            captured["typing_delay"] = cfg_arg.typing_delay

        def fake_scroll(*args, **kwargs):
            return ({"x": 100, "y": 100, "width": 50, "height": 30}, 100, 100)

        with patch.object(h, "human_type", side_effect=fake_human_type), \
             patch.object(h, "scroll_to_element", side_effect=fake_scroll):
            h.patch_page(page, cfg, cursor)
            page.fill("#password", "secret", human_config={"typing_delay": 150})

        assert captured["typing_delay"] == 150

    def test_element_handle_type_uses_per_call_human_config(self):
        """el.type(text, human_config={...}) merges per-call overrides on the
        ElementHandle path (which doesn't go through page.type)."""
        from cloakbrowser.human import _patch_single_element_handle_sync, _CursorState
        from cloakbrowser.human.config import resolve_config
        import cloakbrowser.human as h
        from unittest.mock import MagicMock, patch

        cfg = resolve_config("default", {
            "idle_between_actions": False,
            "field_switch_delay": (0, 1),
        })
        cursor = _CursorState()
        cursor.initialized = True
        cursor.x = 50
        cursor.y = 50

        page = MagicMock()
        page.viewport_size = {"width": 1280, "height": 720}
        page._original = MagicMock()

        el = MagicMock()
        el._human_patched = False
        el.bounding_box = MagicMock(
            return_value={"x": 200, "y": 200, "width": 100, "height": 30}
        )
        el.evaluate = MagicMock(return_value=True)
        el.is_checked = MagicMock(return_value=False)
        el.query_selector = MagicMock(return_value=None)
        el.query_selector_all = MagicMock(return_value=[])
        el.wait_for_selector = MagicMock(return_value=None)
        el.scroll_into_view_if_needed = MagicMock()

        raw_mouse = MagicMock()
        raw_keyboard = MagicMock()

        captured = {}
        def fake_human_type(page_arg, raw, text, cfg_arg, cdp_session=None):
            captured["typing_delay"] = cfg_arg.typing_delay

        with patch.object(h, "human_type", side_effect=fake_human_type):
            _patch_single_element_handle_sync(
                el, page, cfg, cursor, raw_mouse, raw_keyboard,
                page._original, None, None,
            )
            el.type("abc", human_config={"typing_delay": 25})

        assert captured["typing_delay"] == 25


# =========================================================================
# 17. scroll_into_view_if_needed humanization
# =========================================================================

class TestScrollIntoViewIfNeeded:
    """scroll_into_view_if_needed should run through the same
    accelerate → cruise → decelerate → overshoot wheel sequence as page.click—
    not Playwright's instant-snap default."""

    def test_human_scroll_into_view_skips_when_in_viewport(self):
        """Already-visible elements: no wheel events, just return."""
        from cloakbrowser.human.scroll import human_scroll_into_view
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", None)
        page = MagicMock()
        page.viewport_size = {"width": 1280, "height": 720}
        raw = MagicMock()
        # Box is dead-center of viewport — squarely in scroll_target_zone
        in_view_box = {"x": 200, "y": 300, "width": 50, "height": 30}

        box, cx, cy = human_scroll_into_view(
            page, raw, lambda: in_view_box, 0, 0, cfg,
        )
        assert box == in_view_box
        assert not raw.wheel.called, "In-viewport elements shouldn't trigger wheel events"

    def test_human_scroll_into_view_scrolls_when_below_fold(self):
        """Below-fold elements: wheel events fire, eventually box becomes visible."""
        from cloakbrowser.human.scroll import human_scroll_into_view
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", {
            "scroll_overshoot_chance": 0,        # deterministic
            "scroll_pre_move_delay": (0, 1),
            "scroll_pause_fast": (0, 1),
            "scroll_pause_slow": (0, 1),
            "scroll_settle_delay": (0, 1),
        })
        page = MagicMock()
        page.viewport_size = {"width": 1280, "height": 720}
        raw = MagicMock()

        # First box is far below the fold; subsequent boxes "come into view"
        # so the loop terminates after a few wheel bursts.
        boxes = [
            {"x": 200, "y": 2000, "width": 50, "height": 30},
            {"x": 200, "y": 1500, "width": 50, "height": 30},
            {"x": 200, "y": 1000, "width": 50, "height": 30},
            {"x": 200, "y": 400, "width": 50, "height": 30},   # in viewport
            {"x": 200, "y": 400, "width": 50, "height": 30},
            {"x": 200, "y": 400, "width": 50, "height": 30},
        ]
        idx = {"i": 0}
        def get_box():
            i = min(idx["i"], len(boxes) - 1)
            idx["i"] += 1
            return boxes[i]

        human_scroll_into_view(page, raw, get_box, 0, 0, cfg)
        assert raw.wheel.called, "Below-fold scroll should produce wheel events"

    def test_element_handle_scroll_into_view_if_needed_humanized(self):
        """el.scroll_into_view_if_needed() routes through human_scroll_into_view."""
        from cloakbrowser.human import _patch_single_element_handle_sync, _CursorState
        from cloakbrowser.human.config import resolve_config
        import cloakbrowser.human as h
        from unittest.mock import MagicMock, patch

        cfg = resolve_config("default", None)
        cursor = _CursorState()
        cursor.initialized = True
        cursor.x = 50
        cursor.y = 50

        page = MagicMock()
        page.viewport_size = {"width": 1280, "height": 720}
        page._original = MagicMock()

        el = MagicMock()
        el._human_patched = False
        el.bounding_box = MagicMock(
            return_value={"x": 200, "y": 200, "width": 50, "height": 30}
        )
        el.evaluate = MagicMock(return_value=False)
        el.is_checked = MagicMock(return_value=False)
        el.query_selector = MagicMock(return_value=None)
        el.query_selector_all = MagicMock(return_value=[])
        el.wait_for_selector = MagicMock(return_value=None)
        # Make sure the original method exists so the patch is wired up
        el.scroll_into_view_if_needed = MagicMock()

        called = {"count": 0}
        def fake(*args, **kwargs):
            called["count"] += 1
            return ({"x": 200, "y": 200, "width": 50, "height": 30}, 100, 100)

        with patch.object(h, "human_scroll_into_view", side_effect=fake):
            _patch_single_element_handle_sync(
                el, page, cfg, cursor, MagicMock(), MagicMock(),
                page._original, None, None,
            )
            # Patched method should now invoke our humanized helper
            el.scroll_into_view_if_needed()

        assert called["count"] >= 1, "humanized scroll helper was never called"

    def test_locator_scroll_into_view_if_needed_humanized(self):
        """Locator.scroll_into_view_if_needed() also goes through humanized scroll."""
        import cloakbrowser.human as h
        from cloakbrowser.human import _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock, patch

        # Patch Locator class fresh
        _ensure_locator_patched()

        from playwright.sync_api._generated import Locator

        cfg = resolve_config("default", None)
        cursor = _CursorState()
        cursor.x = 50
        cursor.y = 50
        cursor.initialized = True

        page = MagicMock()
        page._original = MagicMock()
        page._human_cfg = cfg
        page._human_cursor = cursor
        page._human_raw_mouse = MagicMock()
        page.viewport_size = {"width": 1280, "height": 720}

        # Build a Locator-like object satisfying the patched method
        loc = MagicMock(spec=Locator)
        loc.page = page
        impl_obj = MagicMock()
        impl_obj._selector = "#x"
        loc._impl_obj = impl_obj
        loc.bounding_box = MagicMock(
            return_value={"x": 100, "y": 100, "width": 50, "height": 30}
        )

        called = {"count": 0, "cfg": None}
        def fake(*args, **kwargs):
            called["count"] += 1
            # cfg is the 6th positional arg (page, raw, get_box, cx, cy, cfg)
            called["cfg"] = args[5] if len(args) >= 6 else kwargs.get("cfg")
            return ({"x": 100, "y": 100, "width": 50, "height": 30}, 200, 200)

        with patch.object(h, "human_scroll_into_view", side_effect=fake):
            Locator.scroll_into_view_if_needed(
                loc, human_config={"scroll_overshoot_chance": 0.5},
            )

        assert called["count"] == 1
        # Per-call override merged into the cfg passed downstream
        assert called["cfg"].scroll_overshoot_chance == 0.5
        # Cursor was updated from the helper's return value
        assert cursor.x == 200 and cursor.y == 200


# =========================================================================
# Direct runner (backwards compat)
# =========================================================================

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short", "-x"]))
