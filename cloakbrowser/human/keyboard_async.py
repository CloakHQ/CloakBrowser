"""cloakbrowser-human — Async human-like keyboard input.

Mirrors keyboard.py but uses ``await`` for all Playwright calls and
``async_sleep_ms`` instead of ``sleep_ms``.

Stealth-aware: when a CDP session is provided, shift symbols are typed
via CDP Input.dispatchKeyEvent (isTrusted=true, no evaluate stack trace).
"""

from __future__ import annotations

import random
from typing import Any, Optional, Protocol

from .config import HumanConfig, rand, rand_range, async_sleep_ms
from .keyboard import SHIFT_SYMBOLS, NEARBY_KEYS, _get_nearby_key
from .keyboard import _SHIFT_SYMBOL_CODES, _SHIFT_SYMBOL_KEYCODES


class AsyncRawKeyboard(Protocol):
    async def down(self, key: str) -> None: ...
    async def up(self, key: str) -> None: ...
    async def type(self, text: str) -> None: ...
    async def insert_text(self, text: str) -> None: ...


async def async_human_type(
    page: Any, raw: AsyncRawKeyboard, text: str, cfg: HumanConfig,
    cdp_session: Any = None,
) -> None:
    """Type text with human-like per-character timing (async).

    Args:
        cdp_session: If provided, shift symbols use CDP Input.dispatchKeyEvent
            producing isTrusted=true events with no evaluate stack trace.
            If None, falls back to page.evaluate (detectable).
    """
    for i, ch in enumerate(text):
        # Non-ASCII characters (Cyrillic, CJK, emoji) — use insertText
        if not ch.isascii():
            await async_sleep_ms(rand_range(cfg.key_hold))
            await raw.insert_text(ch)
            if i < len(text) - 1:
                await _inter_char_delay(cfg)
            continue

        # Mistype chance — only for ASCII alphanumeric
        if random.random() < cfg.mistype_chance and ch.isalnum():
            wrong = _get_nearby_key(ch)
            await _type_normal_char(raw, wrong, cfg)
            await async_sleep_ms(rand_range(cfg.mistype_delay_notice))
            await raw.down("Backspace")
            await async_sleep_ms(rand_range(cfg.key_hold))
            await raw.up("Backspace")
            await async_sleep_ms(rand_range(cfg.mistype_delay_correct))

        if ch.isupper() and ch.isalpha():
            await _type_shifted_char(page, raw, ch, cfg)
        elif ch in SHIFT_SYMBOLS:
            await _type_shift_symbol(page, raw, ch, cfg, cdp_session)
        else:
            await _type_normal_char(raw, ch, cfg)

        if i < len(text) - 1:
            await _inter_char_delay(cfg)


async def _type_normal_char(raw: AsyncRawKeyboard, ch: str, cfg: HumanConfig) -> None:
    await raw.down(ch)
    await async_sleep_ms(rand_range(cfg.key_hold))
    await raw.up(ch)


async def _type_shifted_char(page: Any, raw: AsyncRawKeyboard, ch: str, cfg: HumanConfig) -> None:
    await raw.down("Shift")
    await async_sleep_ms(rand_range(cfg.shift_down_delay))
    await raw.down(ch)
    await async_sleep_ms(rand_range(cfg.key_hold))
    await raw.up(ch)
    await async_sleep_ms(rand_range(cfg.shift_up_delay))
    await raw.up("Shift")


async def _type_shift_symbol(
    page: Any, raw: AsyncRawKeyboard, ch: str, cfg: HumanConfig,
    cdp_session: Any = None,
) -> None:
    """Type a shift symbol character (async).

    Stealth path (cdp_session provided):
        Uses CDP Input.dispatchKeyEvent → isTrusted=true, clean stack.

    Fallback path (no cdp_session):
        Uses raw.insertText + page.evaluate to dispatch synthetic KeyboardEvent.
        Detectable via isTrusted=false and evaluate stack frame.
    """
    if cdp_session is not None:
        # --- Stealth path: CDP Input.dispatchKeyEvent ---
        code = _SHIFT_SYMBOL_CODES.get(ch, '')
        key_code = _SHIFT_SYMBOL_KEYCODES.get(ch, 0)

        await raw.down("Shift")
        await async_sleep_ms(rand_range(cfg.shift_down_delay))

        await cdp_session.send("Input.dispatchKeyEvent", {
            "type": "keyDown",
            "modifiers": 8,  # Shift modifier flag
            "key": ch,
            "code": code,
            "windowsVirtualKeyCode": key_code,
            "text": ch,
            "unmodifiedText": ch,
        })
        await async_sleep_ms(rand_range(cfg.key_hold))

        await cdp_session.send("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "modifiers": 8,
            "key": ch,
            "code": code,
            "windowsVirtualKeyCode": key_code,
        })

        await async_sleep_ms(rand_range(cfg.shift_up_delay))
        await raw.up("Shift")
    else:
        # --- Fallback path: page.evaluate (detectable) ---
        await raw.down("Shift")
        await async_sleep_ms(rand_range(cfg.shift_down_delay))
        await raw.insert_text(ch)
        await page.evaluate(
            """(key) => {
                const el = document.activeElement;
                if (el) {
                    el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keyup', { key, bubbles: true }));
                }
            }""",
            ch,
        )
        await async_sleep_ms(rand_range(cfg.shift_up_delay))
        await raw.up("Shift")


async def _inter_char_delay(cfg: HumanConfig) -> None:
    if random.random() < cfg.typing_pause_chance:
        await async_sleep_ms(rand_range(cfg.typing_pause_range))
    else:
        delay = cfg.typing_delay + (random.random() - 0.5) * 2 * cfg.typing_delay_spread
        await async_sleep_ms(max(10, delay))
