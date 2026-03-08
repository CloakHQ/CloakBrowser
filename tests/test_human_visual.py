"""
Visual + functional test for humanize.
Red dot = cursor, yellow = mouse held.
"""
import pytest
pytestmark = pytest.mark.slow

if __name__ == "__main__":
    from cloakbrowser import launch
    import time

    CURSOR_JS = """
    () => {
        if (document.getElementById('__hc')) return;
        const el = document.createElement('div');
        el.id = '__hc';
        el.style.cssText = 'width:14px;height:14px;background:red;border:2px solid darkred;border-radius:50%;position:fixed;z-index:2147483647;pointer-events:none;display:none;transition:background 0.05s;';
        document.body.appendChild(el);

        const trail = document.createElement('div');
        trail.id = '__hcTrail';
        trail.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:2147483646;pointer-events:none;overflow:hidden;';
        document.body.appendChild(trail);

        let dotCount = 0;
        const maxDots = 500;

        function updatePos(x, y) {
            el.style.display = 'block';
            el.style.left = (x - 9) + 'px';
            el.style.top = (y - 9) + 'px';

            if (dotCount < maxDots) {
                const dot = document.createElement('div');
                dot.style.cssText = 'width:3px;height:3px;background:rgba(255,0,0,0.3);border-radius:50%;position:fixed;pointer-events:none;left:'+(x-1)+'px;top:'+(y-1)+'px;';
                trail.appendChild(dot);
                dotCount++;
            }
        }

        document.addEventListener('mousemove', e => updatePos(e.clientX, e.clientY));
        document.addEventListener('drag', e => { if (e.clientX > 0) updatePos(e.clientX, e.clientY); });
        document.addEventListener('dragover', e => { if (e.clientX > 0) updatePos(e.clientX, e.clientY); });
        document.addEventListener('mousedown', () => { el.style.background = 'yellow'; });
        document.addEventListener('mouseup', () => { el.style.background = 'red'; });
        document.addEventListener('dragend', () => { el.style.background = 'red'; });
    }
    """

    def inject(page):
        try:
            page.evaluate(CURSOR_JS)
        except:
            pass
        time.sleep(0.3)

    results = []

    def step(name):
        print(f"\n{'='*60}")
        print(f"  STEP: {name}")
        print(f"{'='*60}")

    def check(name, passed, detail=""):
        status = "PASS" if passed else "FAIL"
        msg = f"  [{status}] {name}"
        if detail:
            msg += f" — {detail}"
        print(msg)
        results.append((name, status))

    print("=" * 70)
    print("  HUMAN-LIKE BEHAVIOR VISUAL TEST")
    print("  Watch the red dot — it should move smoothly like a real cursor")
    print("  Yellow = mouse button held")
    print("  Red trail dots = path taken")
    print("=" * 70)

    browser = launch(headless=False, humanize=True)
    page = browser.new_page()

    # ============================================================
    # SCENARIO 1: Wikipedia search
    # ============================================================
    step("Wikipedia — navigate and search")
    page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
    time.sleep(2)
    inject(page)
    time.sleep(1)

    print("  Watch: cursor moves to search box (Bezier curve)")
    t0 = time.time()
    page.locator('#searchInput').click()
    click_ms = int((time.time() - t0) * 1000)
    check("click on search input", click_ms > 200, f"{click_ms} ms")
    time.sleep(0.5)

    print("  Watch: characters appear one by one with varying speed")
    t0 = time.time()
    page.locator('#searchInput').fill('Python programming language')
    fill_ms = int((time.time() - t0) * 1000)
    val = page.locator('#searchInput').input_value()
    check("fill search box", val == 'Python programming language' and fill_ms > 2000, f"{fill_ms} ms, value='{val}'")
    time.sleep(0.5)

    print("  Watch: cursor moves to search box, double yellow flash, word selected")
    t0 = time.time()
    page.locator('#searchInput').dblclick()
    dbl_ms = int((time.time() - t0) * 1000)
    sel = page.evaluate('() => window.getSelection().toString().trim()')
    check("dblclick selects word", len(sel) > 0 and dbl_ms > 200, f"{dbl_ms} ms, selected='{sel}'")
    time.sleep(0.5)

    print("  Watch: old text cleared, new text typed")
    t0 = time.time()
    page.locator('#searchInput').fill('Artificial intelligence')
    fill2_ms = int((time.time() - t0) * 1000)
    val2 = page.locator('#searchInput').input_value()
    check("fill replaces text", val2 == 'Artificial intelligence' and fill2_ms > 1500, f"{fill2_ms} ms, value='{val2}'")
    time.sleep(0.5)

    print("  Watch: cursor moves to button without clicking")
    t0 = time.time()
    page.locator('button[type="submit"]').hover()
    hover_ms = int((time.time() - t0) * 1000)
    check("hover search button", hover_ms > 100, f"{hover_ms} ms")
    time.sleep(1)

    # ============================================================
    # SCENARIO 2: Form interaction — checkboxes
    # ============================================================
    step("Checkboxes — check and uncheck")
    page.goto('https://the-internet.herokuapp.com/checkboxes', wait_until='domcontentloaded')
    time.sleep(2)
    inject(page)
    time.sleep(1)

    cb1 = page.locator('input[type="checkbox"]').nth(0)
    cb2 = page.locator('input[type="checkbox"]').nth(1)

    print("  Watch: cursor moves to first checkbox, clicks")
    if cb1.is_checked():
        cb1.uncheck()
        time.sleep(0.5)

    t0 = time.time()
    cb1.check()
    check_ms = int((time.time() - t0) * 1000)
    check("check checkbox 1", cb1.is_checked() and check_ms > 200, f"{check_ms} ms, checked={cb1.is_checked()}")
    time.sleep(0.5)

    print("  Watch: cursor moves to second checkbox, clicks to uncheck")
    if not cb2.is_checked():
        cb2.check()
        time.sleep(0.5)

    t0 = time.time()
    cb2.uncheck()
    uncheck_ms = int((time.time() - t0) * 1000)
    check("uncheck checkbox 2", not cb2.is_checked() and uncheck_ms > 200, f"{uncheck_ms} ms, checked={cb2.is_checked()}")
    time.sleep(1)

    # ============================================================
    # SCENARIO 3: Dropdown
    # ============================================================
    step("Dropdown — select option")
    page.goto('https://the-internet.herokuapp.com/dropdown', wait_until='domcontentloaded')
    time.sleep(2)
    inject(page)
    time.sleep(1)

    print("  Watch: cursor moves to dropdown, hovers, option selected")
    t0 = time.time()
    page.locator('#dropdown').select_option('1')
    sel_ms = int((time.time() - t0) * 1000)
    val = page.locator('#dropdown').input_value()
    check("select option 1", val == '1' and sel_ms > 100, f"{sel_ms} ms, value='{val}'")
    time.sleep(0.5)

    t0 = time.time()
    page.locator('#dropdown').select_option('2')
    sel2_ms = int((time.time() - t0) * 1000)
    val2 = page.locator('#dropdown').input_value()
    check("select option 2", val2 == '2' and sel2_ms > 100, f"{sel2_ms} ms, value='{val2}'")
    time.sleep(1)

    # ============================================================
    # SCENARIO 4: Drag and drop
    # ============================================================
    step("Drag and Drop — move column A to B")
    page.goto('https://the-internet.herokuapp.com/drag_and_drop', wait_until='domcontentloaded')
    time.sleep(2)
    inject(page)
    time.sleep(1)

    before_a = page.locator('#column-a header').text_content().strip()
    before_b = page.locator('#column-b header').text_content().strip()
    print(f"  Before: A='{before_a}', B='{before_b}'")

    print("  Watch: cursor moves to A, turns yellow (held), moves to B, releases")
    t0 = time.time()
    page.locator('#column-a').drag_to(page.locator('#column-b'))
    drag_ms = int((time.time() - t0) * 1000)
    time.sleep(1)

    after_a = page.locator('#column-a header').text_content().strip()
    after_b = page.locator('#column-b header').text_content().strip()
    swapped = before_a != after_a
    print(f"  After:  A='{after_a}', B='{after_b}'")
    check("drag A to B", swapped and drag_ms > 300, f"{drag_ms} ms, swapped={swapped}")
    time.sleep(1)

    # ============================================================
    # SCENARIO 5: Text editing
    # ============================================================
    step("Text editing — type, press keys, clear")
    page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
    time.sleep(2)
    inject(page)
    time.sleep(1)

    print("  Watch: cursor clicks input, types character by character")
    t0 = time.time()
    page.locator('#searchInput').type('Hello World')
    type_ms = int((time.time() - t0) * 1000)
    val = page.locator('#searchInput').input_value()
    check("type 'Hello World'", val == 'Hello World' and type_ms > 1000, f"{type_ms} ms, value='{val}'")
    time.sleep(0.5)

    print("  Watch: cursor clicks, presses single key")
    t0 = time.time()
    page.locator('#searchInput').press('End')
    page.locator('#searchInput').press('!')
    press_ms = int((time.time() - t0) * 1000)
    val = page.locator('#searchInput').input_value()
    check("press '!' at end", '!' in val and press_ms > 100, f"{press_ms} ms, value='{val}'")
    time.sleep(0.5)

    print("  Watch: field gets cleared (Ctrl+A, Backspace)")
    t0 = time.time()
    page.locator('#searchInput').clear()
    clear_ms = int((time.time() - t0) * 1000)
    val = page.locator('#searchInput').input_value()
    check("clear field", val == '' and clear_ms > 100, f"{clear_ms} ms, value='{repr(val)}'")
    time.sleep(0.5)

    print("  Watch: press_sequentially types each key individually")
    t0 = time.time()
    page.locator('#searchInput').press_sequentially('Sequential')
    pseq_ms = int((time.time() - t0) * 1000)
    val = page.locator('#searchInput').input_value()
    check("press_sequentially", val == 'Sequential' and pseq_ms > 500, f"{pseq_ms} ms, value='{val}'")
    time.sleep(1)

    # ============================================================
    # SCENARIO 6: Mouse precision
    # ============================================================
    step("Mouse precision — move to coordinates")
    print("  Watch: cursor moves in a Bezier curve to (600, 400)")
    t0 = time.time()
    page.mouse.move(600, 400)
    move_ms = int((time.time() - t0) * 1000)
    check("mouse.move to (600,400)", move_ms > 100, f"{move_ms} ms")
    time.sleep(0.5)

    print("  Watch: cursor moves to (200, 200), clicks")
    t0 = time.time()
    page.mouse.click(200, 200)
    mclick_ms = int((time.time() - t0) * 1000)
    check("mouse.click at (200,200)", mclick_ms > 100, f"{mclick_ms} ms")
    time.sleep(0.5)

    print("  Watch: keyboard types directly (no click needed)")
    page.locator('#searchInput').click()
    time.sleep(0.3)
    t0 = time.time()
    page.keyboard.type('Direct keyboard')
    kb_ms = int((time.time() - t0) * 1000)
    check("keyboard.type", kb_ms > 500, f"{kb_ms} ms")
    time.sleep(1)

    # ============================================================
    # SUMMARY
    # ============================================================
    print("\n" + "=" * 70)
    print("  SUMMARY")
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
    print("=" * 70)

    input("\nPress Enter to close browser...")
    browser.close()
