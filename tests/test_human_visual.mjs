// test_human_visual.mjs
/**
 * Visual + functional test for humanize (JS).
 * Red dot = cursor, yellow = mouse held.
 * Trail dots show the path taken.
 */
import { launch } from '../js/dist/index.js';

const CURSOR_JS = `
(() => {
    if (document.getElementById('__hc')) return;
    const el = document.createElement('div');
    el.id = '__hc';
    el.style.cssText = 'width:14px;height:14px;background:red;border:2px solid darkred;border-radius:50%;position:fixed;z-index:2147483647;pointer-events:none;display:none;transition:background 0.05s;';
    document.body.appendChild(el);

    const trail = document.createElement('div');
    trail.id = '__hcTrail';
    trail.style.cssText = 'position:fixed;top:0;left:0;width:100%;height:100%;z-index:2147483646;pointer-events:none;overflow:hidden;';
    document.body.appendChild(trail);

    let dotCount = 0;
    const maxDots = 500;

    function updatePos(x, y) {
        el.style.display = 'block';
        el.style.left = (x - 9) + 'px';
        el.style.top = (y - 9) + 'px';
        if (dotCount < maxDots) {
            const dot = document.createElement('div');
            dot.style.cssText = 'width:3px;height:3px;background:rgba(255,0,0,0.3);border-radius:50%;position:fixed;pointer-events:none;left:'+(x-1)+'px;top:'+(y-1)+'px;';
            trail.appendChild(dot);
            dotCount++;
        }
    }

    document.addEventListener('mousemove', e => updatePos(e.clientX, e.clientY));
    document.addEventListener('drag', e => { if (e.clientX > 0) updatePos(e.clientX, e.clientY); });
    document.addEventListener('dragover', e => { if (e.clientX > 0) updatePos(e.clientX, e.clientY); });
    document.addEventListener('mousedown', () => { el.style.background = 'yellow'; });
    document.addEventListener('mouseup', () => { el.style.background = 'red'; });
    document.addEventListener('dragend', () => { el.style.background = 'red'; });
})();
`;

const results = [];
const delay = ms => new Promise(r => setTimeout(r, ms));

async function inject(page) {
  try { await page.evaluate(CURSOR_JS); } catch {}
  await delay(300);
}

function step(name) {
  console.log(`\n${'='.repeat(60)}`);
  console.log(`  STEP: ${name}`);
  console.log('='.repeat(60));
}

function check(name, passed, detail = '') {
  const status = passed ? 'PASS' : 'FAIL';
  let msg = `  [${status}] ${name}`;
  if (detail) msg += ` — ${detail}`;
  console.log(msg);
  results.push({ name, status });
}

async function main() {
  console.log('='.repeat(70));
  console.log('  HUMAN-LIKE BEHAVIOR VISUAL TEST (JS)');
  console.log('  Watch the red dot — it should move smoothly like a real cursor');
  console.log('='.repeat(70));

  const browser = await launch({
    headless: false,
    humanize: true,
  });
  const page = await browser.newPage();

  // ============================================================
  // SCENARIO 1: Wikipedia search
  // ============================================================
  step('Wikipedia — navigate and search');
  await page.goto('https://www.wikipedia.org', { waitUntil: 'domcontentloaded' });
  await delay(2000);
  await inject(page);
  await delay(1000);

  console.log('  Watch: cursor moves to search box (Bezier curve)');
  let t0 = Date.now();
  await page.locator('#searchInput').click();
  let ms = Date.now() - t0;
  check('click on search input', ms > 200, `${ms} ms`);
  await delay(500);

  console.log('  Watch: characters appear one by one');
  t0 = Date.now();
  await page.locator('#searchInput').fill('Python programming language');
  ms = Date.now() - t0;
  let val = await page.locator('#searchInput').inputValue();
  check('fill search box', val === 'Python programming language' && ms > 2000, `${ms} ms, value='${val}'`);
  await delay(500);

  console.log('  Watch: double click selects word');
  t0 = Date.now();
  await page.locator('#searchInput').dblclick();
  ms = Date.now() - t0;
  let sel = await page.evaluate(() => window.getSelection().toString().trim());
  check('dblclick selects word', sel.length > 0 && ms > 200, `${ms} ms, selected='${sel}'`);
  await delay(500);

  console.log('  Watch: old text replaced');
  t0 = Date.now();
  await page.locator('#searchInput').fill('Artificial intelligence');
  ms = Date.now() - t0;
  val = await page.locator('#searchInput').inputValue();
  check('fill replaces text', val === 'Artificial intelligence' && ms > 1500, `${ms} ms, value='${val}'`);
  await delay(500);

  console.log('  Watch: cursor hovers button without clicking');
  t0 = Date.now();
  await page.locator('button[type="submit"]').hover();
  ms = Date.now() - t0;
  check('hover search button', ms > 100, `${ms} ms`);
  await delay(1000);

  // ============================================================
  // SCENARIO 2: Checkboxes
  // ============================================================
  step('Checkboxes — check and uncheck');
  await page.goto('https://the-internet.herokuapp.com/checkboxes', { waitUntil: 'domcontentloaded' });
  await delay(2000);
  await inject(page);
  await delay(1000);

  const cb1 = page.locator('input[type="checkbox"]').nth(0);
  const cb2 = page.locator('input[type="checkbox"]').nth(1);

  if (await cb1.isChecked()) { await cb1.uncheck(); await delay(500); }

  console.log('  Watch: cursor moves to checkbox, clicks');
  t0 = Date.now();
  await cb1.check();
  ms = Date.now() - t0;
  check('check checkbox 1', await cb1.isChecked() && ms > 200, `${ms} ms`);
  await delay(500);

  if (!(await cb2.isChecked())) { await cb2.check(); await delay(500); }

  t0 = Date.now();
  await cb2.uncheck();
  ms = Date.now() - t0;
  check('uncheck checkbox 2', !(await cb2.isChecked()) && ms > 200, `${ms} ms`);
  await delay(1000);

  // ============================================================
  // SCENARIO 3: Dropdown
  // ============================================================
  step('Dropdown — select option');
  await page.goto('https://the-internet.herokuapp.com/dropdown', { waitUntil: 'domcontentloaded' });
  await delay(2000);
  await inject(page);
  await delay(1000);

  console.log('  Watch: cursor hovers dropdown, option selected');
  t0 = Date.now();
  await page.locator('#dropdown').selectOption('2');
  ms = Date.now() - t0;
  val = await page.locator('#dropdown').inputValue();
  check('select option', val === '2' && ms > 100, `${ms} ms, value='${val}'`);
  await delay(1000);

  // ============================================================
  // SCENARIO 4: Drag and Drop
  // ============================================================
  step('Drag and Drop');
  await page.goto('https://the-internet.herokuapp.com/drag_and_drop', { waitUntil: 'domcontentloaded' });
  await delay(2000);
  await inject(page);
  await delay(1000);

  const beforeA = (await page.locator('#column-a header').textContent()).trim();
  console.log(`  Before: A='${beforeA}'`);
  console.log('  Watch: cursor to A, yellow (held), moves to B, releases');

  t0 = Date.now();
  await page.locator('#column-a').dragTo(page.locator('#column-b'));
  ms = Date.now() - t0;
  await delay(1000);

  const afterA = (await page.locator('#column-a header').textContent()).trim();
  const swapped = beforeA !== afterA;
  check('drag A to B', swapped && ms > 300, `${ms} ms, swapped=${swapped}`);
  await delay(1000);

  // ============================================================
  // SCENARIO 5: Text editing
  // ============================================================
  step('Text editing — type, press, clear');
  await page.goto('https://www.wikipedia.org', { waitUntil: 'domcontentloaded' });
  await delay(2000);
  await inject(page);
  await delay(1000);

  console.log('  Watch: types character by character');
  t0 = Date.now();
  await page.locator('#searchInput').type('Hello World');
  ms = Date.now() - t0;
  val = await page.locator('#searchInput').inputValue();
  check("type 'Hello World'", val === 'Hello World' && ms > 1000, `${ms} ms`);
  await delay(500);

  console.log('  Watch: field cleared');
  t0 = Date.now();
  await page.locator('#searchInput').clear();
  ms = Date.now() - t0;
  val = await page.locator('#searchInput').inputValue();
  check('clear field', val === '' && ms > 100, `${ms} ms`);
  await delay(500);

  console.log('  Watch: mouse moves in Bezier curve');
  t0 = Date.now();
  await page.mouse.move(600, 400);
  ms = Date.now() - t0;
  check('mouse.move', ms > 100, `${ms} ms`);
  await delay(500);

  t0 = Date.now();
  await page.mouse.click(300, 300);
  ms = Date.now() - t0;
  check('mouse.click', ms > 100, `${ms} ms`);
  await delay(1000);

  // ============================================================
  // SUMMARY
  // ============================================================
  console.log('\n' + '='.repeat(70));
  console.log('  SUMMARY');
  console.log('='.repeat(70));

  const passed = results.filter(r => r.status === 'PASS').length;
  const failed = results.filter(r => r.status === 'FAIL').length;

  for (const r of results) {
    const icon = r.status === 'PASS' ? 'OK' : 'XX';
    console.log(`  [${icon}] ${r.name}`);
  }

  console.log(`\n  ${passed}/${results.length} passed, ${failed} failed`);
  if (failed === 0) console.log('  *** ALL TESTS PASSED ***');
  console.log('='.repeat(70));

  await browser.close();
}

main().catch(console.error);
