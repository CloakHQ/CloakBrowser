"""
Unit + integration tests for the humanize layer.
Run directly: python tests/test_humanize_unit.py
Skipped by pytest CI: marked as slow.
"""
import pytest
pytestmark = pytest.mark.slow

if __name__ == "__main__":
    import time
    import math
    import sys

    PROXY = ''
    results = []

    def test(name, fn):
        try:
            fn()
            print(f"  [PASS] {name}")
            results.append((name, "PASS"))
        except Exception as e:
            print(f"  [FAIL] {name} — {e}")
            results.append((name, "FAIL"))

    # =========================================================================
    # 1. Config resolution
    # =========================================================================
    print("\n" + "=" * 60)
    print("  CONFIG RESOLUTION")
    print("=" * 60)

    def test_default_config():
        from cloakbrowser.human.config import resolve_config, HumanConfig
        cfg = resolve_config("default", None)
        assert isinstance(cfg, HumanConfig)
        assert cfg.mouse_min_steps > 0
        assert cfg.mouse_max_steps > cfg.mouse_min_steps
        assert len(cfg.initial_cursor_x) == 2
        assert len(cfg.initial_cursor_y) == 2
        assert cfg.typing_delay > 0

    test("default config resolves", test_default_config)

    def test_careful_config():
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("careful", None)
        assert cfg.mouse_min_steps > 0
        default_cfg = resolve_config("default", None)
        assert cfg.typing_delay >= default_cfg.typing_delay

    test("careful config resolves", test_careful_config)

    def test_custom_override():
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default", {"mouse_min_steps": 100, "mouse_max_steps": 200})
        assert cfg.mouse_min_steps == 100
        assert cfg.mouse_max_steps == 200

    test("custom config override", test_custom_override)

    def test_rand_functions():
        from cloakbrowser.human.config import rand, rand_range
        for _ in range(100):
            v = rand(10, 20)
            assert 10 <= v <= 20
        for _ in range(100):
            v = rand_range([5, 15])
            assert 5 <= v <= 15

    test("rand and rand_range within bounds", test_rand_functions)

    def test_sleep_ms():
        from cloakbrowser.human.config import sleep_ms
        t0 = time.time()
        sleep_ms(50)
        elapsed = (time.time() - t0) * 1000
        assert elapsed >= 40
        assert elapsed < 200

    test("sleep_ms timing", test_sleep_ms)

    # =========================================================================
    # 2. Bézier math
    # =========================================================================
    print("\n" + "=" * 60)
    print("  BÉZIER MATH (via mouse movement recording)")
    print("=" * 60)

    def test_human_move_generates_points():
        from cloakbrowser.human.mouse import human_move
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default", None)
        moves = []
        class FakeRawMouse:
            def move(self, x, y, **kw): moves.append((x, y))
            def down(self, **kw): pass
            def up(self, **kw): pass
            def wheel(self, dx, dy): pass
        human_move(FakeRawMouse(), 0, 0, 500, 300, cfg)
        assert len(moves) >= 10
        last_x, last_y = moves[-1]
        assert abs(last_x - 500) < 10
        assert abs(last_y - 300) < 10

    test("human_move generates multiple points", test_human_move_generates_points)

    def test_human_move_smoothness():
        from cloakbrowser.human.mouse import human_move
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default", None)
        moves = []
        class FakeRawMouse:
            def move(self, x, y, **kw): moves.append((x, y))
            def down(self, **kw): pass
            def up(self, **kw): pass
            def wheel(self, dx, dy): pass
        human_move(FakeRawMouse(), 0, 0, 400, 400, cfg)
        total_dist = math.sqrt(400**2 + 400**2)
        max_jump = total_dist * 0.5
        for i in range(1, len(moves)):
            dx = moves[i][0] - moves[i-1][0]
            dy = moves[i][1] - moves[i-1][1]
            jump = math.sqrt(dx*dx + dy*dy)
            assert jump < max_jump

    test("human_move smoothness (no large jumps)", test_human_move_smoothness)

    def test_human_move_short_distance():
        from cloakbrowser.human.mouse import human_move
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default", None)
        moves = []
        class FakeRawMouse:
            def move(self, x, y, **kw): moves.append((x, y))
            def down(self, **kw): pass
            def up(self, **kw): pass
            def wheel(self, dx, dy): pass
        human_move(FakeRawMouse(), 100, 100, 103, 102, cfg)
        assert len(moves) >= 1

    test("human_move handles short distances", test_human_move_short_distance)

    def test_human_move_not_straight_line():
        from cloakbrowser.human.mouse import human_move
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default", None)
        moves = []
        class FakeRawMouse:
            def move(self, x, y, **kw): moves.append((x, y))
            def down(self, **kw): pass
            def up(self, **kw): pass
            def wheel(self, dx, dy): pass
        deviations = []
        for _ in range(5):
            moves.clear()
            human_move(FakeRawMouse(), 0, 0, 500, 0, cfg)
            deviations.append(max(abs(y) for _, y in moves))
        assert max(deviations) > 0.5

    test("human_move is not a straight line (Bézier)", test_human_move_not_straight_line)

    def test_click_target_computation():
        from cloakbrowser.human.mouse import click_target
        from cloakbrowser.human.config import resolve_config
        cfg = resolve_config("default", None)
        box = {"x": 100, "y": 200, "width": 150, "height": 40}
        for _ in range(50):
            t = click_target(box, False, cfg)
            assert 100 <= t.x <= 250
            assert 200 <= t.y <= 240

    test("click_target within bounding box", test_click_target_computation)

    # =========================================================================
    # 3. Fill clearing
    # =========================================================================
    print("\n" + "=" * 60)
    print("  FILL CLEARING (sync browser)")
    print("=" * 60)

    def test_fill_clears_existing():
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

    test("fill() clears existing text", test_fill_clears_existing)

    def test_fill_timing():
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

    test("fill() timing is humanized (>1s)", test_fill_timing)

    def test_clear_empties():
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

    test("clear() empties field", test_clear_empties)

    # =========================================================================
    # 4. Async compat
    # =========================================================================
    print("\n" + "=" * 60)
    print("  ASYNC COMPATIBILITY")
    print("=" * 60)

    def test_async_imports():
        from cloakbrowser.human.mouse_async import AsyncRawMouse, async_human_move
        from cloakbrowser.human.keyboard_async import AsyncRawKeyboard, async_human_type
        from cloakbrowser.human.scroll_async import async_scroll_to_element
        from cloakbrowser.human import patch_page_async, patch_browser_async, patch_context_async
        assert callable(async_human_move)
        assert callable(async_human_type)
        assert callable(async_scroll_to_element)

    test("async modules import successfully", test_async_imports)

    def test_async_locator_patch():
        import cloakbrowser.human as h
        h._locator_async_patched = False
        h._patch_locator_class_async()
        assert h._locator_async_patched
        from playwright.async_api._generated import Locator as AsyncLocator
        assert 'humanized' in AsyncLocator.fill.__name__

    test("async Locator class patching", test_async_locator_patch)

    def test_async_sleep():
        from cloakbrowser.human.config import async_sleep_ms
        import asyncio
        assert asyncio.iscoroutinefunction(async_sleep_ms)

    test("async_sleep_ms is coroutine", test_async_sleep)

    # =========================================================================
    # 5. Bot detection form
    # =========================================================================
    print("\n" + "=" * 60)
    print("  BOT DETECTION FORM (deviceandbrowserinfo.com)")
    print("=" * 60)

    def test_bot_detection():
        from cloakbrowser import launch
        browser = launch(headless=False, humanize=True, proxy=PROXY, geoip=True)
        page = browser.new_page()
        page.goto('https://deviceandbrowserinfo.com/are_you_a_bot_interactions', wait_until='domcontentloaded')
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
        body_text = page.locator('body').text_content()
        super_human = '"superHumanSpeed": true' in body_text
        suspicious = '"suspiciousClientSideBehavior": true' in body_text
        print(f"    superHumanSpeed: {super_human}")
        print(f"    suspiciousClientSideBehavior: {suspicious}")
        assert not super_human
        assert not suspicious
        browser.close()

    test("bot detection form — behavioral checks pass", test_bot_detection)

    def test_bot_detection_timing():
        from cloakbrowser import launch
        browser = launch(headless=True, humanize=True, proxy=PROXY, geoip=True)
        page = browser.new_page()
        page.goto('https://deviceandbrowserinfo.com/are_you_a_bot_interactions', wait_until='domcontentloaded')
        time.sleep(2)
        t0 = time.time()
        page.locator('#email').fill('test@example.com')
        page.locator('#password').fill('MyPassword!99')
        page.locator('button[type="submit"]').click()
        elapsed_ms = int((time.time() - t0) * 1000)
        time.sleep(3)
        print(f"    Form fill + submit took: {elapsed_ms} ms")
        assert elapsed_ms > 3000
        browser.close()

    test("bot detection form timing (>3s)", test_bot_detection_timing)

    # =========================================================================
    # 6. Locator patching integrity
    # =========================================================================
    print("\n" + "=" * 60)
    print("  LOCATOR PATCHING INTEGRITY")
    print("=" * 60)

    def test_locator_methods():
        from cloakbrowser import launch
        browser = launch(headless=True, humanize=True)
        page = browser.new_page()
        from playwright.sync_api._generated import Locator
        methods = ['fill', 'click', 'type', 'dblclick', 'hover', 'check', 'uncheck',
                   'set_checked', 'select_option', 'press', 'press_sequentially', 'tap', 'drag_to', 'clear']
        for method in methods:
            fn = getattr(Locator, method)
            assert 'humanized' in fn.__name__
        browser.close()

    test("all 14 Locator methods patched", test_locator_methods)

    def test_page_methods():
        from cloakbrowser import launch
        browser = launch(headless=True, humanize=True)
        page = browser.new_page()
        assert hasattr(page, '_original')
        assert 'human' in str(page.click)
        assert 'human' in str(page.fill)
        browser.close()

    test("page-level methods patched", test_page_methods)

    def test_non_humanized():
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
            time.sleep(1)
            assert not hasattr(page, '_original')
            t0 = time.time()
            page.locator('#searchInput').fill('test')
            elapsed = (time.time() - t0) * 1000
            assert elapsed < 500
            browser.close()

    test("non-humanized page uses original methods", test_non_humanized)

    # =========================================================================
    # 7. Focus check — press does not click when already focused
    # =========================================================================
    print("\n" + "=" * 60)
    print("  FOCUS CHECK (press / clear / pressSequentially)")
    print("=" * 60)

    def test_press_skips_click_when_focused():
        """press() should not move mouse if element is already focused."""
        from cloakbrowser.human import _patch_locator_class_sync, _is_selector_focused
        from unittest.mock import MagicMock, patch as mock_patch

        page = MagicMock()
        page._original = MagicMock()
        page._human_cfg = MagicMock()
        page._human_cfg.idle_between_actions = False

        click_count = {"n": 0}
        orig_click = page.click
        def counting_click(*a, **kw):
            click_count["n"] += 1
            return orig_click(*a, **kw)
        page.click = counting_click

        # Simulate element already focused
        with mock_patch("cloakbrowser.human._is_selector_focused", return_value=True):
            from playwright.sync_api._generated import Locator
            loc = MagicMock(spec=Locator)
            loc.page = page
            loc._impl_obj = MagicMock()
            loc._impl_obj._selector = "#test"

            # Call humanized press directly
            Locator.press(loc, "Enter")

        assert click_count["n"] == 0, f"press() clicked {click_count['n']} times when element was focused"

    test("press skips click when element already focused", test_press_skips_click_when_focused)

    def test_press_clicks_when_not_focused():
        """press() should click if element is NOT focused."""
        from unittest.mock import MagicMock, patch as mock_patch

        page = MagicMock()
        page._original = MagicMock()
        page._human_cfg = MagicMock()
        page._human_cfg.idle_between_actions = False

        click_count = {"n": 0}
        orig_click = page.click
        def counting_click(*a, **kw):
            click_count["n"] += 1
        page.click = counting_click

        with mock_patch("cloakbrowser.human._is_selector_focused", return_value=False):
            from playwright.sync_api._generated import Locator
            loc = MagicMock(spec=Locator)
            loc.page = page
            loc._impl_obj = MagicMock()
            loc._impl_obj._selector = "#test"

            Locator.press(loc, "Enter")

        assert click_count["n"] == 1, f"press() should click once when not focused, got {click_count['n']}"

    test("press clicks when element not focused", test_press_clicks_when_not_focused)

    # =========================================================================
    # 8. check/uncheck idle
    # =========================================================================
    print("\n" + "=" * 60)
    print("  CHECK/UNCHECK IDLE")
    print("=" * 60)

    def test_check_calls_idle_when_enabled():
        """Locator check() should call human_idle when idle_between_actions=True."""
        from unittest.mock import MagicMock, patch as mock_patch
        from cloakbrowser.human.config import resolve_config

        cfg = resolve_config("default", {"idle_between_actions": True, "idle_between_duration": [50, 100]})

        page = MagicMock()
        page._original = MagicMock()
        page._original.mouse_move = MagicMock()
        page._human_cfg = cfg

        idle_called = {"n": 0}
        original_idle = None
        def fake_idle(*a, **kw):
            idle_called["n"] += 1

        from playwright.sync_api._generated import Locator
        loc = MagicMock(spec=Locator)
        loc.page = page
        loc._impl_obj = MagicMock()
        loc._impl_obj._selector = "#checkbox"
        loc.is_checked = MagicMock(return_value=False)

        with mock_patch("cloakbrowser.human.human_idle", fake_idle):
            Locator.check(loc)

        assert idle_called["n"] >= 1, f"human_idle not called during check(), count={idle_called['n']}"

    test("check() calls human_idle when idle_between_actions=True", test_check_calls_idle_when_enabled)

    def test_uncheck_calls_idle_when_enabled():
        """Locator uncheck() should call human_idle when idle_between_actions=True."""
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
        loc = MagicMock(spec=Locator)
        loc.page = page
        loc._impl_obj = MagicMock()
        loc._impl_obj._selector = "#checkbox"
        loc.is_checked = MagicMock(return_value=True)

        with mock_patch("cloakbrowser.human.human_idle", fake_idle):
            Locator.uncheck(loc)

        assert idle_called["n"] >= 1, f"human_idle not called during uncheck(), count={idle_called['n']}"

    test("uncheck() calls human_idle when idle_between_actions=True", test_uncheck_calls_idle_when_enabled)

    # =========================================================================
    # 9. Frame patching completeness
    # =========================================================================
    print("\n" + "=" * 60)
    print("  FRAME PATCHING COMPLETENESS")
    print("=" * 60)

    def test_frame_all_methods_patched():
        """All 11 frame-level methods should be patched after _patch_single_frame_sync."""
        from cloakbrowser.human import _patch_single_frame_sync, _CursorState
        from cloakbrowser.human.config import resolve_config
        from unittest.mock import MagicMock

        cfg = resolve_config("default", None)
        cursor = _CursorState()
        page = MagicMock()
        page._original = MagicMock()
        frame = MagicMock()
        frame._human_patched = False

        raw_mouse = MagicMock()
        raw_keyboard = MagicMock()

        _patch_single_frame_sync(frame, page, cfg, cursor, raw_mouse, raw_keyboard, page._original)

        expected = ['click', 'dblclick', 'hover', 'type', 'fill',
                    'check', 'uncheck', 'select_option', 'press',
                    'clear', 'drag_and_drop']
        missing = []
        for method in expected:
            fn = getattr(frame, method, None)
            if fn is None:
                missing.append(method)
            elif not callable(fn):
                missing.append(f"{method} (not callable)")
            elif 'MagicMock' in type(fn).__name__ and not hasattr(fn, '_mock_name'):
                # Still original mock — not replaced
                pass
        # Verify they were reassigned (not the original MagicMock)
        for method in expected:
            fn = getattr(frame, method)
            assert not isinstance(fn, MagicMock), f"frame.{method} was not patched (still MagicMock)"

    test("frame has all 11 methods patched", test_frame_all_methods_patched)

    # =========================================================================
    # 10. drag_to safety check
    # =========================================================================
    print("\n" + "=" * 60)
    print("  DRAG_TO SAFETY CHECK")
    print("=" * 60)

    def test_drag_to_without_original():
        """drag_to should fall back to original when page._original is missing."""
        from playwright.sync_api._generated import Locator
        from unittest.mock import MagicMock

        page = MagicMock()
        # Remove _original to simulate edge case
        if hasattr(page, '_original'):
            del page._original
        page._original = None

        source_loc = MagicMock(spec=Locator)
        source_loc.page = page
        source_loc._impl_obj = MagicMock()
        source_loc._impl_obj._selector = "#src"
        source_loc.bounding_box = MagicMock(return_value={"x": 10, "y": 10, "width": 50, "height": 50})

        target_loc = MagicMock(spec=Locator)
        target_loc.page = page
        target_loc._impl_obj = MagicMock()
        target_loc._impl_obj._selector = "#tgt"
        target_loc.bounding_box = MagicMock(return_value={"x": 200, "y": 200, "width": 50, "height": 50})

        # Should not raise — falls back to original
        try:
            Locator.drag_to(source_loc, target_loc)
        except AttributeError:
            raise AssertionError("drag_to crashed without page._original — safety check missing")

    test("drag_to handles missing page._original", test_drag_to_without_original)

    # =========================================================================
    # 11. page._human_cfg is set
    # =========================================================================
    print("\n" + "=" * 60)
    print("  PAGE CONFIG PERSISTENCE")
    print("=" * 60)

    def test_page_human_cfg_set():
        """patch_page should set page._human_cfg for Locator access."""
        from cloakbrowser import launch
        browser = launch(headless=True, humanize=True)
        page = browser.new_page()
        assert hasattr(page, '_human_cfg'), "page._human_cfg not set"
        assert page._human_cfg is not None, "page._human_cfg is None"
        assert hasattr(page._human_cfg, 'idle_between_actions'), "cfg missing idle_between_actions"
        browser.close()

    test("page._human_cfg is set after patch", test_page_human_cfg_set)


    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "=" * 70)
    print("  TEST SUMMARY")
    print("=" * 70)
    passed = sum(1 for _, s in results if s == "PASS")
    failed = sum(1 for _, s in results if s == "FAIL")
    total = len(results)
    for name, status in results:
        icon = "OK" if status == "PASS" else "XX"
        print(f"  [{icon}] {name}")
    print(f"\n  {passed}/{total} passed, {failed} failed")
    if failed == 0:
        print("  *** ALL TESTS PASSED ***")
    else:
        print(f"  *** {failed} TESTS FAILED ***")
    print("=" * 70)
    sys.exit(0 if failed == 0 else 1)
