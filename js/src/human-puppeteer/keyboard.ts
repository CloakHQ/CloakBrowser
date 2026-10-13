/**
 * cloakbrowser-human — Human-like keyboard input.
 * Adapted for Puppeteer API.
 *
 * Changes from Playwright version:
 *   - Uses puppeteer-core Page/CDPSession types
 *   - keyboard.sendCharacter() mapped via RawKeyboard.insertText adapter
 *   - CDPSession obtained via page.createCDPSession()
 *
 * Stealth-aware: shift symbols use CDP Input.dispatchKeyEvent (isTrusted=true).
 */

import type { Page, CDPSession } from 'puppeteer-core';
import { RawKeyboard } from '../human/mouse.js';
import type { HumanConfig } from '../human/config.js';
import { randRange, sleep } from '../human/config.js';
import { Typist, type TypistKeys } from '../human/keyboard.js';


const NEARBY_KEYS: Record<string, string> = {
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


export async function humanType(
  page: Page,
  raw: RawKeyboard,
  text: string,
  cfg: HumanConfig,
  cdpSession?: CDPSession | null,
): Promise<void> {
  // Same key timeline as the Playwright engine: log-normal holds, rollover,
  // Shift usually released before the letter.
  const keys: TypistKeys = {
    down: (k) => raw.down(k),
    up: (k) => raw.up(k),
    insertText: (t) => raw.insertText(t),
    cdp: async (params) => {
      if (cdpSession) {
        await cdpSession.send('Input.dispatchKeyEvent', params);
      } else if (params.type === 'keyDown') {
        // No CDP session: insert the symbol and fire synthetic key events
        // (detectable via isTrusted=false).
        await raw.insertText(params.key);
        await page.evaluate((key: string) => {
          const el = document.activeElement;
          if (el) {
            el.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }));
            el.dispatchEvent(new KeyboardEvent('keyup', { key, bubbles: true }));
          }
        }, params.key);
      }
    },
  };
  const typist = new Typist(keys, cfg);
  try {
    for (const ch of [...text]) {
      // Mistype
      if (isAscii(ch) && /^[a-zA-Z0-9]$/.test(ch) && Math.random() < cfg.mistype_chance) {
        await typist.key(getNearbyKey(ch));
        await typist.rest();
        await sleep(randRange(cfg.mistype_delay_notice));
        await typist.key('Backspace');
        await typist.rest();
        await sleep(randRange(cfg.mistype_delay_correct));
      }
      await typist.key(ch);
    }
    await typist.finish();
  } finally {
    await typist.releaseAll();
  }
}
