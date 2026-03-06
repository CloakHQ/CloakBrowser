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
