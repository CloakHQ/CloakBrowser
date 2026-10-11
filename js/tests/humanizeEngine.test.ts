/**
 * Behaviour tests for the unified humanize engine (real browser, fast config).
 *
 * These replace the old mock-based tests that asserted on internals of the
 * previous implementation. Every test drives the real CloakBrowser binary
 * headless against a small local test page (js/tests/humanizeHarness.ts) with
 * near-zero delays. Mirrors tests/test_humanize_engine.py.
 *
 * Run with: CLOAKBROWSER_BINARY_PATH=/path/to/chrome npx vitest run tests/humanizeEngine.test.ts
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, it, expect, beforeAll, afterAll, afterEach } from 'vitest';
import type { Browser, Page, Frame } from 'playwright-core';
import { errors } from 'playwright-core';
import { FAST, startServer, events, reset, value } from './humanizeHarness.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));

describe('worldHelpers stays identical to the Python copy', () => {
  it('HELPERS_JS matches cloakbrowser/human/world.py', async () => {
    const { HELPERS_JS } = await import('../src/human/worldHelpers.js');
    const py = fs.readFileSync(path.resolve(HERE, '../../cloakbrowser/human/world.py'), 'utf-8');
    const m = /_HELPERS_JS = r"""([\s\S]*?)"""/.exec(py);
    expect(m).not.toBeNull();
    expect(HELPERS_JS).toBe(m![1]);
  });
});

describe('fields', () => {
  it('classifies like Playwright fill', async () => {
    const f = await import('../src/human/fields.js');
    expect(f.classify('input', 'text', false)).toBe(f.TYPE);
    expect(f.classify('input', 'date', false)).toBe(f.SET);
    expect(f.classify('input', 'checkbox', false)).toBe(f.NOT_FILLABLE);
    expect(f.classify('div', null, true)).toBe(f.TYPE);
    expect(f.allowsMistype('input', 'password')).toBe(false);
    expect(f.validateNumber('12.5')).toBe('12.5');
    expect(f.validateNumber('abc')).toBeNull();
  });

  it('splits date/time values into editor segments', async () => {
    const f = await import('../src/human/fields.js');
    expect(f.datetimeParts('date', '2024-01-31')).toMatchObject({ year: '2024', month: '01', day: '31' });
    const t = f.datetimeParts('time', '13:05')!;
    expect(t).toMatchObject({ hour: '01', hour24: 13, minute: '05' });
    expect(f.use24h(t, false).hour).toBe('13');
    expect(f.datetimeParts('date', '2024-1-31')).toBeNull();
    expect(f.segmentAutoAdvances('year', { year: '2024' })).toBe(false);
    expect(f.segmentAutoAdvances('month', { month: '01' }, 'month')).toBe(false);
    expect(f.segmentAutoAdvances('day', { day: '31' })).toBe(true);
  });
});

describe('InjectedScript source', () => {
  it('is found in the installed playwright-core', async () => {
    const { findInjectedLiteral } = await import('../src/human/injected.js');
    const lit = findInjectedLiteral();
    expect(lit.length).toBeGreaterThan(10_000);
    expect(lit.includes('InjectedScript')).toBe(true);
  });
});

describe.skipIf(!process.env.CLOAKBROWSER_BINARY_PATH)('humanize engine (real browser)', { timeout: 30_000 }, () => {
  let srv: { url: string; close: () => Promise<void> };
  let browser: Browser;
  let page: Page;

  const frame = async (p: Page): Promise<Frame> => {
    const f = p.frame({ name: 'f' })!;
    await f.waitForLoadState();
    return f;
  };

  beforeAll(async () => {
    const { launch } = await import('../src/playwright.js');
    srv = await startServer();
    browser = await launch({ headless: true, humanize: true, humanConfig: FAST as any });
  }, 120_000);

  afterAll(async () => {
    await browser?.close();
    await srv?.close();
  });

  const open = async () => {
    page = await browser.newPage();
    await page.goto(srv.url + 'index.html');
    return page;
  };
  afterEach(async () => { await page?.close().catch(() => {}); });

  // --- wiring -------------------------------------------------------------

  it('humanized reads resolve in the isolated world: correct values, page state untouched', async () => {
    const p: any = await open();
    const dispatched = async () => p.evaluate(() => (window as any).__dispatched.length);
    const before = await dispatched();

    await p.fill('#name', 'laptop');
    const reads = {
      inputValue: await p.inputValue('#name'),
      locatorInputValue: await p.locator('#name').inputValue(),
      handleInputValue: await (await p.$('#name')).inputValue(),
      textContent: await p.textContent('#btn'),
      innerText: await p.innerText('#btn'),
      innerHTML: await p.innerHTML('#btn'),
      getAttribute: await p.getAttribute('#btn', 'id'),
      locatorTextContent: await p.locator('#btn').textContent(),
    };

    expect(reads.inputValue).toBe('laptop');
    expect(reads.locatorInputValue).toBe('laptop');
    expect(reads.handleInputValue).toBe('laptop');
    expect(reads.getAttribute).toBe('btn');
    expect(reads.textContent).toBe(reads.locatorTextContent);
    expect(reads.innerText).toBe(reads.textContent);
    expect(reads.innerHTML).toBe(reads.textContent);
    expect(await dispatched()).toBe(before);
  });

  it('dispatchEvent reaches a page listener with the same event shape', async () => {
    const p: any = await open();
    await p.evaluate(() => {
      (window as any).__clicks = [];
      document.addEventListener('click', (e) => {
        (window as any).__clicks.push({ mouse: e instanceof MouseEvent, bubbles: e.bubbles, x: (e as MouseEvent).clientX });
      });
    });

    await p.dispatchEvent('#btn', 'click', { clientX: 7, clientY: 9 });
    await p.locator('#btn').dispatchEvent('click', { clientX: 3, clientY: 4 });

    const clicks = await p.evaluate(() => (window as any).__clicks);
    expect(clicks).toHaveLength(2);
    expect(clicks[0]).toEqual({ mouse: true, bubbles: true, x: 7 });
  });

  it('handle reads of hidden or same-box elements use the raw path at once', async () => {
    const p: any = await open();
    await p.evaluate(() => {
      document.head.insertAdjacentHTML('beforeend', '<meta name="csrf" content="tok123">');
      document.body.insertAdjacentHTML('beforeend', '<input id="hid" type="hidden" value="secret">'
        + '<div id="outer" style="width:90px;height:30px"><div id="inner" style="width:90px;height:30px"></div></div>');
    });
    const t = Date.now();
    expect(await (await p.$('meta[name="csrf"]')).getAttribute('content')).toBe('tok123');
    expect(await (await p.$('#hid')).inputValue()).toBe('secret');
    expect(Date.now() - t).toBeLessThan(5000);
    // A read must land on the handle's own element, not its same-box wrapper.
    expect(await (await p.$('#inner')).getAttribute('id')).toBe('inner');
    expect(await (await p.$('#outer')).getAttribute('id')).toBe('outer');
  });

  it('dispatchEvent with a JSHandle in eventInit uses the raw path', async () => {
    const p: any = await open();
    await p.evaluate(() => {
      (window as any).__dt = [];
      document.addEventListener('dragstart', (e) => (window as any).__dt.push(e.dataTransfer instanceof DataTransfer));
    });
    const dt = await p.evaluateHandle(() => new DataTransfer());
    await p.dispatchEvent('#btn', 'dragstart', { dataTransfer: dt });
    await p.locator('#btn').dispatchEvent('dragstart', { dataTransfer: dt });
    expect(await p.evaluate(() => (window as any).__dt)).toEqual([true, true]);
  });

  it('a license guard installed on a humanized page does not disable humanize', async () => {
    // The guard stores its wrapper on the page object (it carries this launch's
    // denial path), so the order it is applied in decides which methods it holds.
    // Installed on an already-humanized page it must forward to the human engine.
    const p: any = await open();
    const { installLicenseGuard } = await import('../src/license.js');
    installLicenseGuard(p, '/tmp/denial-compose-test');
    await p.evaluate(() => {
      (window as any).__m = 0;
      document.addEventListener('mousemove', () => { (window as any).__m += 1; }, true);
    });

    await p.click('#btn');

    // A humanized click travels in a curve; Playwright's own click teleports (1-2).
    expect(await p.evaluate(() => (window as any).__m)).toBeGreaterThan(3);
  });

  it('the probe works: the page records events dispatched in its own world', async () => {
    const p: any = await open();
    const before = await p.evaluate(() => (window as any).__dispatched.length);
    await p.evaluate(() => document.getElementById('btn')!.dispatchEvent(new Event('probe')));
    expect(await p.evaluate(() => (window as any).__dispatched.length)).toBe(before + 1);
  });

  it('page is humanized and keeps the compat attributes', async () => {
    const p: any = await open();
    expect(p._humanCfg.mistype_chance).toBe(0);
    expect(await p._stealth.evaluate('1 + 1')).toBe(2);
    await p._original.click('#btn'); // raw Playwright still reachable
  });

  it('a non-humanized page in the same process is untouched', async () => {
    const { launch } = await import('../src/playwright.js');
    const plain = await launch({ headless: true });
    try {
      const p = await plain.newPage();
      await p.goto(srv.url + 'index.html');
      expect((p as any)._original).toBeUndefined();
      await reset(p);
      await p.click('#btn');
      await p.fill('#name', 'plain');
      expect(await value(p, '#name')).toBe('plain');
      // Playwright's own click teleports: no curve of mouse moves.
      expect((await events(p, 'mousemove')).length).toBeLessThan(3);
    } finally {
      await plain.close();
    }
  }, 60_000);

  it('humanized actions leave no side effects in the page (listeners, mutations)', async () => {
    page = await browser.newPage();
    await page.addInitScript(() => {
      const add = EventTarget.prototype.addEventListener;
      const d: any = (window as any).__engine = { listeners: 0, mutations: 0 };
      EventTarget.prototype.addEventListener = function (this: any, t: any, f: any, o: any) {
        if (this === window || this === document) d.listeners++;
        return add.call(this, t, f, o);
      };
      new MutationObserver((m) => { d.mutations += m.length; })
        .observe(document, { subtree: true, childList: true, attributes: true });
    });
    await page.goto(srv.url + 'index.html?nolog');
    // page.$() is Playwright's own query; take the handle first, then measure our actions.
    const handle = (await page.$('#btn'))!;
    await page.evaluate(() => { const d = (window as any).__engine; d.listeners = 0; d.mutations = 0; });
    await page.getByRole('button', { name: 'Press me' }).click();
    await page.locator('#buttons >> #btn').hover();
    await handle.click();
    await page.frameLocator('#frame').locator('#finput').click();
    await expect(page.locator('.dup').click({ timeout: 500 })).rejects.toThrow(/strict mode/);
    const seen = await page.evaluate(() => {
      const d = (window as any).__engine;
      return { listeners: d.listeners, mutations: d.mutations };
    });
    expect(seen).toEqual({ listeners: 0, mutations: 0 });
  });

  // --- pointer actions ------------------------------------------------------

  it('click moves along a curve, then presses', async () => {
    const p = await open();
    await reset(p);
    await p.click('#btn');
    expect((await events(p, 'mousemove')).length).toBeGreaterThanOrEqual(3);
    expect((await events(p, 'click')).map((e) => e.target)).toEqual(['btn']);
  });

  it('click options are honoured', async () => {
    const p = await open();
    await reset(p);
    await p.click('#btn', { button: 'right', modifiers: ['Shift'] });
    const down = (await events(p, 'mousedown')).pop();
    expect([down.button, down.shift]).toEqual([2, true]);
    await reset(p);
    await p.click('#btn', { clickCount: 2 });
    expect((await events(p, 'dblclick')).length).toBe(1);
    await reset(p);
    await p.click('#btn', { trial: true });
    expect(await events(p, 'click')).toEqual([]);
  });

  it('hover does not press; dblclick matches a real double click', async () => {
    const p = await open();
    await reset(p);
    await p.hover('#btn');
    expect(await events(p, 'mousedown')).toEqual([]);
    await reset(p);
    await p.dblclick('#btn');
    const seq = (await events(p, 'mousedown', 'click', 'dblclick')).map((e) => `${e.t}:${e.detail}`).join(' ');
    expect(seq).toBe('mousedown:1 click:1 mousedown:2 click:2 dblclick:2');
  });

  it('hover holds the modifiers while the mouse moves', async () => {
    const p = await open();
    await p.hover('#chk');
    await reset(p);
    await p.hover('#btn', { modifiers: ['Shift'] });
    const seq = await events(p, 'mousemove', 'keydown', 'keyup');
    const moves = seq.filter((e) => e.t === 'mousemove');
    expect(moves.length).toBeGreaterThan(0);
    expect(moves.every((e) => e.shift)).toBe(true);
    expect(seq[0].t).toBe('keydown');
    expect(seq[seq.length - 1].t).toBe('keyup');
    expect(await events(p, 'mousedown')).toEqual([]);
  });

  it('covered element times out with the reason', async () => {
    const p = await open();
    const err = await p.click('#covered', { timeout: 1000 }).catch((e) => e);
    expect(err).toBeInstanceOf(errors.TimeoutError);
    expect(err.message).toMatch(/intercepts pointer events/);
  });

  it('strict mode violation', async () => {
    const p = await open();
    await expect(p.locator('.dup').click({ timeout: 1000 })).rejects.toThrow(/strict mode violation/);
    await p.locator('.dup').first().click();
  });

  it('page default timeout and timeout: 0', async () => {
    const p = await open();
    p.setDefaultTimeout(500);
    const t0 = Date.now();
    await expect(p.click('#missing')).rejects.toBeInstanceOf(errors.TimeoutError);
    expect(Date.now() - t0).toBeLessThan(1500);
    await p.click('#btn', { timeout: 0 });
  });

  it('standard locators', async () => {
    const p = await open();
    await p.getByRole('button', { name: 'Press me' }).click();
    await p.locator('#buttons').locator('#btn').click();
    await p.locator('button').filter({ hasText: 'Press me' }).click();
    await p.click('#btn:visible');
  });

  // --- keyboard -------------------------------------------------------------

  it('fill replaces, pressSequentially appends, clear empties', async () => {
    const p = await open();
    await p.fill('#name', 'Shaho');
    expect(await value(p, '#name')).toBe('Shaho');
    await p.locator('#name').pressSequentially('!');
    expect(await value(p, '#name')).toBe('Shaho!');
    await p.locator('#name').clear();
    expect(await value(p, '#name')).toBe('');
  });

  it('value inputs are operated like a person (trusted events only)', async () => {
    const p = await open();
    await p.evaluate(() => {
      (window as any).__untrusted = 0;
      for (const t of ['input', 'change']) {
        document.addEventListener(t, (e) => { if (!e.isTrusted) (window as any).__untrusted++; }, true);
      }
    });
    await p.fill('#date', '2024-01-31');
    await p.fill('#date', '1999-12-05');
    await p.fill('#range', '80');
    expect(await p.selectOption('#sel', 'b')).toEqual(['b']);
    expect([await value(p, '#date'), await value(p, '#range'), await value(p, '#sel')]).toEqual(['1999-12-05', '80', 'b']);
    expect(await p.evaluate(() => (window as any).__untrusted)).toBe(0);
    await expect(p.fill('#color', '#ff0000')).rejects.toThrow(/native colour picker/);
    await expect(p.fill('#chk', 'x')).rejects.toThrow(/cannot be filled/);
  }, 60_000);

  it('unreachable element is not focused programmatically', async () => {
    const p = await open();
    const err = await p.fill('#neg', 'x', { timeout: 1500 }).catch((e) => e);
    expect(err).toBeInstanceOf(errors.TimeoutError);
    expect(err.message).toMatch(/outside of the viewport/);
    expect(await value(p, '#neg')).toBe('');
  });

  it('press focuses its target first and forwards delay', async () => {
    const p = await open();
    await p.focus('#fa');
    await (await p.$('#fb'))!.press('x');
    expect([await value(p, '#fa'), await value(p, '#fb')]).toEqual(['', 'x']);
    await reset(p);
    await p.press('#name', 'a', { delay: 150 });
    const ev = await events(p, 'keydown', 'keyup');
    expect(ev[ev.length - 1].ts - ev[ev.length - 2].ts).toBeGreaterThanOrEqual(120);
  });

  it('press / type reach non-focusable targets (canvas, document key handlers)', async () => {
    const p = await open();
    await p.evaluate(() => { (window as any).__keys = []; document.addEventListener('keydown', (e) => (window as any).__keys.push(e.key)); });
    await p.press('#cv', 'ArrowUp');
    await p.locator('#cv').pressSequentially('ab');
    expect(await p.evaluate(() => (window as any).__keys)).toEqual(['ArrowUp', 'a', 'b']);
  });

  it('mistypes are corrected, skip masked fields, uppercase uses Shift', async () => {
    const p = await open();
    const typo = { human_config: { mistype_chance: 1 } } as any;
    await p.fill('#name', 'Hello', typo);
    expect(await value(p, '#name')).toBe('Hello');
    await p.fill('#hex', 'ab', typo);
    expect(await value(p, '#hex')).toBe('ab');
    await reset(p);
    await p.locator('#name').pressSequentially('AB', typo);
    const bad = (await events(p, 'keydown')).filter((e) => /^[A-Z]$/.test(e.key) && !e.shift);
    expect(bad).toEqual([]);
  });

  it('scroll overshoot wheels past the target and back', async () => {
    const p = await open();
    await p.setViewportSize({ width: 800, height: 300 });
    await reset(p);
    await p.click('#chk', { human_config: { scroll_overshoot_chance: 1, scroll_overshoot_px: [120, 120] } });
    const dys = (await events(p, 'wheel')).map((e) => e.dy);
    expect(dys.some((d) => d > 0) && dys.some((d) => d < 0)).toBe(true);
    expect((await events(p, 'click')).map((e) => e.target)).toEqual(['chk']);
    await reset(p);
    await p.evaluate(() => scrollTo(0, 0));
    await p.click('#chk', { human_config: { scroll_overshoot_chance: 0 } });
    expect((await events(p, 'wheel')).every((e) => e.dy > 0)).toBe(true);
  });

  it('per-call human_config and flat config keys', async () => {
    const p = await open();
    const hold = async (o: any) => {
      await reset(p);
      await p.click('#btn', o);
      const up = (await events(p, 'mouseup')).pop(), down = (await events(p, 'mousedown')).pop();
      return up.ts - down.ts;
    };
    expect(await hold({ human_config: { click_hold_button: [300, 300] } })).toBeGreaterThanOrEqual(250);
    expect(await hold({ click_hold_button: [300, 300] })).toBeGreaterThanOrEqual(250);
  });

  // --- checkable / select ---------------------------------------------------

  it('check, uncheck, setChecked, selectOption by index', async () => {
    const p = await open();
    await p.check('#chk');
    expect(await p.isChecked('#chk')).toBe(true);
    await p.locator('#chk').uncheck();
    expect(await p.isChecked('#chk')).toBe(false);
    await (await p.$('#chk'))!.setChecked(true);
    expect(await p.isChecked('#chk')).toBe(true);
    expect(await p.selectOption('#sel', { index: 1 })).toEqual(['b']);
  });

  it('selectOption on a long dropdown types ahead instead of walking every row (#581)', async () => {
    const p = await open();
    await p.evaluate(() => {
      const s = document.createElement('select'); s.id = 'long';
      for (let i = 0; i < 205; i++) s.add(new Option('Country ' + String(i).padStart(3, '0'), 'v' + i));
      (window as any).__sel = [];
      for (const t of ['input', 'change']) s.addEventListener(t, () => (window as any).__sel.push(t));
      document.body.append(s);
    });
    await reset(p);
    expect(await p.selectOption('#long', 'v150')).toEqual(['v150']);
    const keys = (await events(p, 'keydown')).map((e) => e.key);
    expect(keys).not.toContain('ArrowDown');
    expect(keys.length).toBeLessThanOrEqual(13);
    const sel: string[] = await p.evaluate(() => (window as any).__sel);
    // A macOS dropdown moves on every typed letter (one input/change each); elsewhere only Enter commits.
    expect(sel.slice(-2)).toEqual(['input', 'change']);
    if (process.platform !== 'darwin') expect(sel).toHaveLength(2);
    await p.evaluate(() => { (document.querySelector('#long') as HTMLSelectElement).selectedIndex = 0; });
    const e = await p.selectOption('#long', 'v200', { timeout: 200 }).catch((x) => x);
    expect(e).toBeInstanceOf(errors.TimeoutError);
  });

  it('selectOption on emoji labels uses arrows, and refuses on macOS', async () => {
    // Blink's type-ahead drops a typed emoji; a macOS popup ignores arrows.
    const p = await open();
    await p.evaluate(() => {
      const s = document.createElement('select'); s.id = 'emoji';
      for (const [l, v] of [['Pick one', ''], ['🍎 Apple', 'a'], ['🍌 Banana', 'b'], ['🍒 Cherry', 'c']]) s.add(new Option(l, v));
      document.body.append(s);
    });
    if (process.platform === 'darwin') {
      await expect(p.selectOption('#emoji', 'c')).rejects.toThrow(/cannot be picked with human input/);
    } else {
      expect(await p.selectOption('#emoji', 'c')).toEqual(['c']);
    }
  });

  // --- frames and handles ---------------------------------------------------

  it('frame actions', async () => {
    const p = await open();
    const f = await frame(p);
    await f.fill('#finput', 'in frame');
    expect(await value(f, '#finput')).toBe('in frame');
    await p.frameLocator('#frame').locator('#finput').pressSequentially('!');
    expect(await value(f, '#finput')).toBe('in frame!');
    await reset(f);
    await f.click('#fbottom', { timeout: 5000 });
    expect((await events(f, 'click')).map((e) => e.target)).toEqual(['fbottom']);
    // The frame was scrolled to its bottom above; wheeling back up takes time.
    await expect(f.click('#fcovered', { timeout: 4000 })).rejects.toThrow(/intercepts pointer events/);
  }, 60_000);

  it('element handle actions', async () => {
    const p = await open();
    await (await p.$('#name'))!.fill('handle');
    expect(await value(p, '#name')).toBe('handle');
    await reset(p);
    await (await p.$('#btn'))!.click();
    expect((await events(p, 'click')).map((e) => e.target)).toEqual(['btn']);
  });

  it('mouse API', async () => {
    const p = await open();
    await reset(p);
    await p.mouse.move(50, 50, { steps: 1 });
    expect((await events(p, 'mousemove')).length).toBe(1);
    const box = (await p.locator('#btn').boundingBox())!;
    await reset(p);
    await p.mouse.click(box.x + 5, box.y + 5, { button: 'right' });
    expect((await events(p, 'mousedown')).map((e) => e.button)).toEqual([2]);
  });

  it('select-all follows the persona, not the host OS', async () => {
    const { launch } = await import('../src/playwright.js');
    const mac = await launch({ headless: true, humanize: true, humanConfig: FAST as any, args: ['--fingerprint-platform=macos'] });
    try {
      const p = await mac.newPage();
      await p.goto(srv.url + 'index.html');
      expect(await p.evaluate(() => navigator.platform)).toBe('MacIntel');
      await p.fill('#name', 'old');
      await p.fill('#name', 'Mac');
      expect(await value(p, '#name')).toBe('Mac');
    } finally {
      await mac.close();
    }
  }, 60_000);
});
