/**
 * Real-browser behaviour tests for the Puppeteer humanize wrapper.
 *
 * Drives the CloakBrowser binary headless against the test page in humanizeHarness.ts with
 * near-zero delays. Skipped unless CLOAKBROWSER_BINARY_PATH is set.
 */

import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest';
import type { Browser, Page } from 'puppeteer-core';
import { launch } from '../src/puppeteer.js';
import { FAST, startServer, events, reset, value } from './humanizeHarness.js';

describe.skipIf(!process.env.CLOAKBROWSER_BINARY_PATH)('humanize: Puppeteer (real browser)', { timeout: 30_000 }, () => {
  let srv: { url: string; close: () => Promise<void> };
  let browser: Browser;
  const pages: Page[] = [];

  const open = async (b: Browser = browser): Promise<Page> => {
    const page = await b.newPage();
    pages.push(page);
    await page.setViewport({ width: 1280, height: 720 });
    await page.goto(srv.url + 'index.html');
    return page;
  };
  const frameOf = async (page: Page) => {
    const f = page.frames().find((x) => x.name() === 'f')!;
    await f.waitForSelector('#finput');
    return f;
  };

  beforeAll(async () => {
    srv = await startServer();
    browser = await launch({ headless: true, humanize: true, humanConfig: FAST as any });
  }, 120_000);

  afterEach(async () => {
    for (const p of pages.splice(0)) await p.close().catch(() => {});
  });

  afterAll(async () => {
    await browser?.close();
    await srv?.close();
  });

  it("click({ button: 'right' }) and mouse.click({ button: 'right' })", async () => {
    const page = await open();
    await reset(page);
    await page.click('#btn', { button: 'right' });
    const b = (await (await page.$('#btn'))!.boundingBox())!;
    await page.mouse.click(b.x + 5, b.y + 5, { button: 'right' });
    expect((await events(page, 'mousedown')).map((e) => e.button)).toEqual([2, 2]);
    expect((await events(page, 'contextmenu')).length).toBe(2);
  });

  it('click({ count: 2 }) is a real double click (detail 1, 2)', async () => {
    const page = await open();
    await reset(page);
    await page.click('#btn', { count: 2 } as any);
    const seq = (await events(page, 'mousedown', 'click', 'dblclick')).map((e) => `${e.t}:${e.detail}`).join(' ');
    expect(seq).toBe('mousedown:1 click:1 mousedown:2 click:2 dblclick:2');
  });

  it('frame.click / type / hover resolve inside the frame (#184)', async () => {
    // Tall viewport: the frame input is already in view, so no wheel scroll can
    // land over the iframe (known gap: Puppeteer's scroll may wheel the iframe).
    const page = await open();
    await page.setViewport({ width: 1280, height: 1400 });
    const f = await frameOf(page);
    await reset(f);
    await f.click('#finput');
    expect((await events(f, 'click')).map((e) => e.target)).toEqual(['finput']);
    // Puppeteer's type() leaves the caret where the click landed, so start empty.
    await f.evaluate(() => { (document.querySelector('#finput') as HTMLInputElement).value = ''; });
    await f.type('#finput', 'abc');
    expect(await value(f, '#finput')).toBe('abc');
    await reset(f);
    await f.hover('#finput');
    expect((await events(f, 'mousemove')).length).toBeGreaterThan(0);
  });

  it('same key lower then upper case never sends a repeat keydown ("xX", "1!")', async () => {
    const b = await launch({
      headless: true, humanize: true,
      humanConfig: {
        ...FAST, key_hold: [60, 175], typing_delay: 150, typing_delay_spread: 70, typing_pause_chance: 0,
        shift_down_delay: [60, 220], shift_up_delay: [-60, 30],
      } as any,
    });
    try {
      const page = await open(b);
      await page.evaluate(() => {
        (window as any).__kd = [];
        for (const t of ['keydown', 'keyup'])
          document.addEventListener(t, (e: any) => (window as any).__kd.push([t, e.code, e.repeat]), true);
      });
      const text = 'xX aA zZ 1! qQ';
      for (let i = 0; i < 3; i++) {
        await page.evaluate(() => { (document.querySelector('#name') as HTMLInputElement).value = ''; });
        await page.type('#name', text);
        expect(await value(page, '#name')).toBe(text);
      }
      const log: [string, string, boolean][] = await page.evaluate(() => (window as any).__kd);
      expect(log.filter(e => e[2])).toEqual([]);
    } finally {
      await b.close();
    }
  }, 90_000);

  it('uppercase typos are typed with Shift', async () => {
    const b = await launch({ headless: true, humanize: true, humanConfig: { ...FAST, mistype_chance: 1 } as any });
    try {
      const page = await open(b);
      await page.evaluate(() => { (document.querySelector('#name') as HTMLInputElement).value = ''; });
      await reset(page);
      await page.type('#name', 'AB');
      const unshifted = (await events(page, 'keydown'))
        .filter((e) => e.key.length === 1 && /[A-Z]/.test(e.key) && !e.shift).map((e) => e.key);
      expect(unshifted).toEqual([]);
      expect(await value(page, '#name')).toBe('AB');
    } finally {
      await b.close();
    }
  }, 60_000);
});
