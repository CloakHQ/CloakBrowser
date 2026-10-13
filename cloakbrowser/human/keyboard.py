"""cloakbrowser-human — Human-like keyboard input.

Stealth-aware: when a CDP session is provided, shift symbols are typed
via CDP Input.dispatchKeyEvent (isTrusted=true, no evaluate stack trace).
Falls back to page.evaluate when no CDP session is available.
"""

from __future__ import annotations

import math
import random
from typing import Any, Optional, Protocol

from .config import HumanConfig, rand, rand_log, rand_lognormal, rand_range, sleep_ms


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
    # Digits stay digits: a letter typo is rejected by <input type=number>,
    # so the correcting Backspace would delete the previous real digit (#573).
    '1': '2', '2': '13', '3': '24', '4': '35', '5': '46',
    '6': '57', '7': '68', '8': '79', '9': '80', '0': '9',
}

# CDP key code for each shift symbol's physical key.
_SHIFT_SYMBOL_CODES: dict[str, str] = {
    '!': 'Digit1', '@': 'Digit2', '#': 'Digit3', '$': 'Digit4',
    '%': 'Digit5', '^': 'Digit6', '&': 'Digit7', '*': 'Digit8',
    '(': 'Digit9', ')': 'Digit0', '_': 'Minus', '+': 'Equal',
    '{': 'BracketLeft', '}': 'BracketRight', '|': 'Backslash',
    ':': 'Semicolon', '"': 'Quote', '<': 'Comma', '>': 'Period',
    '?': 'Slash', '~': 'Backquote',
}

# Physical key of each unshifted digit / punctuation character, so a shift
# symbol and its base character ("1" and "!") count as the same key.
_BASE_KEY_CODES: dict[str, str] = {
    '1': 'Digit1', '2': 'Digit2', '3': 'Digit3', '4': 'Digit4', '5': 'Digit5',
    '6': 'Digit6', '7': 'Digit7', '8': 'Digit8', '9': 'Digit9', '0': 'Digit0',
    '-': 'Minus', '=': 'Equal', '[': 'BracketLeft', ']': 'BracketRight',
    '\\': 'Backslash', ';': 'Semicolon', "'": 'Quote', ',': 'Comma',
    '.': 'Period', '/': 'Slash', '`': 'Backquote',
}


def physical_key(ch: str) -> str:
    """The physical key that types ``ch``: "x" and "X" are one key, so are
    "1" and "!". Used so a key never goes down while it is still held."""
    return _SHIFT_SYMBOL_CODES.get(ch) or _BASE_KEY_CODES.get(ch) or ch.lower()


# Windows virtual key codes for Input.dispatchKeyEvent.
_SHIFT_SYMBOL_KEYCODES: dict[str, int] = {
    '!': 49, '@': 50, '#': 51, '$': 52, '%': 53,
    '^': 54, '&': 55, '*': 56, '(': 57, ')': 48,
    '_': 189, '+': 187, '{': 219, '}': 221, '|': 220,
    ':': 186, '"': 222, '<': 188, '>': 190, '?': 191,
    '~': 192,
}


# ---------------------------------------------------------------------------
# Key timing (shared by the humanize engine)
# ---------------------------------------------------------------------------
#
# Numbers come from the 136M Keystrokes data (Dhakal et al., CHI 2018):
# letters typed with the other hand follow ~20% faster than letters of the
# same hand, a repeated letter (same finger) is slower, and the first letter
# of a word (after a space) is the slowest. People commonly press the next
# key before letting go of the previous one (rollover).

_LEFT_HAND = frozenset("qwertasdfgzxcvb`12345~!@#$%")


def _hand(ch: str) -> Optional[str]:
    c = ch.lower()
    if not c or not c.isascii() or c.isspace():
        return None
    return "L" if c in _LEFT_HAND else "R"


def gap_factor(prev: str, ch: str) -> float:
    """How much slower / faster than average the press of ``ch`` follows
    ``prev`` (the previous typed character)."""
    if not prev:
        return 1.0
    if prev == " ":
        return 1.3
    if ch == " ":
        return 0.9
    if prev.lower() == ch.lower():
        return 1.05
    hp, hc = _hand(prev), _hand(ch)
    if hp and hc:
        return 0.85 if hp != hc else 1.1
    return 1.0


def key_gap(cfg: HumanConfig, prev: str, ch: str) -> float:
    """Milliseconds from the press of ``prev`` to the press of ``ch``
    (log-normal around ``typing_delay``, plus occasional thinking pauses
    before words)."""
    median = max(1.0, cfg.typing_delay * gap_factor(prev, ch))
    spread = max(0.0, cfg.typing_delay_spread)
    sigma = math.log1p(spread / cfg.typing_delay) if cfg.typing_delay > 0 else 0.0
    gap = rand_lognormal(median, sigma)
    word_start = prev == " " or prev == ""
    chance = cfg.typing_pause_chance * (1.0 if word_start else 0.1)
    if chance > 0 and random.random() < chance:
        gap += rand_range(cfg.typing_pause_range)
    return max(15.0, gap)


def key_hold(cfg: HumanConfig) -> float:
    """How long one key stays down (ms)."""
    return max(1.0, rand_log(cfg.key_hold))


def _get_nearby_key(ch: str) -> str:
    """Return a random adjacent key for the given character."""
    lower = ch.lower()
    if lower in NEARBY_KEYS:
        neighbors = NEARBY_KEYS[lower]
        wrong = random.choice(neighbors)
        return wrong.upper() if ch.isupper() else wrong
    return ch


def human_type(
    page: Any, raw: RawKeyboard, text: str, cfg: HumanConfig,
    cdp_session: Any = None,
) -> None:
    """Type text with human-like per-character timing.

    Args:
        cdp_session: If provided, shift symbols use CDP Input.dispatchKeyEvent
            producing isTrusted=true events with no evaluate stack trace.
            If None, falls back to page.evaluate (detectable).
    """
    for i, ch in enumerate(text):
        # Non-ASCII characters (Cyrillic, CJK, emoji) — use insertText
        if not ch.isascii():
            sleep_ms(key_hold(cfg))
            raw.insert_text(ch)
            if i < len(text) - 1:
                _inter_char_delay(cfg)
            continue

        # Mistype chance — only for ASCII alphanumeric
        if random.random() < cfg.mistype_chance and ch.isalnum():
            wrong = _get_nearby_key(ch)
            _type_normal_char(raw, wrong, cfg)
            sleep_ms(rand_range(cfg.mistype_delay_notice))
            raw.down("Backspace")
            sleep_ms(key_hold(cfg))
            raw.up("Backspace")
            sleep_ms(rand_range(cfg.mistype_delay_correct))

        if ch.isupper() and ch.isalpha():
            _type_shifted_char(page, raw, ch, cfg)
        elif ch in SHIFT_SYMBOLS:
            _type_shift_symbol(page, raw, ch, cfg, cdp_session)
        else:
            _type_normal_char(raw, ch, cfg)

        if i < len(text) - 1:
            _inter_char_delay(cfg)


def _type_normal_char(raw: RawKeyboard, ch: str, cfg: HumanConfig) -> None:
    raw.down(ch)
    sleep_ms(key_hold(cfg))
    raw.up(ch)


def _type_shifted_char(page: Any, raw: RawKeyboard, ch: str, cfg: HumanConfig) -> None:
    raw.down("Shift")
    sleep_ms(rand_log(cfg.shift_down_delay))
    raw.down(ch)
    sleep_ms(key_hold(cfg))
    raw.up(ch)
    sleep_ms(max(0.0, rand_range(cfg.shift_up_delay)))
    raw.up("Shift")


def _type_shift_symbol(
    page: Any, raw: RawKeyboard, ch: str, cfg: HumanConfig,
    cdp_session: Any = None,
) -> None:
    """Type a shift symbol character.

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

        raw.down("Shift")
        sleep_ms(rand_log(cfg.shift_down_delay))

        cdp_session.send("Input.dispatchKeyEvent", {
            "type": "keyDown",
            "modifiers": 8,  # Shift modifier flag
            "key": ch,
            "code": code,
            "windowsVirtualKeyCode": key_code,
            "text": ch,
            "unmodifiedText": ch,
        })
        sleep_ms(key_hold(cfg))

        cdp_session.send("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "modifiers": 8,
            "key": ch,
            "code": code,
            "windowsVirtualKeyCode": key_code,
        })

        sleep_ms(max(0.0, rand_range(cfg.shift_up_delay)))
        raw.up("Shift")
    else:
        # --- Fallback path: page.evaluate (detectable) ---
        raw.down("Shift")
        sleep_ms(rand_log(cfg.shift_down_delay))
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
        sleep_ms(max(0.0, rand_range(cfg.shift_up_delay)))
        raw.up("Shift")


def _inter_char_delay(cfg: HumanConfig) -> None:
    sleep_ms(max(10.0, key_gap(cfg, "a", "b") - rand_log(cfg.key_hold)))
