"""
Unit + integration tests for the humanize layer.
Covers: config resolution, Bézier math, fill clearing, async compat,
and bot-detection form interaction.

Run: python tests/test_humanize_unit.py
"""
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
    assert cfg.mouse_min_steps > 0, "mouse_min_steps should be positive"
    assert cfg.mouse_max_steps > cfg.mouse_min_steps, "mouse_max_steps should be > min"
    assert len(cfg.initial_cursor_x) == 2
    assert len(cfg.initial_cursor_y) == 2
    assert cfg.typing_delay > 0, "typing_delay should be positive"

test("default config resolves", test_default_config)

def test_careful_config():
    from cloakbrowser.human.config import resolve_config
    cfg = resolve_config("careful", None)
    assert cfg.mouse_min_steps > 0
    default_cfg = resolve_config("default", None)
    assert cfg.typing_delay >= default_cfg.typing_delay, "careful should have >= typing delays"

test("careful config resolves", test_careful_config)

def test_custom_override():
    from cloakbrowser.human.config import resolve_config
    cfg = resolve_config("default", {"mouse_min_steps": 100, "mouse_max_steps": 200})
    assert cfg.mouse_min_steps == 100, f"Override failed: {cfg.mouse_min_steps}"
    assert cfg.mouse_max_steps == 200, f"Override failed: {cfg.mouse_max_steps}"

test("custom config override", test_custom_override)

def test_rand_functions():
    from cloakbrowser.human.config import rand, rand_range
    for _ in range(100):
        v = rand(10, 20)
        assert 10 <= v <= 20, f"rand out of range: {v}"
    for _ in range(100):
        v = rand_range([5, 15])
        assert 5 <= v <= 15, f"rand_range out of range: {v}"

test("rand and rand_range within bounds", test_rand_functions)

def test_sleep_ms():
    from cloakbrowser.human.config import sleep_ms
    t0 = time.time()
    sleep_ms(50)
    elapsed = (time.time() - t0) * 1000
    assert elapsed >= 40, f"sleep_ms too short: {elapsed:.0f} ms"
    assert elapsed < 200, f"sleep_ms too long: {elapsed:.0f} ms"

test("sleep_ms timing", test_sleep_ms)


# =========================================================================
# 2. Bézier math (via human_move recording)
# =========================================================================
print("\n" + "=" * 60)
print("  BÉZIER MATH (via mouse movement recording)")
print("=" * 60)

def test_human_move_generates_points():
    """human_move should generate multiple intermediate mouse.move calls."""
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
    assert len(moves) >= 10, f"Expected >= 10 moves, got {len(moves)}"
    # Last move should be near target
    last_x, last_y = moves[-1]
    assert abs(last_x - 500) < 10, f"Last x too far: {last_x}"
    assert abs(last_y - 300) < 10, f"Last y too far: {last_y}"

test("human_move generates multiple points", test_human_move_generates_points)

def test_human_move_smoothness():
    """No jumps > 50% of total distance between consecutive points."""
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
        assert jump < max_jump, f"Jump too large at step {i}: {jump:.1f}"

test("human_move smoothness (no large jumps)", test_human_move_smoothness)

def test_human_move_short_distance():
    """human_move should handle very short distances."""
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
    assert len(moves) >= 1, "Should have at least 1 move"

test("human_move handles short distances", test_human_move_short_distance)

def test_human_move_not_straight_line():
    """Bézier curve should deviate from a straight line."""
    from cloakbrowser.human.mouse import human_move
    from cloakbrowser.human.config import resolve_config
    cfg = resolve_config("default", None)

    moves = []
    class FakeRawMouse:
        def move(self, x, y, **kw): moves.append((x, y))
        def down(self, **kw): pass
        def up(self, **kw): pass
        def wheel(self, dx, dy): pass

    # Horizontal move — y should deviate from 0
    human_move(FakeRawMouse(), 0, 0, 500, 0, cfg)
    max_y_deviation = max(abs(y) for _, y in moves)
    # At least some deviation (Bézier curves aren't perfectly straight)
    # Run multiple times since it's random
    deviations = []
    for _ in range(5):
        moves.clear()
        human_move(FakeRawMouse(), 0, 0, 500, 0, cfg)
        deviations.append(max(abs(y) for _, y in moves))
    max_dev = max(deviations)
    assert max_dev > 0.5, f"Curve appears too straight, max deviation: {max_dev:.2f}"

test("human_move is not a straight line (Bézier)", test_human_move_not_straight_line)

def test_click_target_computation():
    from cloakbrowser.human.mouse import click_target
    from cloakbrowser.human.config import resolve_config
    cfg = resolve_config("default", None)
    box = {"x": 100, "y": 200, "width": 150, "height": 40}
    for _ in range(50):
        t = click_target(box, False, cfg)
        assert 100 <= t.x <= 250, f"click_target x out of box: {t.x}"
        assert 200 <= t.y <= 240, f"click_target y out of box: {t.y}"

test("click_target within bounding box", test_click_target_computation)


# =========================================================================
# 3. Fill clearing (sync, with real browser)
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
    val_before = page.locator('#searchInput').input_value()
    assert val_before == 'initial text', f"Initial type failed: '{val_before}'"

    page.locator('#searchInput').fill('replaced text')
    time.sleep(0.5)
    val_after = page.locator('#searchInput').input_value()
    assert val_after == 'replaced text', f"Fill did not replace: '{val_after}'"
    assert 'initial' not in val_after, "Old text still present"

    browser.close()

test("fill() clears existing text", test_fill_clears_existing)

def test_fill_timing_is_human():
    from cloakbrowser import launch
    browser = launch(headless=True, humanize=True)
    page = browser.new_page()
    page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
    time.sleep(1)

    t0 = time.time()
    page.locator('#searchInput').fill('Human speed test')
    elapsed_ms = int((time.time() - t0) * 1000)
    assert elapsed_ms > 1000, f"fill() too fast: {elapsed_ms} ms"

    browser.close()

test("fill() timing is humanized (>1s)", test_fill_timing_is_human)

def test_clear_empties_field():
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
    assert val == '', f"clear() did not empty: '{val}'"

    browser.close()

test("clear() empties field", test_clear_empties_field)


# =========================================================================
# 4. Async compat
# =========================================================================
print("\n" + "=" * 60)
print("  ASYNC COMPATIBILITY")
print("=" * 60)

def test_async_config_imports():
    from cloakbrowser.human.mouse_async import AsyncRawMouse, async_human_move
    from cloakbrowser.human.keyboard_async import AsyncRawKeyboard, async_human_type
    from cloakbrowser.human.scroll_async import async_scroll_to_element
    from cloakbrowser.human import patch_page_async, patch_browser_async, patch_context_async
    assert callable(async_human_move)
    assert callable(async_human_type)
    assert callable(async_scroll_to_element)
    assert callable(patch_page_async)
    assert callable(patch_browser_async)
    assert callable(patch_context_async)

test("async modules import successfully", test_async_config_imports)

def test_async_locator_patching():
    import cloakbrowser.human as h
    h._locator_async_patched = False
    h._patch_locator_class_async()
    assert h._locator_async_patched, "Async locator patching failed"
    from playwright.async_api._generated import Locator as AsyncLocator
    assert 'humanized' in AsyncLocator.fill.__name__, f"Not patched: {AsyncLocator.fill.__name__}"

test("async Locator class patching", test_async_locator_patching)

def test_async_sleep():
    from cloakbrowser.human.config import async_sleep_ms
    import asyncio
    assert asyncio.iscoroutinefunction(async_sleep_ms)

test("async_sleep_ms is coroutine", test_async_sleep)


# =========================================================================
# 5. Bot detection form — deviceandbrowserinfo.com
# =========================================================================
print("\n" + "=" * 60)
print("  BOT DETECTION FORM (deviceandbrowserinfo.com)")
print("=" * 60)

def test_bot_detection_form():
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
    suspicious_behavior = '"suspiciousClientSideBehavior": true' in body_text
    cdp_mouse_leak = '"hasCDPMouseLeak": true' in body_text

    print(f"    superHumanSpeed: {super_human}")
    print(f"    suspiciousClientSideBehavior: {suspicious_behavior}")
    print(f"    hasCDPMouseLeak: {cdp_mouse_leak}")

    assert not super_human, "superHumanSpeed detected"
    assert not suspicious_behavior, "suspiciousClientSideBehavior detected"

    cdp_detected = '"isAutomatedWithCDP": true' in body_text
    if cdp_detected:
        print("    [INFO] isAutomatedWithCDP=true — CloakBrowser stealth issue, not humanize")

    browser.close()

test("bot detection form — behavioral checks pass", test_bot_detection_form)

def test_bot_detection_form_timing():
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
    assert elapsed_ms > 3000, f"Form filled too fast: {elapsed_ms} ms"

    browser.close()

test("bot detection form timing (>3s)", test_bot_detection_form_timing)


# =========================================================================
# 6. Locator patching integrity
# =========================================================================
print("\n" + "=" * 60)
print("  LOCATOR PATCHING INTEGRITY")
print("=" * 60)

def test_locator_methods_patched():
    from cloakbrowser import launch
    browser = launch(headless=True, humanize=True)
    page = browser.new_page()

    from playwright.sync_api._generated import Locator
    methods = [
        'fill', 'click', 'type', 'dblclick', 'hover',
        'check', 'uncheck', 'set_checked', 'select_option',
        'press', 'press_sequentially', 'tap', 'drag_to', 'clear',
    ]
    for method in methods:
        fn = getattr(Locator, method)
        assert 'humanized' in fn.__name__, f"Locator.{method} not patched: {fn.__name__}"

    browser.close()

test("all 14 Locator methods patched", test_locator_methods_patched)

def test_page_methods_patched():
    from cloakbrowser import launch
    browser = launch(headless=True, humanize=True)
    page = browser.new_page()

    assert hasattr(page, '_original'), "page._original missing"
    assert 'human' in str(page.click), "page.click not humanized"
    assert 'human' in str(page.fill), "page.fill not humanized"

    browser.close()

test("page-level methods patched", test_page_methods_patched)

def test_non_humanized_locator_fallback():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        time.sleep(1)

        assert not hasattr(page, '_original'), "Plain page should not have _original"

        t0 = time.time()
        page.locator('#searchInput').fill('test')
        elapsed = (time.time() - t0) * 1000
        assert elapsed < 500, f"Non-humanized fill too slow: {elapsed:.0f} ms"

        browser.close()

test("non-humanized page uses original methods", test_non_humanized_locator_fallback)


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
