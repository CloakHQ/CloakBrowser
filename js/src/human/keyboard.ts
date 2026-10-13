/**
 * cloakbrowser-human — Human-like keyboard input.
 *
 * Stealth-aware: when a CDPSession is provided, shift symbols are typed
 * via CDP Input.dispatchKeyEvent (isTrusted=true, no evaluate stack trace).
 * Falls back to page.evaluate when no CDPSession is available.
 */

import type { Page, CDPSession } from 'playwright-core';
import type { RawKeyboard } from './mouse.js';
import { type HumanConfig, randLog, randLognormal, randRange, sleep } from './config.js';

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

export const SHIFT_SYMBOLS = new Set([
  '@', '#', '!', '$', '%', '^', '&', '*', '(', ')',
  '_', '+', '{', '}', '|', ':', '"', '<', '>', '?', '~',
]);

export const NEARBY_KEYS: Record<string, string> = {
  a: 'sqwz', b: 'vghn', c: 'xdfv', d: 'sfecx', e: 'wrsdf',
  f: 'dgrtcv', g: 'fhtyb', h: 'gjybn', i: 'ujko', j: 'hkunm',
  k: 'jloi', l: 'kop', m: 'njk', n: 'bhjm', o: 'iklp',
  p: 'ol', q: 'wa', r: 'edft', s: 'awedxz', t: 'rfgy',
  u: 'yhji', v: 'cfgb', w: 'qase', x: 'zsdc', y: 'tghu',
  z: 'asx',
  // Digits stay digits: a letter typo is rejected by <input type=number>,
  // so the correcting Backspace would delete the previous real digit (#573).
  '1': '2', '2': '13', '3': '24', '4': '35', '5': '46',
  '6': '57', '7': '68', '8': '79', '9': '80', '0': '9',
};

/**
 * CDP key code for each shift symbol's physical key.
 * Used by Input.dispatchKeyEvent to produce isTrusted=true events.
 */
export const SHIFT_SYMBOL_CODES: Record<string, string> = {
  '!': 'Digit1', '@': 'Digit2', '#': 'Digit3', '$': 'Digit4',
  '%': 'Digit5', '^': 'Digit6', '&': 'Digit7', '*': 'Digit8',
  '(': 'Digit9', ')': 'Digit0', '_': 'Minus', '+': 'Equal',
  '{': 'BracketLeft', '}': 'BracketRight', '|': 'Backslash',
  ':': 'Semicolon', '"': 'Quote', '<': 'Comma', '>': 'Period',
  '?': 'Slash', '~': 'Backquote',
};

/** Physical key of each unshifted digit / punctuation character, so a shift
 * symbol and its base character ("1" and "!") count as the same key. */
const BASE_KEY_CODES: Record<string, string> = {
  '1': 'Digit1', '2': 'Digit2', '3': 'Digit3', '4': 'Digit4', '5': 'Digit5',
  '6': 'Digit6', '7': 'Digit7', '8': 'Digit8', '9': 'Digit9', '0': 'Digit0',
  '-': 'Minus', '=': 'Equal', '[': 'BracketLeft', ']': 'BracketRight',
  '\\': 'Backslash', ';': 'Semicolon', "'": 'Quote', ',': 'Comma',
  '.': 'Period', '/': 'Slash', '`': 'Backquote',
};

/** The physical key that types `ch`: "x" and "X" are one key, so are "1" and
 * "!". Used so a key never goes down while it is still held. */
export function physicalKey(ch: string): string {
  return SHIFT_SYMBOL_CODES[ch] || BASE_KEY_CODES[ch] || ch.toLowerCase();
}

/**
 * Windows virtual key codes for shift symbols.
 * Input.dispatchKeyEvent uses these to match real keyboard behavior.
 */
export const SHIFT_SYMBOL_KEYCODES: Record<string, number> = {
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

// ---------------------------------------------------------------------------
// Key timing (shared by the humanize engine)
// ---------------------------------------------------------------------------
//
// Numbers come from the 136M Keystrokes data (Dhakal et al., CHI 2018):
// letters typed with the other hand follow ~20% faster than letters of the
// same hand, a repeated letter (same finger) is slower, and the first letter
// of a word (after a space) is the slowest. People commonly press the next
// key before letting go of the previous one (rollover).

const LEFT_HAND = new Set('qwertasdfgzxcvb`12345~!@#$%');

function hand(ch: string): 'L' | 'R' | null {
  const c = ch.toLowerCase();
  if (!c || c.length !== 1 || c.charCodeAt(0) > 127 || /\s/.test(c)) return null;
  return LEFT_HAND.has(c) ? 'L' : 'R';
}

/** How much slower / faster than average the press of `ch` follows `prev`. */
export function gapFactor(prev: string, ch: string): number {
  if (!prev) return 1;
  if (prev === ' ') return 1.3;
  if (ch === ' ') return 0.9;
  if (prev.toLowerCase() === ch.toLowerCase()) return 1.05;
  const hp = hand(prev), hc = hand(ch);
  if (hp && hc) return hp !== hc ? 0.85 : 1.1;
  return 1;
}

/**
 * Milliseconds from the press of `prev` to the press of `ch` (log-normal
 * around `typing_delay`, plus occasional thinking pauses before words).
 */
export function keyGap(cfg: HumanConfig, prev: string, ch: string): number {
  const median = Math.max(1, cfg.typing_delay * gapFactor(prev, ch));
  const spread = Math.max(0, cfg.typing_delay_spread);
  const sigma = cfg.typing_delay > 0 ? Math.log1p(spread / cfg.typing_delay) : 0;
  let gap = randLognormal(median, sigma);
  const wordStart = prev === ' ' || prev === '';
  const chance = cfg.typing_pause_chance * (wordStart ? 1 : 0.1);
  if (chance > 0 && Math.random() < chance) gap += randRange(cfg.typing_pause_range);
  return Math.max(15, gap);
}

/** How long one key stays down (ms). */
export function keyHold(cfg: HumanConfig): number {
  return Math.max(1, randLog(cfg.key_hold));
}

// ---------------------------------------------------------------------------
// Typing timeline
// ---------------------------------------------------------------------------

type KeyUp = { due: number; key: string; cdp: any | null };

/** Key primitives a Typist drives. `cdp` sends one Input.dispatchKeyEvent. */
export interface TypistKeys {
  down(key: string): Promise<void>;
  up(key: string): Promise<void>;
  insertText(text: string): Promise<void>;
  cdp(params: any): Promise<void>;
}

const sleepMs = (ms: number) => (ms > 0 ? sleep(ms) : Promise.resolve());
const isUpper = (ch: string) => /^[A-Z]$/.test(ch);

/**
 * Presses keys on a timeline the way a person does: each press follows the
 * previous *press* after a letter-dependent gap, and each key is held for its
 * own time, so the next key often goes down before the previous one comes up
 * (rollover). Shift goes down before the letter and is usually let go just
 * before the letter key. Releases are queued and sent when due.
 */
export class Typist {
  private prev = '';
  private lastPress: number | null = null;
  private ups: KeyUp[] = [];
  private shiftUpDue: number | null = null;
  private shiftDown = false;

  constructor(private keys: TypistKeys, private cfg: HumanConfig, private delay?: number) {}

  private async wait(until: number): Promise<void> { await sleepMs(until - performance.now()); }

  private async shift(down: boolean): Promise<void> {
    this.shiftDown = down;
    await (down ? this.keys.down('Shift') : this.keys.up('Shift'));
  }

  private async up(u: KeyUp): Promise<void> {
    if (u.cdp) await this.keys.cdp(u.cdp);
    else if (u.key.length === 1 && isUpper(u.key) && !this.shiftDown) await this.keys.up(u.key.toLowerCase());
    else await this.keys.up(u.key);
  }

  /** Send every release due before `until` (in time order). */
  private async flush(until: number): Promise<void> {
    for (;;) {
      let next: KeyUp | null = null;
      for (const u of this.ups) if (u.due <= until && (!next || u.due < next.due)) next = u;
      const shiftFirst = this.shiftUpDue !== null && this.shiftUpDue <= until && (!next || this.shiftUpDue <= next.due);
      if (shiftFirst) {
        await this.wait(this.shiftUpDue!);
        this.shiftUpDue = null;
        await this.shift(false);
        continue;
      }
      if (!next) return;
      await this.wait(next.due);
      this.ups.splice(this.ups.indexOf(next), 1);
      await this.up(next);
    }
  }

  async key(ch: string): Promise<void> {
    const cfg = this.cfg;
    let at: number;
    if (this.lastPress === null) at = performance.now();
    else if (this.delay !== undefined && this.delay !== null) at = this.lastPress + this.delay;
    else at = this.lastPress + keyGap(cfg, this.prev, ch);
    const shifted = isUpper(ch) || SHIFT_SYMBOLS.has(ch);
    const textOnly = !isAscii(ch);
    // A key cannot go down twice: let the earlier press of the same physical
    // key ("x" before "X", "1" before "!") come up first.
    const key = physicalKey(ch);
    const same = this.ups.filter(u => physicalKey(u.key) === key);
    if (same.length) at = Math.max(at, Math.min(...same.map(u => u.due)) + 5);
    if (shifted) {
      if (this.shiftUpDue !== null) {
        this.shiftUpDue = null; // still down from the previous capital
        await this.flush(at);
      } else {
        const lead = randLog(cfg.shift_down_delay);
        // Shift goes down after the previous key comes up.
        await this.flush(at - lead);
        await this.wait(at - lead);
        await this.shift(true);
        // Keys due to come up while Shift is going down (e.g. the "x" of
        // "xX") are released before the capital is pressed.
        await this.flush(at);
      }
    } else {
      await this.flush(at);
      if (this.shiftUpDue !== null && ch !== 'Backspace') {
        // A lower-case key while Shift is still down: let it go first.
        this.shiftUpDue = null;
        await this.shift(false);
      }
    }
    await this.wait(at);
    this.lastPress = Math.max(at, performance.now());
    const hold0 = keyHold(cfg);
    const hold = this.delay !== undefined && this.delay !== null && this.delay < hold0 ? this.delay : hold0;
    const upAt = this.lastPress + hold;
    if (textOnly) {
      // Non-ASCII text has no key: it arrives as one input, like an IME.
      await this.keys.insertText(ch);
    } else if (SHIFT_SYMBOLS.has(ch)) {
      const code = SHIFT_SYMBOL_CODES[ch] || '';
      const vk = SHIFT_SYMBOL_KEYCODES[ch] || 0;
      await this.keys.cdp({
        type: 'keyDown', modifiers: 8, key: ch, code, windowsVirtualKeyCode: vk, text: ch, unmodifiedText: ch,
      });
      this.ups.push({ due: upAt, key: ch, cdp: { type: 'keyUp', modifiers: 8, key: ch, code, windowsVirtualKeyCode: vk } });
    } else {
      await this.keys.down(ch);
      this.ups.push({ due: upAt, key: ch, cdp: null });
    }
    if (shifted) {
      // Usually let go of Shift around the letter's release, most often just
      // before it.
      this.shiftUpDue = Math.max(this.lastPress + 10, upAt + randRange(cfg.shift_up_delay));
      // The CDP keyUp of a shift symbol carries the Shift modifier.
      if (SHIFT_SYMBOLS.has(ch)) this.shiftUpDue = Math.max(this.shiftUpDue, upAt + 5);
    }
    this.prev = ch;
  }

  /** Release everything still held, on schedule. */
  async finish(): Promise<void> { await this.flush(Infinity); }

  /** Hands off the keys (before a pause): release, and start the next key
   * without a gap carried over from the last one. */
  async rest(): Promise<void> {
    await this.finish();
    this.lastPress = null;
  }

  /** Error path: never leave a key stuck down. */
  async releaseAll(): Promise<void> {
    const ups = this.ups;
    this.ups = [];
    for (const u of ups) { try { await this.up(u); } catch { /* best effort */ } }
    this.shiftUpDue = null;
    if (this.shiftDown) { try { await this.shift(false); } catch { /* best effort */ } }
  }
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
      await sleep(keyHold(cfg));
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
      await sleep(keyHold(cfg));
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
  await sleep(keyHold(cfg));
  await raw.up(ch);
}

async function typeShiftedChar(raw: RawKeyboard, ch: string, cfg: HumanConfig): Promise<void> {
  await raw.down('Shift');
  await sleep(randLog(cfg.shift_down_delay));
  await raw.down(ch);
  await sleep(keyHold(cfg));
  await raw.up(ch);
  await sleep(Math.max(0, randRange(cfg.shift_up_delay)));
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
    await sleep(randLog(cfg.shift_down_delay));

    await cdpSession.send('Input.dispatchKeyEvent', {
      type: 'keyDown',
      modifiers: 8, // Shift modifier flag
      key: ch,
      code,
      windowsVirtualKeyCode: keyCode,
      text: ch,
      unmodifiedText: ch,
    });
    await sleep(keyHold(cfg));

    await cdpSession.send('Input.dispatchKeyEvent', {
      type: 'keyUp',
      modifiers: 8,
      key: ch,
      code,
      windowsVirtualKeyCode: keyCode,
    });

    await sleep(Math.max(0, randRange(cfg.shift_up_delay)));
    await raw.up('Shift');
  } else {
    // --- Fallback path: page.evaluate (detectable) ---
    await raw.down('Shift');
    await sleep(randLog(cfg.shift_down_delay));
    await raw.insertText(ch);
    await page.evaluate((key: string) => {
      const el = document.activeElement;
      if (el) {
        el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
        el.dispatchEvent(new KeyboardEvent('keyup', { key, bubbles: true }));
      }
    }, ch);
    await sleep(Math.max(0, randRange(cfg.shift_up_delay)));
    await raw.up('Shift');
  }
}

async function interCharDelay(cfg: HumanConfig): Promise<void> {
  await sleep(Math.max(10, keyGap(cfg, 'a', 'b') - randLog(cfg.key_hold)));
}
