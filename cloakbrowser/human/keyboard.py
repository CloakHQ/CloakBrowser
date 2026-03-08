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

NEARBY_KEYS = {
    'a': 'sqwz', 'b': 'vghn', 'c': 'xdfv', 'd': 'sfecx', 'e': 'wrsdf',
    'f': 'dgrtcv', 'g': 'fhtyb', 'h': 'gjybn', 'i': 'ujko', 'j': 'hkunm',
    'k': 'jloi', 'l': 'kop', 'm': 'njk', 'n': 'bhjm', 'o': 'iklp',
    'p': 'ol', 'q': 'wa', 'r': 'edft', 's': 'awedxz', 't': 'rfgy',
    'u': 'yhji', 'v': 'cfgb', 'w': 'qase', 'x': 'zsdc', 'y': 'tghu',
    'z': 'asx',
    '1': '2q', '2': '13qw', '3': '24we', '4': '35er', '5': '46rt',
    '6': '57ty', '7': '68yu', '8': '79ui', '9': '80io', '0': '9p',
}


def _get_nearby_key(ch: str) -> str:
    """Return a random adjacent key for the given character."""
    lower = ch.lower()
    if lower in NEARBY_KEYS:
        neighbors = NEARBY_KEYS[lower]
        wrong = random.choice(neighbors)
        return wrong.upper() if ch.isupper() else wrong
    return ch


def human_type(page: Any, raw: RawKeyboard, text: str, cfg: HumanConfig) -> None:
    for i, ch in enumerate(text):
        # Mistype chance — press wrong key, notice, backspace, then correct
        if random.random() < cfg.mistype_chance and ch.isalnum():
            wrong = _get_nearby_key(ch)
            _type_normal_char(raw, wrong, cfg)
            sleep_ms(rand_range(cfg.mistype_delay_notice))
            raw.down("Backspace")
            sleep_ms(rand_range(cfg.key_hold))
            raw.up("Backspace")
            sleep_ms(rand_range(cfg.mistype_delay_correct))

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
