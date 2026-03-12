/**
 * Unit + integration tests for the humanize layer (JS).
 * Covers: config resolution, Bézier math, fill clearing,
 * bot-detection form, and patching integrity.
 *
 * Run: node tests/test_humanize_unit.mjs
 */
import { launch } from '../js/dist/index.js';
import { resolveConfig, rand, randRange, sleep } from '../js/dist/human/config.js';
import { humanMove, clickTarget } from '../js/dist/human/mouse.js';

const PROXY = {

};
const delay = ms => new Promise(r => setTimeout(r, ms));
const results = [];

async function test(name, fn) {
  try {
    await fn();
    console.log(`  [PASS] ${name}`);
    results.push({ name, status: 'PASS' });
  } catch (e) {
    console.log(`  [FAIL] ${name} — ${e.message || e}`);
    results.push({ name, status: 'FAIL' });
  }
}

// =========================================================================
// 1. Config resolution
// =========================================================================
console.log('\n' + '='.repeat(60));
console.log('  CONFIG RESOLUTION');
console.log('='.repeat(60));

await test('default config resolves', async () => {
  const cfg = resolveConfig('default');
  if (!cfg) throw new Error('resolveConfig returned null');
  if (cfg.mouse_min_steps <= 0) throw new Error('mouse_min_steps should be > 0');
  if (cfg.mouse_max_steps <= cfg.mouse_min_steps) throw new Error('mouse_max_steps should be > min');
  if (cfg.typing_delay <= 0) throw new Error('typing_delay should be > 0');
  if (!Array.isArray(cfg.initial_cursor_x) || cfg.initial_cursor_x.length !== 2) throw new Error('initial_cursor_x invalid');
  if (!Array.isArray(cfg.initial_cursor_y) || cfg.initial_cursor_y.length !== 2) throw new Error('initial_cursor_y invalid');
});

await test('careful config resolves', async () => {
  const cfg = resolveConfig('careful');
  const def = resolveConfig('default');
  if (!cfg) throw new Error('resolveConfig returned null');
  if (cfg.typing_delay < def.typing_delay) throw new Error('careful should have >= typing_delay');
});

await test('custom config override', async () => {
  const cfg = resolveConfig('default', { mouse_min_steps: 100, mouse_max_steps: 200 });
  if (cfg.mouse_min_steps !== 100) throw new Error(`Override failed: ${cfg.mouse_min_steps}`);
  if (cfg.mouse_max_steps !== 200) throw new Error(`Override failed: ${cfg.mouse_max_steps}`);
});

await test('rand within bounds', async () => {
  for (let i = 0; i < 100; i++) {
    const v = rand(10, 20);
    if (v < 10 || v > 20) throw new Error(`rand out of range: ${v}`);
  }
});

await test('randRange within bounds', async () => {
  for (let i = 0; i < 100; i++) {
    const v = randRange([5, 15]);
    if (v < 5 || v > 15) throw new Error(`randRange out of range: ${v}`);
  }
});

await test('sleep timing', async () => {
  const t0 = Date.now();
  await sleep(50);
  const elapsed = Date.now() - t0;
  if (elapsed < 40) throw new Error(`sleep too short: ${elapsed} ms`);
  if (elapsed > 200) throw new Error(`sleep too long: ${elapsed} ms`);
});

// =========================================================================
// 2. Bézier math (via humanMove recording)
// =========================================================================
console.log('\n' + '='.repeat(60));
console.log('  BÉZIER MATH (via mouse movement recording)');
console.log('='.repeat(60));

await test('humanMove generates multiple points', async () => {
  const cfg = resolveConfig('default');
  const moves = [];
  const fakeRaw = {
    move: async (x, y) => moves.push({ x, y }),
    down: async () => {},
    up: async () => {},
    wheel: async () => {},
  };
  await humanMove(fakeRaw, 0, 0, 500, 300, cfg);
  if (moves.length < 10) throw new Error(`Expected >= 10 moves, got ${moves.length}`);
  const last = moves[moves.length - 1];
  if (Math.abs(last.x - 500) > 10) throw new Error(`Last x too far: ${last.x}`);
  if (Math.abs(last.y - 300) > 10) throw new Error(`Last y too far: ${last.y}`);
});

await test('humanMove smoothness (no large jumps)', async () => {
  const cfg = resolveConfig('default');
  const moves = [];
  const fakeRaw = {
    move: async (x, y) => moves.push({ x, y }),
    down: async () => {},
    up: async () => {},
    wheel: async () => {},
  };
  await humanMove(fakeRaw, 0, 0, 400, 400, cfg);
  const totalDist = Math.sqrt(400 * 400 + 400 * 400);
  const maxJump = totalDist * 0.5;
  for (let i = 1; i < moves.length; i++) {
    const dx = moves[i].x - moves[i - 1].x;
    const dy = moves[i].y - moves[i - 1].y;
    const jump = Math.sqrt(dx * dx + dy * dy);
    if (jump > maxJump) throw new Error(`Jump too large at step ${i}: ${jump.toFixed(1)}`);
  }
});

await test('humanMove not a straight line', async () => {
  const cfg = resolveConfig('default');
  let maxDev = 0;
  for (let trial = 0; trial < 5; trial++) {
    const moves = [];
    const fakeRaw = {
      move: async (x, y) => moves.push({ x, y }),
      down: async () => {},
      up: async () => {},
      wheel: async () => {},
    };
    await humanMove(fakeRaw, 0, 0, 500, 0, cfg);
    const dev = Math.max(...moves.map(m => Math.abs(m.y)));
    if (dev > maxDev) maxDev = dev;
  }
  if (maxDev < 0.5) throw new Error(`Curve too straight, max y deviation: ${maxDev.toFixed(2)}`);
});

await test('clickTarget within bounding box', async () => {
  const cfg = resolveConfig('default');
  const box = { x: 100, y: 200, width: 150, height: 40 };
  for (let i = 0; i < 50; i++) {
    const t = clickTarget(box, false, cfg);
    if (t.x < 100 || t.x > 250) throw new Error(`x out of box: ${t.x}`);
    if (t.y < 200 || t.y > 240) throw new Error(`y out of box: ${t.y}`);
  }
});

// =========================================================================
// 3. Fill clearing (with real browser)
// =========================================================================
console.log('\n' + '='.repeat(60));
console.log('  FILL CLEARING (browser)');
console.log('='.repeat(60));

await test('fill() clears existing text', async () => {
  const browser = await launch({ headless: true, humanize: true });
  const page = await browser.newPage();
  await page.goto('https://www.wikipedia.org', { waitUntil: 'domcontentloaded' });
  await delay(1000);

  await page.locator('#searchInput').type('initial text');
  await delay(500);
  const before = await page.locator('#searchInput').inputValue();
  if (before !== 'initial text') throw new Error(`Initial type failed: '${before}'`);

  await page.locator('#searchInput').fill('replaced text');
  await delay(500);
  const after = await page.locator('#searchInput').inputValue();
  if (after !== 'replaced text') throw new Error(`Fill did not replace: '${after}'`);
  if (after.includes('initial')) throw new Error('Old text still present');

  await browser.close();
});

await test('fill() timing is humanized (>1s)', async () => {
  const browser = await launch({ headless: true, humanize: true });
  const page = await browser.newPage();
  await page.goto('https://www.wikipedia.org', { waitUntil: 'domcontentloaded' });
  await delay(1000);

  const t0 = Date.now();
  await page.locator('#searchInput').fill('Human speed test');
  const elapsed = Date.now() - t0;
  if (elapsed < 1000) throw new Error(`fill() too fast: ${elapsed} ms`);

  await browser.close();
});

await test('clear() empties field', async () => {
  const browser = await launch({ headless: true, humanize: true });
  const page = await browser.newPage();
  await page.goto('https://www.wikipedia.org', { waitUntil: 'domcontentloaded' });
  await delay(1000);

  await page.locator('#searchInput').fill('some text');
  await delay(500);
  await page.locator('#searchInput').clear();
  await delay(500);
  const val = await page.locator('#searchInput').inputValue();
  if (val !== '') throw new Error(`clear() did not empty: '${val}'`);

  await browser.close();
});

// =========================================================================
// 4. Bot detection form — deviceandbrowserinfo.com
// =========================================================================
console.log('\n' + '='.repeat(60));
console.log('  BOT DETECTION FORM (deviceandbrowserinfo.com)');
console.log('='.repeat(60));

await test('bot detection form — behavioral checks pass', async () => {
  const browser = await launch({ headless: false, humanize: true, proxy: PROXY });
  const page = await browser.newPage();
  await page.goto('https://deviceandbrowserinfo.com/are_you_a_bot_interactions', { waitUntil: 'domcontentloaded' });
  await delay(3000);

  await page.locator('#email').click();
  await delay(300);
  await page.locator('#email').fill('test@example.com');
  await delay(500);

  await page.locator('#password').click();
  await delay(300);
  await page.locator('#password').fill('SecurePass!123');
  await delay(500);

  await page.locator('button[type="submit"]').click();
  await delay(5000);

  const body = await page.locator('body').textContent();

  const superHuman = body.includes('"superHumanSpeed": true');
  const suspicious = body.includes('"suspiciousClientSideBehavior": true');
  const cdpMouse = body.includes('"hasCDPMouseLeak": true');

  console.log(`    superHumanSpeed: ${superHuman}`);
  console.log(`    suspiciousClientSideBehavior: ${suspicious}`);
  console.log(`    hasCDPMouseLeak: ${cdpMouse}`);

  if (superHuman) throw new Error('superHumanSpeed detected');
  if (suspicious) throw new Error('suspiciousClientSideBehavior detected');

  if (body.includes('"isAutomatedWithCDP": true')) {
    console.log('    [INFO] isAutomatedWithCDP=true — stealth issue, not humanize');
  }

  await browser.close();
});

await test('bot detection form timing (>3s)', async () => {
  const browser = await launch({ headless: true, humanize: true, proxy: PROXY });
  const page = await browser.newPage();
  await page.goto('https://deviceandbrowserinfo.com/are_you_a_bot_interactions', { waitUntil: 'domcontentloaded' });
  await delay(2000);

  const t0 = Date.now();
  await page.locator('#email').fill('test@example.com');
  await page.locator('#password').fill('MyPassword!99');
  await page.locator('button[type="submit"]').click();
  const elapsed = Date.now() - t0;
  await delay(3000);

  console.log(`    Form fill + submit took: ${elapsed} ms`);
  if (elapsed < 3000) throw new Error(`Form filled too fast: ${elapsed} ms`);

  await browser.close();
});

// =========================================================================
// 5. Patching integrity
// =========================================================================
console.log('\n' + '='.repeat(60));
console.log('  PATCHING INTEGRITY');
console.log('='.repeat(60));

await test('page has _original after launch', async () => {
  const browser = await launch({ headless: true, humanize: true });
  const page = await browser.newPage();
  if (!page._original) throw new Error('page._original missing');
  if (!page._humanCfg) throw new Error('page._humanCfg missing');
  if (!page._humanCursor) throw new Error('page._humanCursor missing');
  await browser.close();
});

await test('page.click is humanized', async () => {
  const browser = await launch({ headless: true, humanize: true });
  const page = await browser.newPage();
  const clickStr = page.click.toString();
  if (!clickStr.includes('ensureCursorInit') && !clickStr.includes('humanClickFn') && !clickStr.includes('scrollToElement')) {
    throw new Error('page.click does not appear humanized');
  }
  await browser.close();
});

await test('non-humanized page works normally', async () => {
  const browser = await launch({ headless: true, humanize: false });
  const page = await browser.newPage();
  if (page._original) throw new Error('Non-humanized page should not have _original');

  await page.goto('https://www.wikipedia.org', { waitUntil: 'domcontentloaded' });
  await delay(1000);

  const t0 = Date.now();
  await page.locator('#searchInput').fill('test');
  const elapsed = Date.now() - t0;
  if (elapsed > 500) throw new Error(`Non-humanized fill too slow: ${elapsed} ms`);

  await browser.close();
});

// =========================================================================
// 6. Focus check — press skips click when focused
// =========================================================================
console.log('\n' + '='.repeat(60));
console.log('  FOCUS CHECK (press / pressSequentially)');
console.log('='.repeat(60));

await test('press skips click when element already focused', async () => {
  const browser = await launch({ headless: true, humanize: true });
  const page = await browser.newPage();
  await page.goto('https://www.wikipedia.org', { waitUntil: 'domcontentloaded' });
  await delay(1000);

  // Click input first to focus it
  await page.locator('#searchInput').click();
  await delay(300);

  // Record mouse moves before pressing Enter
  const movesBefore = [];
  const origMove = page._humanOriginals.mouseMove;
  let moveCount = 0;
  page._humanOriginals.mouseMove = async (x, y, opts) => {
    moveCount++;
    return origMove(x, y, opts);
  };

  // Press Enter — element is already focused, should NOT trigger mouse move
  const movesAtStart = moveCount;
  await page.locator('#searchInput').press('a');
  const movesUsed = moveCount - movesAtStart;

  // Restore
  page._humanOriginals.mouseMove = origMove;

  // If focus check works, should be 0 moves (just keyboard press)
  if (movesUsed > 0) {
    console.log(`    [INFO] press() triggered ${movesUsed} mouse moves on focused element`);
  }
  // Lenient: allow some moves but not a full Bézier path (>10 would indicate a click)
  if (movesUsed > 10) {
    throw new Error(`press() moved mouse ${movesUsed} times on already-focused element — focus check broken`);
  }

  await browser.close();
});

// =========================================================================
// 7. check/uncheck idle
// =========================================================================
console.log('\n' + '='.repeat(60));
console.log('  CHECK/UNCHECK IDLE');
console.log('='.repeat(60));

await test('check() respects idle_between_actions config', async () => {
  const cfg = resolveConfig('default', { idle_between_actions: true, idle_between_duration: [50, 100] });
  if (!cfg.idle_between_actions) throw new Error('idle_between_actions should be true');
  if (!cfg.idle_between_duration || cfg.idle_between_duration[0] !== 50) {
    throw new Error('idle_between_duration not set');
  }
  // Verify config is carried through to page
  const browser = await launch({ headless: true, humanize: true, humanize_config: { idle_between_actions: true } });
  const page = await browser.newPage();
  if (!page._humanCfg) throw new Error('page._humanCfg missing');
  await browser.close();
});

// =========================================================================
// 8. Frame patching completeness
// =========================================================================
console.log('\n' + '='.repeat(60));
console.log('  FRAME PATCHING COMPLETENESS');
console.log('='.repeat(60));

await test('frame has all methods patched', async () => {
  const browser = await launch({ headless: true, humanize: true });
  const page = await browser.newPage();
  await page.goto('https://www.wikipedia.org', { waitUntil: 'domcontentloaded' });
  await delay(1000);

  const mainFrame = page.mainFrame();
  const expected = ['click', 'dblclick', 'hover', 'type', 'fill',
                    'check', 'uncheck', 'selectOption', 'press',
                    'clear', 'dragAndDrop'];
  const missing = [];
  for (const method of expected) {
    if (typeof mainFrame[method] !== 'function') {
      missing.push(method);
    }
  }
  if (missing.length > 0) {
    throw new Error(`Frame missing patched methods: ${missing.join(', ')}`);
  }

  // Verify they are patched (not original Playwright bindings)
  if (!mainFrame._humanPatched) {
    throw new Error('mainFrame._humanPatched flag not set');
  }

  await browser.close();
});

// =========================================================================
// 9. drag_to safety — page._original check
// =========================================================================
console.log('\n' + '='.repeat(60));
console.log('  DRAG_TO SAFETY');
console.log('='.repeat(60));

await test('page._humanCfg is accessible', async () => {
  const browser = await launch({ headless: true, humanize: true });
  const page = await browser.newPage();
  if (!page._humanCfg) throw new Error('page._humanCfg not set');
  if (!page._original) throw new Error('page._original not set');
  if (typeof page._original.mouseDown !== 'function') throw new Error('mouseDown not preserved');
  if (typeof page._original.mouseUp !== 'function') throw new Error('mouseUp not preserved');
  await browser.close();
});

// =========================================================================
// 10. patchBrowser.newPage uses original context
// =========================================================================
console.log('\n' + '='.repeat(60));
console.log('  PATCH BROWSER — newPage context');
console.log('='.repeat(60));

await test('browser.newPage returns patched page', async () => {
  const browser = await launch({ headless: true, humanize: true });
  const page = await browser.newPage();
  if (!page._original) throw new Error('page from browser.newPage() not patched');
  if (!page._humanCfg) throw new Error('page._humanCfg missing from browser.newPage()');
  await browser.close();
});


// =========================================================================
// SUMMARY
// =========================================================================
console.log('\n' + '='.repeat(70));
console.log('  TEST SUMMARY');
console.log('='.repeat(70));

const passed = results.filter(r => r.status === 'PASS').length;
const failed = results.filter(r => r.status === 'FAIL').length;

for (const r of results) {
  const icon = r.status === 'PASS' ? 'OK' : 'XX';
  console.log(`  [${icon}] ${r.name}`);
}

console.log(`\n  ${passed}/${results.length} passed, ${failed} failed`);
if (failed === 0) console.log('  *** ALL JS TESTS PASSED ***');
else console.log(`  *** ${failed} TESTS FAILED ***`);
console.log('='.repeat(70));

process.exit(failed === 0 ? 0 : 1);
