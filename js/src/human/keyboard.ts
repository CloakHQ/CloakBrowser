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

/**
 * Map each Chinese-ideograph char index → its lowercase pinyin syllable.
 *
 * Converts per contiguous Han run (not per isolated char) so pinyin-pro's
 * word-context disambiguation gives correct polyphonic readings
 * (重庆 → chong/qing). Returns an empty Map when disabled, when there are no Han
 * chars, or when pinyin-pro is not installed (warns once).
 */
export async function pinyinMap(text: string, imeLanguage?: string | null): Promise<Map<number, string>> {
  const result = new Map<number, string>();
  const chars = [...text];
  if (imeLanguage !== 'zh' || !chars.some(isChineseIdeograph)) return result;
  const pinyinFn = await getPinyinFn();
  if (!pinyinFn) return result;

  let i = 0;
  while (i < chars.length) {
    if (!isChineseIdeograph(chars[i])) { i++; continue; }
    let j = i;
    while (j < chars.length && isChineseIdeograph(chars[j])) j++;
    // Pure-Han run → pinyin-pro returns exactly one syllable per char.
    // `v: true` outputs ü as ASCII "v" (nü→nv), matching pypinyin and how a real
    // pinyin IME works (no ü key — users press v); without it ü fails the [a-z] guard.
    const syllables = pinyinFn(chars.slice(i, j).join(''), { toneType: 'none', type: 'array', v: true });
    for (let k = 0; k < syllables.length; k++) {
      const syl = (syllables[k] || '').toLowerCase();
      if (/^[a-z]+$/.test(syl)) result.set(i + k, syl);
    }
    i = j;
  }
  return result;
}

/**
 * Reproduce a real pinyin-IME flow for one Han char.
 *
 * Per pinyin letter: a keydown/keyup carrying the IME-processing code
 * (windowsVirtualKeyCode 229 / key "Process") plus an Input.imeSetComposition
 * that grows the composition string (fires compositionstart/update). Then commit
 * the composed hanzi via Input.insertText (fires compositionend + input).
 *
 * NOTE: compositionend fires isTrusted=false — a CDP Input.insertText limitation
 * at the binary level, not fixable from the wrapper. The pinyin-letter keydown
 * stream and composition/input events are all trusted.
 */
async function typeCjkIme(
  ch: string,
  pinyin: string,
  cfg: HumanConfig,
  cdpSession: CDPSession,
): Promise<void> {
  for (let i = 0; i < pinyin.length; i++) {
    const code = LETTER_CODES[pinyin[i]] || '';
    await cdpSession.send('Input.dispatchKeyEvent', {
      type: 'keyDown',
      windowsVirtualKeyCode: 229, // VK_PROCESSKEY — IME is processing
      key: 'Process',
      code,
    });
    await cdpSession.send('Input.imeSetComposition', {
      text: pinyin.slice(0, i + 1),
      selectionStart: i + 1,
      selectionEnd: i + 1,
    });
    await sleep(randRange(cfg.key_hold));
    await cdpSession.send('Input.dispatchKeyEvent', {
      type: 'keyUp',
      windowsVirtualKeyCode: 229,
      key: 'Process',
      code,
    });
    if (i < pinyin.length - 1) await sleep(randRange(cfg.key_hold));
  }
  // Commit the top candidate → compositionend + input.
  await cdpSession.send('Input.insertText', { text: ch });
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

  // Chinese ideographs get a real pinyin-IME flow when enabled (ime_language='zh'
  // + a CDP session + pinyin-pro available); everything else keeps insertText.
  const pinyinIdx = cdpSession
    ? await pinyinMap(text, cfg.ime_language)
    : new Map<number, string>();

  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];

    // Non-ASCII characters (Cyrillic, CJK, emoji) — use insertText
    if (!isAscii(ch)) {
      await sleep(randRange(cfg.key_hold));
      const py = pinyinIdx.get(i);
      if (py && cdpSession) {
        try {
          await typeCjkIme(ch, py, cfg, cdpSession);
        } catch (err) {
          // A CDP hiccup on one char must not abort the whole type().
          console.debug(`[cloakbrowser] CJK IME failed for ${ch}; using insertText`, err);
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
