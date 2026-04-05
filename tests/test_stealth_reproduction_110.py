# tests/test_stealth_reproduction_110.py
"""
Exact reproduction of issue #110 detection vectors.
Proves all three leaks (isInputElement, isSelectorFocused, typeShiftSymbol)
are fixed with CDP isolated worlds.
"""
import asyncio
import pytest

@pytest.mark.slow
class TestIssue110Reproduction:

    @pytest.mark.asyncio
    async def test_exact_reproduction_from_issue(self):
        """Exact detection script from issue #110 — must produce zero detections."""
        from cloakbrowser import launch_async

        browser = await launch_async(headless=True, humanize=True)
        page = await browser.new_page()

        await page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        await asyncio.sleep(1)

        # === EXACT detection from issue #110 ===
        await page.evaluate("""
            () => {
                window.__detections = {
                    evaluateQS: [],
                    untrustedKeydown: []
                };

                // Detection 1: querySelector from evaluate context
                const origQS = document.querySelector.bind(document);
                document.querySelector = function(sel) {
                    try { throw new Error(); } catch (e) {
                        if (e.stack.includes(':302:')) {
                            window.__detections.evaluateQS.push(sel);
                        }
                    }
                    return origQS(sel);
                };

                // Detection 2: untrusted keyboard events
                document.addEventListener('keydown', (e) => {
                    if (!e.isTrusted) {
                        window.__detections.untrustedKeydown.push(e.key);
                    }
                }, true);
            }
        """)

        # === Trigger all three vectors from issue ===

        # Vector 1: isInputElement — click triggers querySelector check
        await page.click('#searchInput')
        await asyncio.sleep(0.3)

        # Vector 2+3: typeShiftSymbol — type text with shift symbols
        await page.keyboard.type('Hello!@#$%^&*()')
        await asyncio.sleep(0.5)

        # === Verify: zero detections ===
        detections = await page.evaluate('() => window.__detections')

        qs_leaks = detections['evaluateQS']
        untrusted = detections['untrustedKeydown']

        print(f"\n{'='*60}")
        print(f"Issue #110 Reproduction Results:")
        print(f"  querySelector from evaluate: {len(qs_leaks)} detections")
        print(f"  Untrusted keyboard events:   {len(untrusted)} detections")
        print(f"{'='*60}")

        assert len(qs_leaks) == 0, (
            f"LEAK: querySelector called from evaluate context: {qs_leaks}"
        )
        assert len(untrusted) == 0, (
            f"LEAK: Untrusted keyboard events detected: {untrusted}"
        )

        await browser.close()

    @pytest.mark.asyncio
    async def test_all_21_shift_symbols_trusted(self):
        """Every single shift symbol must produce isTrusted=true."""
        from cloakbrowser import launch_async

        browser = await launch_async(headless=True, humanize=True)
        page = await browser.new_page()

        await page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        await asyncio.sleep(1)

        await page.evaluate("""
            () => {
                window.__keyResults = { trusted: [], untrusted: [] };
                const input = document.querySelector('#searchInput');
                input.addEventListener('keydown', (e) => {
                    const list = e.isTrusted ? 'trusted' : 'untrusted';
                    window.__keyResults[list].push(e.key);
                }, true);
            }
        """)

        await page.click('#searchInput')
        await asyncio.sleep(0.3)

        # Type ALL 21 shift symbols
        all_shift = '!@#$%^&*()_+{}|:"<>?~'
        await page.keyboard.type(all_shift)
        await asyncio.sleep(1)

        results = await page.evaluate('() => window.__keyResults')

        print(f"\n{'='*60}")
        print(f"All 21 Shift Symbols Test:")
        print(f"  Trusted:   {results['trusted']}")
        print(f"  Untrusted: {results['untrusted']}")
        print(f"{'='*60}")

        # Every shift symbol must be trusted
        for sym in all_shift:
            assert sym in results['trusted'], f"'{sym}' NOT in trusted events"
            assert sym not in results['untrusted'], f"'{sym}' IS in untrusted events"

        await browser.close()

    @pytest.mark.asyncio
    async def test_clear_uses_isolated_world(self):
        """clear() calls isSelectorFocused — must not leak evaluate."""
        from cloakbrowser import launch_async

        browser = await launch_async(headless=True, humanize=True)
        page = await browser.new_page()

        await page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        await asyncio.sleep(1)

        await page.evaluate("""
            () => {
                window.__evalLeaks = [];
                const origQS = document.querySelector.bind(document);
                document.querySelector = function(sel) {
                    try { throw new Error(); } catch (e) {
                        if (e.stack.includes(':302:')) {
                            window.__evalLeaks.push(sel);
                        }
                    }
                    return origQS(sel);
                };
            }
        """)

        # fill → click + type (isInputElement + isSelectorFocused)
        await page.locator('#searchInput').fill('some text')
        await asyncio.sleep(0.3)

        # clear → isSelectorFocused check
        await page.locator('#searchInput').clear()
        await asyncio.sleep(0.3)

        leaks = await page.evaluate('() => window.__evalLeaks')
        assert len(leaks) == 0, f"clear() leaked via evaluate: {leaks}"

        val = await page.locator('#searchInput').input_value()
        assert val == '', f"clear() didn't clear: '{val}'"

        await browser.close()
