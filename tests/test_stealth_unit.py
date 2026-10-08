"""
Unit tests for stealth / anti-detection fixes (issue #110).

Covers:
  - _SyncIsolatedWorld / _AsyncIsolatedWorld — CDP isolated-world lifecycle
  - _is_input_element / _is_selector_focused — stealth DOM queries with fallback
  - _type_shift_symbol / _type_shift_symbol (async) — CDP Input.dispatchKeyEvent path
  - Navigation invalidation (goto → stealth.invalidate)
  - patch_page stealth infrastructure wiring
  - SHIFT_SYMBOL_CODES / SHIFT_SYMBOL_KEYCODES completeness

All tests are fast, mock-based, and do NOT require a browser.
"""

import asyncio
import json
import math
import sys
import time

import pytest
from unittest.mock import MagicMock, AsyncMock, patch as mock_patch, call


# =========================================================================
# Helper: quick config
# =========================================================================

def _cfg(**overrides):
    from cloakbrowser.human.config import resolve_config
    return resolve_config("default", overrides or None)


# =========================================================================
# 12. _SyncIsolatedWorld
# =========================================================================


# =========================================================================
# 13. _AsyncIsolatedWorld
# =========================================================================


# =========================================================================
# 14. _is_input_element stealth
# =========================================================================

# =========================================================================
# 16. Shift symbol CDP stealth path (sync)
# =========================================================================

class TestShiftSymbolCDPSync:
    """Tests for _type_shift_symbol using CDP Input.dispatchKeyEvent."""

    def test_shift_symbol_codes_completeness(self):
        """Every SHIFT_SYMBOL must have an entry in _SHIFT_SYMBOL_CODES and _SHIFT_SYMBOL_KEYCODES."""
        from cloakbrowser.human.keyboard import SHIFT_SYMBOLS, _SHIFT_SYMBOL_CODES, _SHIFT_SYMBOL_KEYCODES

        for sym in SHIFT_SYMBOLS:
            assert sym in _SHIFT_SYMBOL_CODES, f"Missing code for '{sym}'"
            assert sym in _SHIFT_SYMBOL_KEYCODES, f"Missing keycode for '{sym}'"

    def test_cdp_path_sends_key_down_and_key_up(self):
        """When cdp_session is provided, _type_shift_symbol sends keyDown + keyUp via CDP."""
        from cloakbrowser.human.keyboard import _type_shift_symbol
        from cloakbrowser.human.keyboard import _SHIFT_SYMBOL_CODES, _SHIFT_SYMBOL_KEYCODES

        cfg = _cfg()
        page = MagicMock()
        raw = MagicMock()

        cdp_session = MagicMock()
        cdp_calls = []
        cdp_session.send = MagicMock(side_effect=lambda m, p: cdp_calls.append((m, p)))

        _type_shift_symbol(page, raw, "!", cfg, cdp_session=cdp_session)

        # Should have called raw.down("Shift") and raw.up("Shift")
        raw.down.assert_any_call("Shift")
        raw.up.assert_any_call("Shift")

        # Should have called CDP Input.dispatchKeyEvent (keyDown + keyUp)
        assert len(cdp_calls) == 2
        assert cdp_calls[0][0] == "Input.dispatchKeyEvent"
        assert cdp_calls[0][1]["type"] == "keyDown"
        assert cdp_calls[0][1]["key"] == "!"
        assert cdp_calls[0][1]["code"] == _SHIFT_SYMBOL_CODES["!"]
        assert cdp_calls[0][1]["windowsVirtualKeyCode"] == _SHIFT_SYMBOL_KEYCODES["!"]
        assert cdp_calls[0][1]["modifiers"] == 8  # Shift flag
        assert cdp_calls[0][1]["text"] == "!"

        assert cdp_calls[1][0] == "Input.dispatchKeyEvent"
        assert cdp_calls[1][1]["type"] == "keyUp"
        assert cdp_calls[1][1]["key"] == "!"

    def test_cdp_path_does_not_call_page_evaluate(self):
        """When cdp_session is provided, page.evaluate must NOT be called."""
        from cloakbrowser.human.keyboard import _type_shift_symbol

        cfg = _cfg()
        page = MagicMock()
        raw = MagicMock()
        cdp_session = MagicMock()

        _type_shift_symbol(page, raw, "@", cfg, cdp_session=cdp_session)

        page.evaluate.assert_not_called()

    def test_cdp_path_does_not_call_insert_text(self):
        """CDP path inserts characters via keyDown text field, not insertText."""
        from cloakbrowser.human.keyboard import _type_shift_symbol

        cfg = _cfg()
        page = MagicMock()
        raw = MagicMock()
        cdp_session = MagicMock()

        _type_shift_symbol(page, raw, "#", cfg, cdp_session=cdp_session)

        raw.insert_text.assert_not_called()

    def test_fallback_path_uses_page_evaluate(self):
        """When no cdp_session, falls back to page.evaluate (detectable path)."""
        from cloakbrowser.human.keyboard import _type_shift_symbol

        cfg = _cfg()
        page = MagicMock()
        raw = MagicMock()

        _type_shift_symbol(page, raw, "$", cfg, cdp_session=None)

        page.evaluate.assert_called_once()
        raw.insert_text.assert_called_once_with("$")
        raw.down.assert_any_call("Shift")
        raw.up.assert_any_call("Shift")

    def test_cdp_path_all_shift_symbols(self):
        """All 21 shift symbols should work via CDP path without error."""
        from cloakbrowser.human.keyboard import _type_shift_symbol, SHIFT_SYMBOLS

        cfg = _cfg()
        page = MagicMock()
        raw = MagicMock()
        cdp_session = MagicMock()

        for sym in SHIFT_SYMBOLS:
            page.reset_mock()
            raw.reset_mock()
            cdp_session.reset_mock()

            _type_shift_symbol(page, raw, sym, cfg, cdp_session=cdp_session)

            page.evaluate.assert_not_called()
            assert cdp_session.send.call_count == 2, f"Expected 2 CDP calls for '{sym}'"

    def test_cdp_keydown_has_text_field(self):
        """keyDown event must include 'text' and 'unmodifiedText' for char insertion."""
        from cloakbrowser.human.keyboard import _type_shift_symbol

        cfg = _cfg()
        page = MagicMock()
        raw = MagicMock()

        cdp_calls = []
        cdp_session = MagicMock()
        cdp_session.send = MagicMock(side_effect=lambda m, p: cdp_calls.append((m, p)))

        _type_shift_symbol(page, raw, "%", cfg, cdp_session=cdp_session)

        keydown = cdp_calls[0][1]
        assert keydown["text"] == "%"
        assert keydown["unmodifiedText"] == "%"

    def test_cdp_keyup_has_no_text_field(self):
        """keyUp event should NOT have 'text' or 'unmodifiedText' fields."""
        from cloakbrowser.human.keyboard import _type_shift_symbol

        cfg = _cfg()
        page = MagicMock()
        raw = MagicMock()

        cdp_calls = []
        cdp_session = MagicMock()
        cdp_session.send = MagicMock(side_effect=lambda m, p: cdp_calls.append((m, p)))

        _type_shift_symbol(page, raw, "^", cfg, cdp_session=cdp_session)

        keyup = cdp_calls[1][1]
        assert "text" not in keyup
        assert "unmodifiedText" not in keyup


# =========================================================================
# 16b. human_type end-to-end: shift symbols route via CDP
# =========================================================================

class TestHumanTypeShiftCDP:
    """Integration: human_type() routes shift symbols through CDP path."""

    def test_shift_symbol_in_text_uses_cdp(self):
        from cloakbrowser.human.keyboard import human_type

        cfg = _cfg(mistype_chance=0)
        page = MagicMock()
        raw = MagicMock()

        cdp_calls = []
        cdp_session = MagicMock()
        cdp_session.send = MagicMock(side_effect=lambda m, p: cdp_calls.append((m, p)))

        human_type(page, raw, "a!", cfg, cdp_session=cdp_session)

        # 'a' — normal char: raw.down('a'), raw.up('a')
        raw.down.assert_any_call("a")
        raw.up.assert_any_call("a")

        # '!' — shift symbol via CDP
        page.evaluate.assert_not_called()
        cdp_key_events = [(m, p) for m, p in cdp_calls if m == "Input.dispatchKeyEvent"]
        assert len(cdp_key_events) == 2  # keyDown + keyUp for '!'

    def test_text_without_shift_symbols_no_cdp(self):
        from cloakbrowser.human.keyboard import human_type

        cfg = _cfg(mistype_chance=0)
        page = MagicMock()
        raw = MagicMock()
        cdp_session = MagicMock()

        human_type(page, raw, "hello", cfg, cdp_session=cdp_session)

        cdp_session.send.assert_not_called()
        page.evaluate.assert_not_called()

    def test_multiple_shift_symbols_all_use_cdp(self):
        from cloakbrowser.human.keyboard import human_type

        cfg = _cfg(mistype_chance=0)
        page = MagicMock()
        raw = MagicMock()

        cdp_calls = []
        cdp_session = MagicMock()
        cdp_session.send = MagicMock(side_effect=lambda m, p: cdp_calls.append((m, p)))

        human_type(page, raw, "!@#", cfg, cdp_session=cdp_session)

        page.evaluate.assert_not_called()
        # 3 symbols × 2 events = 6 CDP calls
        assert len(cdp_calls) == 6

    def test_mixed_text_no_evaluate_leak(self):
        """'Hello World!' — the '!' must go via CDP, uppercase via Shift+raw, lowercase via raw."""
        from cloakbrowser.human.keyboard import human_type

        cfg = _cfg(mistype_chance=0)
        page = MagicMock()
        raw = MagicMock()
        cdp_session = MagicMock()

        human_type(page, raw, "Hello World!", cfg, cdp_session=cdp_session)

        page.evaluate.assert_not_called()


# =========================================================================
# 17. Shift symbol CDP stealth path (async)
# =========================================================================


# =========================================================================
# 18. Navigation invalidation
# =========================================================================


# =========================================================================
# 19. patch_page stealth infrastructure wiring
# =========================================================================


# =========================================================================
# 20. SHIFT_SYMBOL_CODES / SHIFT_SYMBOL_KEYCODES correctness
# =========================================================================

class TestShiftSymbolMaps:
    """Verify the code/keycode mappings are correct."""

    def test_all_codes_are_valid_key_codes(self):
        from cloakbrowser.human.keyboard import _SHIFT_SYMBOL_CODES

        valid_prefixes = ("Digit", "Minus", "Equal", "Bracket", "Backslash",
                          "Semicolon", "Quote", "Comma", "Period", "Slash", "Backquote")
        for sym, code in _SHIFT_SYMBOL_CODES.items():
            assert any(code.startswith(p) for p in valid_prefixes), \
                f"Invalid code '{code}' for symbol '{sym}'"

    def test_all_keycodes_are_positive_integers(self):
        from cloakbrowser.human.keyboard import _SHIFT_SYMBOL_KEYCODES

        for sym, keycode in _SHIFT_SYMBOL_KEYCODES.items():
            assert isinstance(keycode, int), f"Keycode for '{sym}' is not int"
            assert keycode > 0, f"Keycode for '{sym}' is not positive"

    def test_digit_symbols_have_correct_keycodes(self):
        """!@#$%^&*() should map to keycodes 49-57, 48 (digits 1-9, 0)."""
        from cloakbrowser.human.keyboard import _SHIFT_SYMBOL_KEYCODES

        digit_symbols = ['!', '@', '#', '$', '%', '^', '&', '*', '(', ')']
        expected_keycodes = [49, 50, 51, 52, 53, 54, 55, 56, 57, 48]

        for sym, expected in zip(digit_symbols, expected_keycodes):
            assert _SHIFT_SYMBOL_KEYCODES[sym] == expected, \
                f"Keycode for '{sym}': expected {expected}, got {_SHIFT_SYMBOL_KEYCODES[sym]}"

    def test_codes_and_keycodes_have_same_keys(self):
        from cloakbrowser.human.keyboard import _SHIFT_SYMBOL_CODES, _SHIFT_SYMBOL_KEYCODES
        assert set(_SHIFT_SYMBOL_CODES.keys()) == set(_SHIFT_SYMBOL_KEYCODES.keys())

    def test_shift_symbols_set_matches_codes_keys(self):
        from cloakbrowser.human.keyboard import SHIFT_SYMBOLS, _SHIFT_SYMBOL_CODES
        assert SHIFT_SYMBOLS == frozenset(_SHIFT_SYMBOL_CODES.keys())


# =========================================================================
# 21. CDP modifiers flag
# =========================================================================

class TestCDPModifiers:
    """Ensure the shift modifier flag is always 8 (correct CDP constant)."""

    def test_keydown_modifier_is_8(self):
        from cloakbrowser.human.keyboard import _type_shift_symbol

        cfg = _cfg()
        page = MagicMock()
        raw = MagicMock()

        cdp_calls = []
        cdp_session = MagicMock()
        cdp_session.send = MagicMock(side_effect=lambda m, p: cdp_calls.append((m, p)))

        _type_shift_symbol(page, raw, "!", cfg, cdp_session=cdp_session)

        for method, params in cdp_calls:
            assert params["modifiers"] == 8


# =========================================================================
# 22. Isolated world expression injection safety
# =========================================================================


# =========================================================================
# SLOW TESTS — require browser (skipped in CI unless pytest -m slow)
#
# Pattern: all browser tests use launch_async + @pytest.mark.asyncio to
# avoid Playwright Sync API / event loop conflicts with pytest-asyncio.
# =========================================================================


def _launch_kwargs(**extra):
    """Build launch() kwargs, omitting proxy when empty."""
    kw = {"humanize": True, "headless": False}
    kw.update(extra)
    if not kw.get("proxy"):
        kw.pop("proxy", None)
    return kw


@pytest.mark.slow
class TestStealthBrowserReal:
    """Real-browser tests that verify the stealth fixes from #110.

    All tests use launch_async + @pytest.mark.asyncio to be compatible
    with pytest-asyncio mode=AUTO.
    """

    @pytest.mark.asyncio
    async def test_stealth_world_attached_to_page(self):
        """Verify stealth infrastructure is wired up on real browser page."""
        from cloakbrowser import launch_async
        browser = await launch_async(**_launch_kwargs())
        page = await browser.new_page()

        assert hasattr(page, '_stealth_world'), "_stealth_world not attached"
        assert page._stealth_world is not None, "_stealth_world is None"
        assert hasattr(page, '_original'), "_original not attached"
        assert hasattr(page, '_human_cfg'), "_human_cfg not attached"

        await browser.close()

    @pytest.mark.asyncio
    async def test_no_evaluate_leak_on_click(self):
        """click() on input/button must NOT trigger page.evaluate (querySelector leak).

        We inject a detection script that catches querySelector calls from
        evaluate context (Error.stack ':302:' pattern). If humanize is using
        the stealth isolated world, these should NOT fire.
        """
        import asyncio
        from cloakbrowser import launch_async
        browser = await launch_async(**_launch_kwargs())
        page = await browser.new_page()

        await page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        await asyncio.sleep(1)

        # Inject detection hook directly
        await page.evaluate("""
            () => {
                window.__evaluateDetections = [];
                const origQS = document.querySelector.bind(document);
                document.querySelector = function(sel) {
                    try { throw new Error(); } catch (e) {
                        if (e.stack && e.stack.includes(':302:')) {
                            window.__evaluateDetections.push(sel);
                        }
                    }
                    return origQS(sel);
                };
                return true;
            }
        """)

        # Click on the search input — this triggers isInputElement check
        await page.locator('#searchInput').click()
        await asyncio.sleep(0.5)

        # Check if any querySelector calls came from evaluate context
        leaks = await page.evaluate('() => window.__evaluateDetections || []')
        assert len(leaks) == 0, f"Evaluate leak detected: {leaks}"

        await browser.close()

    @pytest.mark.asyncio
    async def test_shift_symbols_produce_trusted_events(self):
        """Shift symbols (!@#) must produce isTrusted=true keyboard events.

        Before #110 fix, these used page.evaluate to dispatch synthetic
        KeyboardEvent with isTrusted=false.
        """
        import asyncio
        from cloakbrowser import launch_async
        browser = await launch_async(**_launch_kwargs())
        page = await browser.new_page()

        await page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        await asyncio.sleep(1)

        # Inject isTrusted tracker on the search input
        await page.evaluate("""
            () => {
                window.__untrustedKeys = [];
                window.__trustedKeys = [];
                const input = document.querySelector('#searchInput');
                if (input) {
                    input.addEventListener('keydown', (e) => {
                        if (!e.isTrusted) {
                            window.__untrustedKeys.push(e.key);
                        } else {
                            window.__trustedKeys.push(e.key);
                        }
                    }, true);
                }
            }
        """)

        # Click into search, then type text with shift symbols
        await page.locator('#searchInput').click()
        await asyncio.sleep(0.3)
        await page.keyboard.type('test!')
        await asyncio.sleep(0.5)

        untrusted = await page.evaluate('() => window.__untrustedKeys || []')
        trusted = await page.evaluate('() => window.__trustedKeys || []')

        # '!' should appear in trusted, NOT in untrusted
        assert '!' not in untrusted, f"Untrusted shift symbol detected: {untrusted}"
        assert '!' in trusted, f"'!' not in trusted keys: {trusted}"

        await browser.close()

    @pytest.mark.asyncio
    async def test_stealth_world_survives_navigation(self):
        """After page.goto(), the isolated world must be invalidated and
        re-created transparently — subsequent click/type should still work."""
        import asyncio
        from cloakbrowser import launch_async
        browser = await launch_async(**_launch_kwargs())
        page = await browser.new_page()

        assert hasattr(page, '_stealth_world')

        # First navigation
        await page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        await asyncio.sleep(1)
        await page.locator('#searchInput').click()
        await asyncio.sleep(0.3)

        # Second navigation — triggers invalidate()
        await page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        await asyncio.sleep(1)

        # This should still work (isolated world auto-recreated)
        await page.locator('#searchInput').click()
        await asyncio.sleep(0.3)
        await page.locator('#searchInput').type('after navigation')
        await asyncio.sleep(0.5)

        val = await page.locator('#searchInput').input_value()
        assert 'after navigation' in val

        await browser.close()

    @pytest.mark.asyncio
    async def test_no_evaluate_leak_on_type_shift_symbols(self):
        """Typing '!@#$%' must NOT produce any page.evaluate calls
        (Error.stack ':302:' detection)."""
        import asyncio
        from cloakbrowser import launch_async
        browser = await launch_async(**_launch_kwargs())
        page = await browser.new_page()

        await page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        await asyncio.sleep(1)

        # Inject detection
        await page.evaluate("""
            () => {
                window.__evalLeaks = [];
                const origQS = document.querySelector.bind(document);
                document.querySelector = function(sel) {
                    try { throw new Error(); } catch (e) {
                        if (e.stack && e.stack.includes(':302:')) {
                            window.__evalLeaks.push({sel, stack: e.stack.substring(0, 200)});
                        }
                    }
                    return origQS(sel);
                };
            }
        """)

        await page.locator('#searchInput').click()
        await asyncio.sleep(0.3)
        await page.keyboard.type('Hello!@#')
        await asyncio.sleep(0.5)

        leaks = await page.evaluate('() => window.__evalLeaks || []')
        assert len(leaks) == 0, (
            f"Evaluate stack leak during shift symbol typing: {leaks}"
        )

        await browser.close()

    @pytest.mark.asyncio
    async def test_form_fill_no_untrusted_events(self):
        """Full form fill (email + password with shift symbols) — all events
        must be isTrusted=true, no evaluate leaks."""
        import asyncio
        from cloakbrowser import launch_async
        browser = await launch_async(**_launch_kwargs(headless=False, geoip=True))
        page = await browser.new_page()

        await page.goto(
            'https://deviceandbrowserinfo.com/are_you_a_bot_interactions',
            wait_until='domcontentloaded',
        )
        await asyncio.sleep(3)

        # Inject both detection hooks
        await page.evaluate("""
            () => {
                window.__evalLeaks = [];
                window.__untrustedKeys = [];

                // Track querySelector from evaluate context
                const origQS = document.querySelector.bind(document);
                document.querySelector = function(sel) {
                    try { throw new Error(); } catch (e) {
                        if (e.stack && e.stack.includes(':302:')) {
                            window.__evalLeaks.push(sel);
                        }
                    }
                    return origQS(sel);
                };

                // Track untrusted keyboard events
                document.addEventListener('keydown', (e) => {
                    if (!e.isTrusted) {
                        window.__untrustedKeys.push(e.key);
                    }
                }, true);
            }
        """)

        # Fill the form with shift symbols in the password
        await page.locator('#email').click()
        await asyncio.sleep(0.3)
        await page.locator('#email').fill('test@example.com')
        await asyncio.sleep(0.5)
        await page.locator('#password').click()
        await asyncio.sleep(0.3)
        await page.locator('#password').fill('SecurePass!@#123')
        await asyncio.sleep(0.5)

        eval_leaks = await page.evaluate('() => window.__evalLeaks || []')
        untrusted = await page.evaluate('() => window.__untrustedKeys || []')

        assert len(eval_leaks) == 0, f"Evaluate leaks: {eval_leaks}"
        assert len(untrusted) == 0, f"Untrusted key events: {untrusted}"

        # Strict mode (like Playwright): this page has two submit buttons.
        await page.get_by_role('button', name='Login').click()
        await asyncio.sleep(5)

        body = await page.locator('body').text_content()
        assert '"superHumanSpeed": true' not in body
        assert '"suspiciousClientSideBehavior": true' not in body

        await browser.close()

    @pytest.mark.asyncio
    async def test_async_no_evaluate_leak(self):
        """launch_async variant — click + shift symbols, zero evaluate leaks."""
        import asyncio
        from cloakbrowser import launch_async
        browser = await launch_async(**_launch_kwargs())
        page = await browser.new_page()

        assert hasattr(page, '_stealth_world')
        assert page._stealth_world is not None

        await page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        await asyncio.sleep(1)

        # Inject detection
        await page.evaluate("""
            () => {
                window.__evalLeaks = [];
                const origQS = document.querySelector.bind(document);
                document.querySelector = function(sel) {
                    try { throw new Error(); } catch (e) {
                        if (e.stack && e.stack.includes(':302:')) {
                            window.__evalLeaks.push(sel);
                        }
                    }
                    return origQS(sel);
                };
            }
        """)

        await page.locator('#searchInput').click()
        await asyncio.sleep(0.3)
        await page.keyboard.type('async!')
        await asyncio.sleep(0.5)

        leaks = await page.evaluate('() => window.__evalLeaks || []')
        assert len(leaks) == 0, f"Async evaluate leak: {leaks}"

        await browser.close()

    @pytest.mark.asyncio
    async def test_async_shift_symbols_trusted(self):
        """launch_async variant — shift symbols produce isTrusted=true."""
        import asyncio
        from cloakbrowser import launch_async
        browser = await launch_async(**_launch_kwargs())
        page = await browser.new_page()

        await page.goto('https://www.wikipedia.org', wait_until='domcontentloaded')
        await asyncio.sleep(1)

        await page.evaluate("""
            () => {
                window.__untrusted = [];
                const input = document.querySelector('#searchInput');
                if (input) {
                    input.addEventListener('keydown', (e) => {
                        if (!e.isTrusted) window.__untrusted.push(e.key);
                    }, true);
                }
            }
        """)

        await page.locator('#searchInput').click()
        await asyncio.sleep(0.3)
        await page.keyboard.type('Hello!@#')
        await asyncio.sleep(0.5)

        untrusted = await page.evaluate('() => window.__untrusted || []')
        assert len(untrusted) == 0, f"Async untrusted keys: {untrusted}"

        await browser.close()


# =========================================================================
# Direct runner
# =========================================================================

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--tb=short", "-x"]))
