/**
 * cloakbrowser-human — Human-like keyboard input.
 *
 * Stealth-aware: when a CDPSession is provided, shift symbols are typed
 * via CDP Input.dispatchKeyEvent (isTrusted=true, no evaluate stack trace).
 * Falls back to page.evaluate when no CDPSession is available.
 */

import type { Page, CDPSession } from 'playwright-core';
import { RawKeyboard } from './mouse.js';
import { HumanConfig, rand, randRange, sleep } from './config.js';

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

  for (let i = 0; i < chars.length; i++) {
    const ch = chars[i];

    // Non-ASCII characters (Cyrillic, CJK, emoji) — use insertText
    if (!isAscii(ch)) {
      await sleep(randRange(cfg.key_hold));
      await raw.insertText(ch);
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
