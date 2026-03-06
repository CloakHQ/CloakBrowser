/**
 * cloakbrowser-human — Human-like keyboard input.
 */

import type { Page } from 'playwright-core';
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

function getNearbyKey(ch: string): string {
  const lower = ch.toLowerCase();
  if (lower in NEARBY_KEYS) {
    const neighbors = NEARBY_KEYS[lower];
    const wrong = neighbors[Math.floor(Math.random() * neighbors.length)];
    return ch === ch.toUpperCase() && ch !== ch.toLowerCase() ? wrong.toUpperCase() : wrong;
  }
  return ch;
}

export async function humanType(
  page: Page,
  raw: RawKeyboard,
  text: string,
  cfg: HumanConfig,
): Promise<void> {
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];

    // Mistype chance — press wrong key, notice, backspace, then correct
    if (Math.random() < cfg.mistype_chance && /[a-zA-Z0-9]/.test(ch)) {
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
      await typeShiftSymbol(page, raw, ch, cfg);
    } else {
      await typeNormalChar(raw, ch, cfg);
    }

    if (i < text.length - 1) {
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

async function typeShiftSymbol(page: Page, raw: RawKeyboard, ch: string, cfg: HumanConfig): Promise<void> {
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

function isUpperCase(ch: string): boolean {
  return ch.length === 1 && ch >= 'A' && ch <= 'Z';
}

async function interCharDelay(cfg: HumanConfig): Promise<void> {
  if (Math.random() < cfg.typing_pause_chance) {
    await sleep(randRange(cfg.typing_pause_range));
  } else {
    const delay = cfg.typing_delay + (Math.random() - 0.5) * 2 * cfg.typing_delay_spread;
    await sleep(Math.max(10, delay));
  }
}
