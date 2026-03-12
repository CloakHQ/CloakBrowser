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
        browser = launch(headless=True, humanize=True)
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
        browser = launch(headless=True, humanize=True)
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
        browser = launch(headless=True, humanize=True)
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
        browser = launch(headless=True, humanize=True)
        page = browser.new_page()
        assert hasattr(page, '_original')
        assert hasattr(page, '_human_cfg')
        browser.close()

    def test_locator_methods_patched(self):
        from cloakbrowser import launch
        browser = launch(headless=True, humanize=True)
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
        browser = launch(headless=True, humanize=True)
        page = browser.new_page()
        assert page._human_cfg is not None
        assert hasattr(page._human_cfg, 'idle_between_actions')
        assert hasattr(page._human_cfg, 'mistype_chance')
        browser.close()


@pytest.mark.slow
class TestBrowserBotDetection:
    PROXY = ''

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
        browser = launch(headless=True, humanize=True, proxy=self.PROXY, geoip=True)
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
    def test_async_launch_click_fill(self):
        """launch_async(humanize=True) — async page.click and page.fill work end-to-end."""
        import asyncio
        from cloakbrowser import launch_async

        async def _run():
            browser = await launch_async(headless=True, humanize=True)
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

        asyncio.run(_run())


# =========================================================================
# Direct runner (backwards compat)
# =========================================================================

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short", "-x"]))
