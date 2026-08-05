"""cloakbrowser-human — Human-like keyboard input.

Stealth-aware: when a CDP session is provided, shift symbols are typed
via CDP Input.dispatchKeyEvent (isTrusted=true, no evaluate stack trace).
Falls back to page.evaluate when no CDP session is available.
"""

from __future__ import annotations

import logging
import random
from typing import Any, Optional, Protocol

from .config import HumanConfig, rand, rand_range, sleep_ms

_log = logging.getLogger("cloakbrowser.human")
_pypinyin_warned = False

# Physical key `code` for each latin letter (used by the CJK IME keydown layer).
_LETTER_CODES = {c: f"Key{c.upper()}" for c in "abcdefghijklmnopqrstuvwxyz"}


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

# CDP key code for each shift symbol's physical key.
_SHIFT_SYMBOL_CODES: dict[str, str] = {
    '!': 'Digit1', '@': 'Digit2', '#': 'Digit3', '$': 'Digit4',
    '%': 'Digit5', '^': 'Digit6', '&': 'Digit7', '*': 'Digit8',
    '(': 'Digit9', ')': 'Digit0', '_': 'Minus', '+': 'Equal',
    '{': 'BracketLeft', '}': 'BracketRight', '|': 'Backslash',
    ':': 'Semicolon', '"': 'Quote', '<': 'Comma', '>': 'Period',
    '?': 'Slash', '~': 'Backquote',
}

# Windows virtual key codes for Input.dispatchKeyEvent.
_SHIFT_SYMBOL_KEYCODES: dict[str, int] = {
    '!': 49, '@': 50, '#': 51, '$': 52, '%': 53,
    '^': 54, '&': 55, '*': 56, '(': 57, ')': 48,
    '_': 189, '+': 187, '{': 219, '}': 221, '|': 220,
    ':': 186, '"': 222, '<': 188, '>': 190, '?': 191,
    '~': 192,
}


def _get_nearby_key(ch: str) -> str:
    """Return a random adjacent key for the given character."""
    lower = ch.lower()
    if lower in NEARBY_KEYS:
        neighbors = NEARBY_KEYS[lower]
        wrong = random.choice(neighbors)
        return wrong.upper() if ch.isupper() else wrong
    return ch


def _is_chinese_ideograph(ch: str) -> bool:
    """True for Han ideographs (CJK Unified + Ext A + Compat).

    This block is shared: Japanese kanji and Korean hanja are indistinguishable
    from Chinese hanzi by code point, so with ime_language='zh' they too get
    Mandarin pinyin. The precise guarantee is only that kana and Hangul syllables
    are excluded — not "Chinese-only".
    """
    o = ord(ch)
    return (0x4E00 <= o <= 0x9FFF) or (0x3400 <= o <= 0x4DBF) or (0xF900 <= o <= 0xFAFF)


def _pinyin_map(text: str, ime_language: Optional[str]) -> dict[int, str]:
    """Map each Chinese-ideograph char index → its lowercase pinyin syllable.

    Converts per contiguous Han run (not per isolated char) so pypinyin's
    word-context disambiguation gives correct polyphonic readings
    (重庆 → chong/qing, not zhong/qing). Returns {} when disabled, when the
    text has no Han chars, or when pypinyin is not installed (warns once).
    """
    global _pypinyin_warned
    if ime_language != "zh" or not any(_is_chinese_ideograph(c) for c in text):
        return {}
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        if not _pypinyin_warned:
            _pypinyin_warned = True
            _log.warning(
                "Chinese IME humanization (ime_language='zh') requires pypinyin; "
                "falling back to basic insertion. Install with: "
                "pip install 'cloakbrowser[cjk]'"
            )
        return {}

    result: dict[int, str] = {}
    i, n = 0, len(text)
    while i < n:
        if not _is_chinese_ideograph(text[i]):
            i += 1
            continue
        j = i
        while j < n and _is_chinese_ideograph(text[j]):
            j += 1
        # Pure-Han run → lazy_pinyin returns exactly one syllable per char.
        for k, syl in enumerate(lazy_pinyin(text[i:j])):
            syl = syl.lower()
            if syl.isascii() and syl.isalpha():
                result[i + k] = syl
        i = j
    return result


def _type_cjk_ime(ch: str, pinyin: str, cfg: HumanConfig, cdp_session: Any) -> None:
    """Reproduce a real pinyin-IME flow for one Han char.

    Per pinyin letter: a keydown/keyup carrying the IME-processing code
    (windowsVirtualKeyCode 229 / key "Process") plus an ``Input.imeSetComposition``
    that grows the composition string (fires compositionstart/update). Then commit
    the composed hanzi via ``Input.insertText`` (fires compositionend + input).

    NOTE: exact keyCode/key on keyUp and any commit-key (Space) modeling are to be
    tuned against a real-Chrome IME capture (docs Phase-0 spec); the pinyin-letter
    keydown stream and composition/commit events are the load-bearing signals.
    """
    for i, letter in enumerate(pinyin):
        code = _LETTER_CODES.get(letter, "")
        cdp_session.send("Input.dispatchKeyEvent", {
            "type": "keyDown",
            "windowsVirtualKeyCode": 229,  # VK_PROCESSKEY — IME is processing
            "key": "Process",
            "code": code,
        })
        cdp_session.send("Input.imeSetComposition", {
            "text": pinyin[:i + 1],
            "selectionStart": i + 1,
            "selectionEnd": i + 1,
        })
        sleep_ms(rand_range(cfg.key_hold))
        cdp_session.send("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "windowsVirtualKeyCode": 229,
            "key": "Process",
            "code": code,
        })
        if i < len(pinyin) - 1:
            sleep_ms(rand_range(cfg.key_hold))
    # Commit the top candidate → compositionend + input.
    cdp_session.send("Input.insertText", {"text": ch})


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
    # Chinese ideographs get a real pinyin-IME flow when enabled (ime_language='zh'
    # + a CDP session + pypinyin available); everything else keeps insertText.
    pinyin_map = (
        _pinyin_map(text, cfg.ime_language) if cdp_session is not None else {}
    )

    for i, ch in enumerate(text):
        # Non-ASCII characters (Cyrillic, CJK, emoji) — use insertText
        if not ch.isascii():
            sleep_ms(rand_range(cfg.key_hold))
            if i in pinyin_map:
                try:
                    _type_cjk_ime(ch, pinyin_map[i], cfg, cdp_session)
                except Exception:
                    # A CDP hiccup on one char (e.g. focus lost mid-type) must not
                    # abort the whole type() — fall back to plain insertion.
                    _log.debug("CJK IME failed for %r; using insertText", ch, exc_info=True)
                    raw.insert_text(ch)
            else:
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
            sleep_ms(rand_range(cfg.key_hold))
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
        sleep_ms(rand_range(cfg.shift_down_delay))

        cdp_session.send("Input.dispatchKeyEvent", {
            "type": "keyDown",
            "modifiers": 8,  # Shift modifier flag
            "key": ch,
            "code": code,
            "windowsVirtualKeyCode": key_code,
            "text": ch,
            "unmodifiedText": ch,
        })
        sleep_ms(rand_range(cfg.key_hold))

        cdp_session.send("Input.dispatchKeyEvent", {
            "type": "keyUp",
            "modifiers": 8,
            "key": ch,
            "code": code,
            "windowsVirtualKeyCode": key_code,
        })

        sleep_ms(rand_range(cfg.shift_up_delay))
        raw.up("Shift")
    else:
        # --- Fallback path: page.evaluate (detectable) ---
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
