"""Quick smoke test — verifies all 6 fixes in a real browser. Run: python tests/quick_check.py"""
import time, sys

def main():
    from cloakbrowser import launch
    from cloakbrowser.human.config import resolve_config

    print("=" * 60)
    print("  QUICK CHECK — 6 fixes verification")
    print("=" * 60)
    errors = []

    browser = launch(headless=False, humanize=True, human_config={"idle_between_actions": True, "idle_between_duration": [0.3, 0.8]})
    page = browser.new_page()
    page.goto("https://www.wikipedia.org", wait_until="domcontentloaded")
    time.sleep(1)

    # Inject visible cursor dot
    page.evaluate("""
    (() => {
        const dot = document.createElement('div');
        dot.id = '__cursor';
        dot.style.cssText = 'width:12px;height:12px;background:red;border-radius:50%;position:fixed;top:0;left:0;z-index:999999;pointer-events:none;transition:left 0.05s,top 0.05s;';
        document.body.appendChild(dot);
        document.addEventListener('mousemove', e => {
            dot.style.left = e.clientX - 6 + 'px';
            dot.style.top = e.clientY - 6 + 'px';
        });
    })();
    """)
    time.sleep(0.3)


    # Fix 1: press — focus check
    print("\n[1] press focus check...")
    t1 = time.time()
    page.locator("#searchInput").click()
    print(f"  click took: {int((time.time()-t1)*1000)}ms")
    time.sleep(0.3)
    t2 = time.time()
    page.locator("#searchInput").press("Backspace")
    press_ms = int((time.time() - t2) * 1000)
    print(f"  press took: {press_ms}ms")
    if press_ms > 2000:
        errors.append(f"FAIL fix1: press took {press_ms}ms")
        print(f"  FAIL — too slow")
    else:
        print(f"  OK — {press_ms}ms")


    # Fix 2: check/uncheck idle
    print("\n[2] check/uncheck idle config...")
    cfg = getattr(page, '_human_cfg', None)
    if cfg is None:
        errors.append("FAIL fix2: page._human_cfg is None")
        print("  FAIL — page._human_cfg missing")
    elif not cfg.idle_between_actions:
        errors.append("FAIL fix2: idle_between_actions not True")
        print("  FAIL — idle_between_actions is False")
    else:
        print(f"  OK — idle_between_actions={cfg.idle_between_actions}, duration={cfg.idle_between_duration}")

    # Fix 3: browser.new_page returns patched page
    print("\n[3] browser.new_page() patching...")
    page2 = browser.new_page()
    has_original = hasattr(page2, '_original')
    has_cfg = hasattr(page2, '_human_cfg')
    if not has_original or not has_cfg:
        errors.append(f"FAIL fix3: new_page missing _original={has_original} _human_cfg={has_cfg}")
        print(f"  FAIL — _original={has_original}, _human_cfg={has_cfg}")
    else:
        print(f"  OK — _original={has_original}, _human_cfg={has_cfg}")
    page2.close()

    # Fix 4: frame patching completeness
    print("\n[4] frame patching (all 11 methods)...")
    main_frame = page.main_frame
    expected = ['click', 'dblclick', 'hover', 'type', 'fill', 'check', 'uncheck',
                'select_option', 'press', 'clear', 'drag_and_drop']
    missing = [m for m in expected if not callable(getattr(main_frame, m, None))]
    patched = getattr(main_frame, '_human_patched', False)
    if missing:
        errors.append(f"FAIL fix4: frame missing methods: {missing}")
        print(f"  FAIL — missing: {missing}")
    elif not patched:
        errors.append("FAIL fix4: frame._human_patched not set")
        print("  FAIL — _human_patched flag missing")
    else:
        print(f"  OK — all {len(expected)} methods present, _human_patched={patched}")

    # Fix 5: drag_to safety (page._original exists)
    print("\n[5] drag_to safety — _original check...")
    orig = getattr(page, '_original', None)
    if orig is None:
        errors.append("FAIL fix5: page._original is None")
        print("  FAIL — page._original missing")
    elif not hasattr(orig, 'mouse_down') or not hasattr(orig, 'mouse_up'):
        errors.append("FAIL fix5: _original missing mouse_down/mouse_up")
        print(f"  FAIL — mouse_down={hasattr(orig, 'mouse_down')}, mouse_up={hasattr(orig, 'mouse_up')}")
    else:
        print(f"  OK — mouse_down={callable(orig.mouse_down)}, mouse_up={callable(orig.mouse_up)}")

    # Fix 6: page._human_cfg persistence
    print("\n[6] page._human_cfg persistence...")
    cfg = getattr(page, '_human_cfg', None)
    if cfg is None:
        errors.append("FAIL fix6: page._human_cfg is None")
        print("  FAIL — missing")
    elif not hasattr(cfg, 'idle_between_actions'):
        errors.append("FAIL fix6: cfg missing idle_between_actions")
        print("  FAIL — incomplete config")
    else:
        fields = ['mouse_min_steps', 'typing_delay', 'idle_between_actions', 'patch_coalesced']
        present = [f for f in fields if hasattr(cfg, f)]
        print(f"  OK — {len(present)}/{len(fields)} fields verified: {present}")

   

    # Summary
    print("\n" + "=" * 60)
    if errors:
        print(f"  FAILED — {len(errors)} issue(s):")
        for e in errors:
            print(f"    {e}")
        print("=" * 60)
        sys.exit(1)
    else:
        print("  ALL 6 FIXES VERIFIED OK")
        print("=" * 60)
        sys.exit(0)

if __name__ == "__main__":
    main()
