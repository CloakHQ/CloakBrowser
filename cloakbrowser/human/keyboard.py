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


def _letter_keycode(letter: str) -> int:
    """Windows virtual key code for a latin letter (a→65 … z→90), verified
    against a real Microsoft Pinyin capture (x=88, i=73, n=78, z=90)."""
    return ord(letter.upper())


# A real IME commits by natural phrase, not per char. Chunk a Han run into
# phrases of this many chars (each is one composition + one Space commit).
_CJK_PHRASE_MIN, _CJK_PHRASE_MAX = 2, 4


def _build_phrases(
    text: str, ime_language: Optional[str]
) -> dict[int, tuple[str, list[str], int]]:
    """Map the start index of each Han phrase → (hanzi, [pinyin syllables], end index).

    Contiguous Han runs are converted with word context (polyphonic-correct, e.g.
    重庆 → chong/qing) then chunked into short phrases — a real user types a whole
    phrase then confirms it, rather than committing every character separately.
    Returns {} when disabled, when there are no Han chars, or when pypinyin is
    missing (warns once). A char whose pinyin isn't plain ASCII is left out of any
    phrase and falls back to insertText.
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

    phrases: dict[int, tuple[str, list[str], int]] = {}
    i, n = 0, len(text)
    while i < n:
        if not _is_chinese_ideograph(text[i]):
            i += 1
            continue
        j = i
        while j < n and _is_chinese_ideograph(text[j]):
            j += 1
        # Convert the whole run once (keeps word context), then slice into phrases.
        run_sylls = [s.lower() for s in lazy_pinyin(text[i:j])]
        k, off = i, 0
        while k < j:
            size = min(random.randint(_CJK_PHRASE_MIN, _CJK_PHRASE_MAX), j - k)
            sylls = run_sylls[off:off + size]
            if len(sylls) == size and all(s.isascii() and s.isalpha() for s in sylls):
                phrases[k] = (text[k:k + size], sylls, k + size - 1)
            k += size
            off += size
        i = j
    return phrases


def _compose_display(typed: list[tuple[int, str]]) -> str:
    """Build the composition string a Microsoft Pinyin IME shows for the letters
    typed so far: syllables joined by an apostrophe separator (xin + z → "xin'z")."""
    parts: dict[int, str] = {}
    order: list[int] = []
    for si, letter in typed:
        if si not in parts:
            parts[si] = ""
            order.append(si)
        parts[si] += letter
    return "'".join(parts[si] for si in order)


def _key_event(type_: str, vk: int, key: str, code: str) -> dict:
    return {"type": type_, "windowsVirtualKeyCode": vk, "key": key, "code": code}


def _type_cjk_phrase(
    hanzi: str, syllables: list[str], cfg: HumanConfig, cdp_session: Any
) -> None:
    """Reproduce a real pinyin-IME phrase, modeled on a Microsoft Pinyin capture.

    For each pinyin letter: a keydown carrying the IME-processing code
    (windowsVirtualKeyCode 229 / key "Process") grows one composition string
    (apostrophe-separated syllables), followed by a DUAL keyup — one 229 event and
    one for the real physical key (x→88). Then Space confirms the top candidate:
    the composition switches to the hanzi, commits (compositionend), and Space emits
    its own dual keyup (229 then 32).

    NOTE: compositionend fires isTrusted=false — a CDP Input.insertText limitation
    the customer confirmed matches a real IME on the same machine, so it is correct.
    """
    typed: list[tuple[int, str]] = []
    for si, syl in enumerate(syllables):
        for letter in syl:
            code = _LETTER_CODES.get(letter, "")
            kc = _letter_keycode(letter)
            cdp_session.send("Input.dispatchKeyEvent",
                             _key_event("keyDown", 229, "Process", code))
            typed.append((si, letter))
            disp = _compose_display(typed)
            cdp_session.send("Input.imeSetComposition",
                             {"text": disp, "selectionStart": len(disp), "selectionEnd": len(disp)})
            sleep_ms(rand_range(cfg.key_hold))
            cdp_session.send("Input.dispatchKeyEvent",
                             _key_event("keyUp", 229, "Process", code))
            cdp_session.send("Input.dispatchKeyEvent",
                             _key_event("keyUp", kc, letter, code))
            sleep_ms(rand_range(cfg.key_hold))
    # Brief thinking pause, then Space confirms the phrase's top candidate.
    sleep_ms(rand_range(cfg.mistype_delay_notice))
    cdp_session.send("Input.dispatchKeyEvent",
                     _key_event("keyDown", 229, "Process", "Space"))
    cdp_session.send("Input.imeSetComposition",
                     {"text": hanzi, "selectionStart": len(hanzi), "selectionEnd": len(hanzi)})
    cdp_session.send("Input.insertText", {"text": hanzi})  # commit → compositionend
    cdp_session.send("Input.dispatchKeyEvent",
                     _key_event("keyUp", 229, "Process", "Space"))
    cdp_session.send("Input.dispatchKeyEvent",
                     _key_event("keyUp", 32, " ", "Space"))


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
    # Chinese phrases get a real pinyin-IME flow when enabled (ime_language='zh'
    # + a CDP session + pypinyin available); everything else keeps insertText.
    phrases = (
        _build_phrases(text, cfg.ime_language) if cdp_session is not None else {}
    )
    skip_until = -1

    for i, ch in enumerate(text):
        if i <= skip_until:
            continue  # already typed as part of a phrase
        # Non-ASCII characters (Cyrillic, CJK, emoji) — use insertText
        if not ch.isascii():
            sleep_ms(rand_range(cfg.key_hold))
            if i in phrases:
                hanzi, sylls, end = phrases[i]
                try:
                    _type_cjk_phrase(hanzi, sylls, cfg, cdp_session)
                except Exception:
                    # A CDP hiccup mid-phrase must not abort the whole type().
                    _log.debug("CJK IME failed for %r; using insertText", hanzi, exc_info=True)
                    for c in hanzi:
                        raw.insert_text(c)
                skip_until = end
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
