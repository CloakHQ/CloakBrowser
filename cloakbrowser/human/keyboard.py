"""cloakbrowser-human — Human-like keyboard input."""

from __future__ import annotations

import random
from typing import Any, Protocol

from .config import HumanConfig, rand, rand_range, sleep_ms


class RawKeyboard(Protocol):
    def down(self, key: str) -> None: ...
    def up(self, key: str) -> None: ...
    def type(self, text: str) -> None: ...
    def insert_text(self, text: str) -> None: ...


SHIFT_SYMBOLS = frozenset('@#!$%^&*()_+{}|:"<>?~')


def human_type(page: Any, raw: RawKeyboard, text: str, cfg: HumanConfig) -> None:
    for i, ch in enumerate(text):
        if ch.isupper() and ch.isalpha():
            _type_shifted_char(page, raw, ch, cfg)
        elif ch in SHIFT_SYMBOLS:
            _type_shift_symbol(page, raw, ch, cfg)
        else:
            _type_normal_char(raw, ch, cfg)

        if i < len(text) - 1:
            _inter_char_delay(cfg)


def _type_normal_char(raw: RawKeyboard, ch: str, cfg: HumanConfig) -> None:
    raw.down(ch)
    sleep_ms(rand_range(cfg.key_hold))
    raw.up(ch)


def _type_shifted_char(page: Any, raw: RawKeyboard, ch: str, cfg: HumanConfig) -> None:
    raw.down("Shift")
    sleep_ms(rand_range(cfg.shift_down_delay))
    raw.down(ch)
    sleep_ms(rand_range(cfg.key_hold))
    raw.up(ch)
    sleep_ms(rand_range(cfg.shift_up_delay))
    raw.up("Shift")


def _type_shift_symbol(page: Any, raw: RawKeyboard, ch: str, cfg: HumanConfig) -> None:
    raw.down("Shift")
    sleep_ms(rand_range(cfg.shift_down_delay))
    raw.insert_text(ch)
    page.evaluate(
        """(key) => {
            const el = document.activeElement;
            if (el) {
                el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
                el.dispatchEvent(new KeyboardEvent('keyup', { key, bubbles: true }));
            }
        }""",
        ch,
    )
    sleep_ms(rand_range(cfg.shift_up_delay))
    raw.up("Shift")


def _inter_char_delay(cfg: HumanConfig) -> None:
    if random.random() < cfg.typing_pause_chance:
        sleep_ms(rand_range(cfg.typing_pause_range))
    else:
        delay = cfg.typing_delay + (random.random() - 0.5) * 2 * cfg.typing_delay_spread
        sleep_ms(max(10, delay))
