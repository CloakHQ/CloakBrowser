/**
 * cloakbrowser-human — Human-like keyboard input.
 *
 * Stealth-aware: when a CDPSession is provided, shift symbols are typed
 * via CDP Input.dispatchKeyEvent (isTrusted=true, no evaluate stack trace).
 * Falls back to page.evaluate when no CDPSession is available.
 */

import type { Page, CDPSession } from 'playwright-core';
import type { RawKeyboard } from './mouse.js';
import { type HumanConfig, randRange, sleep } from './config.js';

export async function pressWithDelay<Key>(
  press: (key: Key, options?: { delay?: number }) => Promise<void>,
  key: Key,
  options?: { delay?: number },
  defaultDelay?: number,
): Promise<void> {
  const delay = options?.delay ?? defaultDelay;
  if (delay === undefined) {
    await press(key);
    return;
  }
  await press(key, { delay });
}

const SHIFT_SYMBOLS = new Set([
  '@', '#', '!', '$', '%', '^', '&', '*', '(', ')',
  '_', '+', '{', '}', '|', ':', '"', '<', '>', '?', '~',
]);

const NEARBY_KEYS: Record<string, string> = {
  a: 'sqwz', b: 'vghn', c: 'xdfv', d: 'sfecx', e: 'wrsdf',
  f: 'dgrtcv', g: 'fhtyb', h: 'gjybn', i: 'ujko', j: 'hkunm',
  k: 'jloi', l: 'kop', m: 'njk', n: 'bhjm', o: 'iklp',
  p: 'ol', q: 'wa', r: 'edft', s: 'awedxz', t: 'rfgy',
  u: 'yhji', v: 'cfgb', w: 'qase', x: 'zsdc', y: 'tghu',
  z: 'asx',
  '1': '2q', '2': '13qw', '3': '24we', '4': '35er', '5': '46rt',
  '6': '57ty', '7': '68yu', '8': '79ui', '9': '80io', '0': '9p',
};

/**
 * CDP key code for each shift symbol's physical key.
 * Used by Input.dispatchKeyEvent to produce isTrusted=true events.
 */
const SHIFT_SYMBOL_CODES: Record<string, string> = {
  '!': 'Digit1', '@': 'Digit2', '#': 'Digit3', '$': 'Digit4',
  '%': 'Digit5', '^': 'Digit6', '&': 'Digit7', '*': 'Digit8',
  '(': 'Digit9', ')': 'Digit0', '_': 'Minus', '+': 'Equal',
  '{': 'BracketLeft', '}': 'BracketRight', '|': 'Backslash',
  ':': 'Semicolon', '"': 'Quote', '<': 'Comma', '>': 'Period',
  '?': 'Slash', '~': 'Backquote',
};

/**
 * Windows virtual key codes for shift symbols.
 * Input.dispatchKeyEvent uses these to match real keyboard behavior.
 */
const SHIFT_SYMBOL_KEYCODES: Record<string, number> = {
  '!': 49, '@': 50, '#': 51, '$': 52, '%': 53,
  '^': 54, '&': 55, '*': 56, '(': 57, ')': 48,
  '_': 189, '+': 187, '{': 219, '}': 221, '|': 220,
  ':': 186, '"': 222, '<': 188, '>': 190, '?': 191,
  '~': 192,
};

function isAscii(ch: string): boolean {
  const code = ch.codePointAt(0);
  return code !== undefined && code < 128;
}

// Physical key `code` for each latin letter (CJK IME keydown layer).
export const LETTER_CODES: Record<string, string> = Object.fromEntries(
  'abcdefghijklmnopqrstuvwxyz'.split('').map(c => [c, `Key${c.toUpperCase()}`]),
);

/**
 * True for Han ideographs (CJK Unified + Ext A + Compat). This block is shared:
 * Japanese kanji and Korean hanja are indistinguishable from Chinese hanzi by
 * code point, so with ime_language='zh' they too get Mandarin pinyin. The precise
 * guarantee is only that kana and Hangul syllables are excluded — not "Chinese-only".
 */
export function isChineseIdeograph(ch: string): boolean {
  const o = ch.codePointAt(0);
  if (o === undefined) return false;
  return (o >= 0x4e00 && o <= 0x9fff) || (o >= 0x3400 && o <= 0x4dbf) ||
    (o >= 0xf900 && o <= 0xfaff);
}

// Lazy handle to the optional pinyin-pro dependency. undefined = not yet tried,
// null = unavailable (warned once).
let _pinyinFn: ((s: string, opts: object) => string[]) | null | undefined;
let _pinyinWarned = false;

async function getPinyinFn(): Promise<((s: string, opts: object) => string[]) | null> {
  if (_pinyinFn !== undefined) return _pinyinFn;
  try {
    const mod = await import('pinyin-pro');
    _pinyinFn = (mod as { pinyin: (s: string, opts: object) => string[] }).pinyin;
  } catch {
    _pinyinFn = null;
    if (!_pinyinWarned) {
      _pinyinWarned = true;
      console.warn(
        "[cloakbrowser] Chinese IME humanization (ime_language='zh') requires " +
        'pinyin-pro; falling back to basic insertion. Install with: ' +
        'npm install pinyin-pro',
      );
    }
  }
  return _pinyinFn;
}

// A real IME commits by natural phrase, not per char. Chunk a Han run into
// phrases of this many chars (each is one composition + one Space commit).
const CJK_PHRASE_MIN = 2;
const CJK_PHRASE_MAX = 4;

/** Windows virtual key code for a latin letter (a→65 … z→90), matching a real
 * Microsoft Pinyin capture (x=88, i=73, n=78, z=90). */
export function letterKeycode(letter: string): number {
  return letter.toUpperCase().charCodeAt(0);
}

/**
 * Map each Han phrase's start index → [hanzi, pinyin syllables, end index].
 *
 * Contiguous Han runs are converted with word context (polyphonic-correct,
 * 重庆 → chong/qing) then chunked into short phrases — a real user types a whole
 * phrase then confirms it, rather than committing every character separately.
 * Empty Map when disabled, no Han chars, or pinyin-pro missing (warns once). A char
 * whose pinyin isn't plain ASCII is left out of any phrase and falls back.
 */
export async function buildPhrases(
  text: string,
  imeLanguage?: string | null,
): Promise<Map<number, [string, string[], number]>> {
  const result = new Map<number, [string, string[], number]>();
  const chars = [...text];
  if (imeLanguage !== 'zh' || !chars.some(isChineseIdeograph)) return result;
  const pinyinFn = await getPinyinFn();
  if (!pinyinFn) return result;

  let i = 0;
  while (i < chars.length) {
    if (!isChineseIdeograph(chars[i])) { i++; continue; }
    let j = i;
    while (j < chars.length && isChineseIdeograph(chars[j])) j++;
    // `v: true` → ü as ASCII "v" (nü→nv), matching pypinyin and a real IME (no ü key).
    const runSylls = pinyinFn(chars.slice(i, j).join(''), { toneType: 'none', type: 'array', v: true })
      .map(s => (s || '').toLowerCase());
    let k = i, off = 0;
    while (k < j) {
      const size = Math.min(
        CJK_PHRASE_MIN + Math.floor(Math.random() * (CJK_PHRASE_MAX - CJK_PHRASE_MIN + 1)),
        j - k,
      );
      const sylls = runSylls.slice(off, off + size);
      if (sylls.length === size && sylls.every(s => /^[a-z]+$/.test(s))) {
        result.set(k, [chars.slice(k, k + size).join(''), sylls, k + size - 1]);
      }
      k += size;
      off += size;
    }
    i = j;
  }
  return result;
}

/** Composition string a Microsoft Pinyin IME shows for the letters typed so far:
 * syllables joined by an apostrophe (xin + z → "xin'z"). */
export function composeDisplay(typed: Array<[number, string]>): string {
  const parts = new Map<number, string>();
  for (const [si, letter] of typed) parts.set(si, (parts.get(si) || '') + letter);
  return [...parts.values()].join("'");
}

/**
 * Reproduce a real pinyin-IME phrase, modeled on a Microsoft Pinyin capture.
 * Per letter: a Process/229 keydown grows the composition, then a DUAL keyup
 * (229 and the physical key, x→88). Space confirms the top candidate: composition
 * switches to the hanzi, commits (compositionend), then Space's own dual keyup (229, 32).
 *
 * NOTE: compositionend fires isTrusted=false — a CDP Input.insertText limitation the
 * customer confirmed matches a real IME on the same machine, so it is correct.
 */
export async function typeCjkPhrase(
  hanzi: string,
  syllables: string[],
  cfg: HumanConfig,
  cdpSession: CDPSession,
): Promise<void> {
  const typed: Array<[number, string]> = [];
  for (let si = 0; si < syllables.length; si++) {
    for (const letter of syllables[si]) {
      const code = LETTER_CODES[letter] || '';
      const kc = letterKeycode(letter);
      await cdpSession.send('Input.dispatchKeyEvent', { type: 'keyDown', windowsVirtualKeyCode: 229, key: 'Process', code });
      typed.push([si, letter]);
      const disp = composeDisplay(typed);
      await cdpSession.send('Input.imeSetComposition', { text: disp, selectionStart: disp.length, selectionEnd: disp.length });
      await sleep(randRange(cfg.key_hold));
      await cdpSession.send('Input.dispatchKeyEvent', { type: 'keyUp', windowsVirtualKeyCode: 229, key: 'Process', code });
      await cdpSession.send('Input.dispatchKeyEvent', { type: 'keyUp', windowsVirtualKeyCode: kc, key: letter, code });
      await sleep(randRange(cfg.key_hold));
    }
  }
  // Brief thinking pause, then Space confirms the phrase's top candidate.
  await sleep(randRange(cfg.mistype_delay_notice));
  await cdpSession.send('Input.dispatchKeyEvent', { type: 'keyDown', windowsVirtualKeyCode: 229, key: 'Process', code: 'Space' });
  await cdpSession.send('Input.imeSetComposition', { text: hanzi, selectionStart: hanzi.length, selectionEnd: hanzi.length });
  await cdpSession.send('Input.insertText', { text: hanzi }); // commit → compositionend
  await cdpSession.send('Input.dispatchKeyEvent', { type: 'keyUp', windowsVirtualKeyCode: 229, key: 'Process', code: 'Space' });
  await cdpSession.send('Input.dispatchKeyEvent', { type: 'keyUp', windowsVirtualKeyCode: 32, key: ' ', code: 'Space' });
}

// Full-width Chinese punctuation → physical key in Microsoft Pinyin (verified from a
// real capture): [needsShift, code, keyCode, baseKey, shiftedKey]. keyCode is the
// physical key's base code; the keyup `key` char is shifted only while Shift is held.
export const CJK_PUNCT: Record<string, [boolean, string, number, string, string]> = {
  '，': [false, 'Comma', 188, ',', ','],
  '。': [false, 'Period', 190, '.', '.'],
  '；': [false, 'Semicolon', 186, ';', ';'],
  '、': [false, 'Backslash', 220, '\\', '\\'],
  '？': [true, 'Slash', 191, '/', '?'],
  '！': [true, 'Digit1', 49, '1', '!'],
  '：': [true, 'Semicolon', 186, ';', ':'],
};

/**
 * Type one full-width Chinese punctuation mark through the IME, matching a real
 * Microsoft Pinyin capture: keydown Process/229 on its physical key → composition →
 * commit → dual keyup (229 + physical keyCode). Shift marks wrap it in Shift; the
 * Shift-release order is randomized (real users vary it) and the keyup `key` char
 * follows the Shift state.
 */
export async function typeCjkPunct(
  ch: string,
  cfg: HumanConfig,
  cdpSession: CDPSession,
): Promise<void> {
  const [shift, code, kc, baseKey, shiftedKey] = CJK_PUNCT[ch];
  if (shift) {
    await cdpSession.send('Input.dispatchKeyEvent', { type: 'keyDown', windowsVirtualKeyCode: 16, key: 'Shift', code: 'ShiftLeft' });
    await sleep(randRange(cfg.shift_down_delay));
  }
  await cdpSession.send('Input.dispatchKeyEvent', { type: 'keyDown', windowsVirtualKeyCode: 229, key: 'Process', code });
  await cdpSession.send('Input.imeSetComposition', { text: ch, selectionStart: ch.length, selectionEnd: ch.length });
  await sleep(randRange(cfg.key_hold));
  await cdpSession.send('Input.insertText', { text: ch });
  const releaseShiftFirst = shift && Math.random() < 0.5;
  if (releaseShiftFirst) {
    await cdpSession.send('Input.dispatchKeyEvent', { type: 'keyUp', windowsVirtualKeyCode: 16, key: 'Shift', code: 'ShiftLeft' });
    await cdpSession.send('Input.dispatchKeyEvent', { type: 'keyUp', windowsVirtualKeyCode: 229, key: 'Process', code });
    await cdpSession.send('Input.dispatchKeyEvent', { type: 'keyUp', windowsVirtualKeyCode: kc, key: baseKey, code });
  } else {
    await cdpSession.send('Input.dispatchKeyEvent', { type: 'keyUp', windowsVirtualKeyCode: 229, key: 'Process', code });
    await cdpSession.send('Input.dispatchKeyEvent', { type: 'keyUp', windowsVirtualKeyCode: kc, key: shift ? shiftedKey : baseKey, code });
    if (shift) await cdpSession.send('Input.dispatchKeyEvent', { type: 'keyUp', windowsVirtualKeyCode: 16, key: 'Shift', code: 'ShiftLeft' });
  }
}

function getNearbyKey(ch: string): string {
  const lower = ch.toLowerCase();
  if (lower in NEARBY_KEYS) {
    const neighbors = NEARBY_KEYS[lower];
    const wrong = neighbors[Math.floor(Math.random() * neighbors.length)];
    return ch === ch.toUpperCase() && ch !== ch.toLowerCase() ? wrong.toUpperCase() : wrong;
  }
  return ch;
}

function isUpperCase(ch: string): boolean {
  return ch.length === 1 && ch >= 'A' && ch <= 'Z';
}

/**
 * Type text with human-like per-character timing, mistype simulation,
 * and realistic shift handling.
 *
 * @param cdpSession - If provided, shift symbols use CDP Input.dispatchKeyEvent
 *   producing isTrusted=true events with no evaluate stack trace.
 *   If null/undefined, falls back to page.evaluate (detectable).
 */
export async function humanType(
  page: Page,
  raw: RawKeyboard,
  text: string,
  cfg: HumanConfig,
  cdpSession?: CDPSession | null,
): Promise<void> {
  const chars = [...text]; // Handle emoji surrogate pairs correctly

  // Chinese phrases get a real pinyin-IME flow when enabled (ime_language='zh'
  // + a CDP session + pinyin-pro available); everything else keeps insertText.
  const phrases = cdpSession
    ? await buildPhrases(text, cfg.ime_language)
    : new Map<number, [string, string[], number]>();
  let skipUntil = -1;

  for (let i = 0; i < chars.length; i++) {
    if (i <= skipUntil) continue; // already typed as part of a phrase
    const ch = chars[i];

    // Non-ASCII characters (Cyrillic, CJK, emoji) — use insertText
    if (!isAscii(ch)) {
      await sleep(randRange(cfg.key_hold));
      const phrase = phrases.get(i);
      if (phrase && cdpSession) {
        const [hanzi, sylls, end] = phrase;
        try {
          await typeCjkPhrase(hanzi, sylls, cfg, cdpSession);
        } catch (err) {
          // A CDP hiccup mid-phrase must not abort the whole type().
          console.debug(`[cloakbrowser] CJK IME failed for ${hanzi}; using insertText`, err);
          for (const c of hanzi) await raw.insertText(c);
        }
        skipUntil = end;
      } else if (cfg.ime_language === 'zh' && cdpSession && ch in CJK_PUNCT) {
        try {
          await typeCjkPunct(ch, cfg, cdpSession);
        } catch (err) {
          console.debug(`[cloakbrowser] CJK punct failed for ${ch}; using insertText`, err);
          await raw.insertText(ch);
        }
      } else {
        await raw.insertText(ch);
      }
      if (i < chars.length - 1) {
        await interCharDelay(cfg);
      }
      continue;
    }

    // Mistype chance — only for ASCII alphanumeric
    if (Math.random() < cfg.mistype_chance && /^[a-zA-Z0-9]$/.test(ch)) {
      const wrong = getNearbyKey(ch);
      await typeNormalChar(raw, wrong, cfg);
      await sleep(randRange(cfg.mistype_delay_notice));
      await raw.down('Backspace');
      await sleep(randRange(cfg.key_hold));
      await raw.up('Backspace');
      await sleep(randRange(cfg.mistype_delay_correct));
    }

    if (isUpperCase(ch)) {
      await typeShiftedChar(raw, ch, cfg);
    } else if (SHIFT_SYMBOLS.has(ch)) {
      await typeShiftSymbol(page, raw, ch, cfg, cdpSession);
    } else {
      await typeNormalChar(raw, ch, cfg);
    }

    if (i < chars.length - 1) {
      await interCharDelay(cfg);
    }
  }
}

async function typeNormalChar(raw: RawKeyboard, ch: string, cfg: HumanConfig): Promise<void> {
  await raw.down(ch);
  await sleep(randRange(cfg.key_hold));
  await raw.up(ch);
}

async function typeShiftedChar(raw: RawKeyboard, ch: string, cfg: HumanConfig): Promise<void> {
  await raw.down('Shift');
  await sleep(randRange(cfg.shift_down_delay));
  await raw.down(ch);
  await sleep(randRange(cfg.key_hold));
  await raw.up(ch);
  await sleep(randRange(cfg.shift_up_delay));
  await raw.up('Shift');
}

/**
 * Type a shift symbol character.
 *
 * Stealth path (cdpSession provided):
 *   Uses CDP Input.dispatchKeyEvent → isTrusted=true, clean stack.
 *
 * Fallback path (no cdpSession):
 *   Uses raw.insertText + page.evaluate to dispatch synthetic KeyboardEvent.
 *   Detectable via isTrusted=false and evaluate stack frame.
 */
async function typeShiftSymbol(
  page: Page,
  raw: RawKeyboard,
  ch: string,
  cfg: HumanConfig,
  cdpSession?: CDPSession | null,
): Promise<void> {
  if (cdpSession) {
    // --- Stealth path: CDP Input.dispatchKeyEvent ---
    const code = SHIFT_SYMBOL_CODES[ch] || '';
    const keyCode = SHIFT_SYMBOL_KEYCODES[ch] || 0;

    await raw.down('Shift');
    await sleep(randRange(cfg.shift_down_delay));

    await cdpSession.send('Input.dispatchKeyEvent', {
      type: 'keyDown',
      modifiers: 8, // Shift modifier flag
      key: ch,
      code,
      windowsVirtualKeyCode: keyCode,
      text: ch,
      unmodifiedText: ch,
    });
    await sleep(randRange(cfg.key_hold));

    await cdpSession.send('Input.dispatchKeyEvent', {
      type: 'keyUp',
      modifiers: 8,
      key: ch,
      code,
      windowsVirtualKeyCode: keyCode,
    });

    await sleep(randRange(cfg.shift_up_delay));
    await raw.up('Shift');
  } else {
    // --- Fallback path: page.evaluate (detectable) ---
    await raw.down('Shift');
    await sleep(randRange(cfg.shift_down_delay));
    await raw.insertText(ch);
    await page.evaluate((key: string) => {
      const el = document.activeElement;
      if (el) {
        el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
        el.dispatchEvent(new KeyboardEvent('keyup', { key, bubbles: true }));
      }
    }, ch);
    await sleep(randRange(cfg.shift_up_delay));
    await raw.up('Shift');
  }
}

async function interCharDelay(cfg: HumanConfig): Promise<void> {
  if (Math.random() < cfg.typing_pause_chance) {
    await sleep(randRange(cfg.typing_pause_range));
  } else {
    const delay = cfg.typing_delay + (Math.random() - 0.5) * 2 * cfg.typing_delay_spread;
    await sleep(Math.max(10, delay));
  }
}
