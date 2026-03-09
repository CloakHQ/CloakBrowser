// tests/test_proxy_real.mjs
/**
 * Real proxy rotation test (JS) — launches browsers with actual proxies.
 * Run: node tests/test_proxy_real.mjs
 */
import { launch } from '../js/dist/index.js';
import { ProxyRotator } from '../js/dist/proxy-rotator.js';

const PROXIES = [
  'http://user:pass@proxy1.example.com:5610',
  'http://user:pass@proxy2.example.com:4586',
  'http://user:pass@proxy3.example.com:5906',
];

const results = [];

function check(name, passed, detail = '') {
  const status = passed ? 'PASS' : 'FAIL';
  let msg = `  [${status}] ${name}`;
  if (detail) msg += ` — ${detail}`;
  console.log(msg);
  results.push({ name, status });
}

async function main() {
  console.log('='.repeat(70));
  console.log('  PROXY ROTATION — REAL BROWSER TEST (JS)');
  console.log('='.repeat(70));

  // ---- Test 1: Round-robin — each proxy returns different IP ----
  console.log('\n--- Test 1: Round-robin rotation ---');
  const rotator = new ProxyRotator(PROXIES, { strategy: 'round_robin' });
  const ips = [];

  for (let i = 0; i < 3; i++) {
    const proxy = rotator.next();
    const browser = await launch({ headless: true, proxy });
    const page = await browser.newPage();
    await page.goto('https://api.ipify.org?format=json', { timeout: 15000 });
    const ip = await page.textContent('body');
    console.log(`  Proxy ${i + 1}: ${ip}`);
    ips.push(ip);
    rotator.reportSuccess(proxy);
    await browser.close();
  }

  const unique = new Set(ips);
  check('round-robin unique IPs', unique.size === 3, `${unique.size} unique`);

  // ---- Test 2: Sticky — same IP for 2 requests ----
  console.log('\n--- Test 2: Sticky session (2 requests) ---');
  const sticky = new ProxyRotator(PROXIES.slice(0, 2), {
    strategy: 'round_robin',
    stickyCount: 2,
  });
  const stickyIps = [];

  for (let i = 0; i < 4; i++) {
    const proxy = sticky.next();
    const browser = await launch({ headless: true, proxy });
    const page = await browser.newPage();
    await page.goto('https://api.ipify.org?format=json', { timeout: 15000 });
    const ip = await page.textContent('body');
    console.log(`  Request ${i + 1}: ${ip}`);
    stickyIps.push(ip);
    sticky.reportSuccess(proxy);
    await browser.close();
  }

  check('sticky first pair', stickyIps[0] === stickyIps[1], `${stickyIps[0]} == ${stickyIps[1]}`);
  check('sticky second pair', stickyIps[2] === stickyIps[3], `${stickyIps[2]} == ${stickyIps[3]}`);
  check('sticky pairs differ', stickyIps[0] !== stickyIps[2], `${stickyIps[0]} != ${stickyIps[2]}`);

  // ---- Test 3: withSession — success tracking ----
  console.log('\n--- Test 3: withSession tracking ---');
  const tracker = new ProxyRotator(PROXIES, { strategy: 'least_failures' });

  await tracker.withSession(async (proxy) => {
    const browser = await launch({ headless: true, proxy });
    const page = await browser.newPage();
    await page.goto('https://api.ipify.org?format=json', { timeout: 15000 });
    console.log(`  Session proxy: ${await page.textContent('body')}`);
    await browser.close();
  });

  const stats = tracker.stats();
  const totalFails = stats.reduce((sum, s) => sum + s.failCount, 0);
  check('session no failures', totalFails === 0, `total fails: ${totalFails}`);
  for (const s of stats) {
    console.log(`  ${s.proxy}: uses=${s.useCount}, fails=${s.failCount}`);
  }

  // ---- Test 4: SOCKS5 with auth rejected ----
  console.log('\n--- Test 4: SOCKS5 auth validation ---');
  let socks5Rejected = false;
  try {
    new ProxyRotator(['socks5://user:pass@host:1080']);
  } catch (e) {
    socks5Rejected = e.message.includes('SOCKS5');
  }
  check('socks5 with auth rejected', socks5Rejected);

  let socks5NoAuth = false;
  try {
    new ProxyRotator(['socks5://host:1080']);
    socks5NoAuth = true;
  } catch (_) {}
  check('socks5 without auth accepted', socks5NoAuth);

  let socks5DictRejected = false;
  try {
    new ProxyRotator([{ server: 'socks5://host:1080', username: 'u', password: 'p' }]);
  } catch (e) {
    socks5DictRejected = e.message.includes('SOCKS5');
  }
  check('socks5 dict with auth rejected', socks5DictRejected);

  let addRejected = false;
  try {
    const r = new ProxyRotator(['http://proxy:8080']);
    r.add('socks5://user:pass@host:1080');
  } catch (e) {
    addRejected = e.message.includes('SOCKS5');
  }
  check('add socks5 with auth rejected', addRejected);

  // ---- Summary ----
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

  await new Promise(r => setTimeout(r, 500));
  process.exit(failed > 0 ? 1 : 0);
}

main().catch(e => { console.error(e); process.exit(1); });
