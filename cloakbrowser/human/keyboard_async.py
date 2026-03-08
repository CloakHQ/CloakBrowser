"""cloakbrowser-human — Async human-like keyboard input.

Mirrors keyboard.py but uses ``await`` for all Playwright calls and
``async_sleep_ms`` instead of ``sleep_ms``.
"""

from __future__ import annotations

import random
from typing import Any, Protocol

from .config import HumanConfig, rand, rand_range, async_sleep_ms
from .keyboard import SHIFT_SYMBOLS, NEARBY_KEYS, _get_nearby_key


class AsyncRawKeyboard(Protocol):
    async def down(self, key: str) -> None: ...
    async def up(self, key: str) -> None: ...
    async def type(self, text: str) -> None: ...
    async def insert_text(self, text: str) -> None: ...


async def async_human_type(page: Any, raw: AsyncRawKeyboard, text: str, cfg: HumanConfig) -> None:
    for i, ch in enumerate(text):
        # Mistype chance — press wrong key, notice, backspace, then correct
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
            await _type_shift_symbol(page, raw, ch, cfg)
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


async def _type_shift_symbol(page: Any, raw: AsyncRawKeyboard, ch: str, cfg: HumanConfig) -> None:
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
