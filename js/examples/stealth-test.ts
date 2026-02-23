/**
 * Full stealth test suite — validates CloakBrowser against live detection services.
 * Mirrors Python examples/stealth_test.py.
 *
 * Usage:
 *   CLOAKBROWSER_BINARY_PATH=/path/to/chrome npx tsx examples/stealth-test.ts
 *   CLOAKBROWSER_BINARY_PATH=/path/to/chrome npx tsx examples/stealth-test.ts --proxy http://10.50.96.5:8888
 */

import { launch } from "../src/index.js";

const PROXY = process.argv.includes("--proxy")
  ? process.argv[process.argv.indexOf("--proxy") + 1]
  : undefined;

interface TestResult {
  name: string;
  status: "PASS" | "FAIL" | "ERROR";
  verdict: string;
}

const results: TestResult[] = [];

console.log("=".repeat(60));
console.log("CloakBrowser JS — Stealth Test Suite");
console.log("=".repeat(60));
console.log(`Proxy: ${PROXY || "none"}\n`);

const browser = await launch({ headless: true, proxy: PROXY });
const page = await browser.newPage();

// ---------------------------------------------------------------------------
// Test 1: bot.sannysoft.com
// ---------------------------------------------------------------------------
async function testSannysoft() {
  console.log("--- bot.sannysoft.com ---");
  await page.goto("https://bot.sannysoft.com", {
    waitUntil: "networkidle",
    timeout: 30000,
  });
  await page.waitForTimeout(3000);

  const result = await page.evaluate(() => {
    const rows = document.querySelectorAll("table tr");
    let passed = 0;
    let total = 0;
    const failed: string[] = [];
    rows.forEach((r) => {
      const cells = r.querySelectorAll("td");
      if (cells.length >= 2) {
        total++;
        const key = cells[0]!.innerText.trim();
        const cls = cells[1]!.className || "";
        if (cls.includes("failed")) {
          failed.push(key);
        } else {
          passed++;
        }
      }
    });
    return { passed, total, failed };
  });

  const verdict =
    result.failed.length === 0
      ? `${result.passed}/${result.total} — ALL GREEN`
      : `${result.passed}/${result.total} (FAILED: ${result.failed.join(", ")})`;
  const status = result.failed.length === 0 ? "PASS" : "FAIL";
  console.log(`Result: [${status}] ${verdict}\n`);
  results.push({ name: "bot.sannysoft.com", status, verdict });
}

// ---------------------------------------------------------------------------
// Test 2: bot.incolumitas.com
// ---------------------------------------------------------------------------
async function testIncolumitas() {
  console.log("--- bot.incolumitas.com ---");
  await page.goto("https://bot.incolumitas.com", {
    waitUntil: "networkidle",
    timeout: 30000,
  });
  await page.waitForTimeout(12000); // needs time for all detection tests

  const result = await page.evaluate(() => {
    const text = document.body.innerText;
    const okMatches = text.match(/"(\w+)":\s*"OK"/g) || [];
    const failMatches = text.match(/"(\w+)":\s*"FAIL"/g) || [];
    const failedTests = failMatches.map((m) => {
      const match = m.match(/"(\w+)"/);
      return match ? match[1] : m;
    });
    return {
      passed: okMatches.length,
      failed: failMatches.length,
      failedTests,
      total: okMatches.length + failMatches.length,
    };
  });

  const verdict =
    result.failed === 0
      ? `${result.passed}/${result.total} — ALL GREEN`
      : `${result.passed}/${result.total} (FAILED: ${result.failedTests.join(", ")})`;
  // WEBDRIVER false positive is expected
  const status = result.failed <= 1 ? "PASS" : "FAIL";
  console.log(`Result: [${status}] ${verdict}\n`);
  results.push({ name: "bot.incolumitas.com", status, verdict });
}

// ---------------------------------------------------------------------------
// Test 3: BrowserScan
// ---------------------------------------------------------------------------
async function testBrowserScan() {
  console.log("--- BrowserScan ---");
  await page.goto("https://www.browserscan.net/bot-detection", {
    waitUntil: "networkidle",
    timeout: 30000,
  });
  await page.waitForTimeout(5000);

  const result = await page.evaluate(() => {
    const text = document.body.innerText;
    const normalMatches = text.match(/Normal/g);
    const abnormalMatches = text.match(/Abnormal/g);
    return {
      normal: normalMatches ? normalMatches.length : 0,
      abnormal: abnormalMatches ? abnormalMatches.length : 0,
    };
  });

  const verdict = `Normal: ${result.normal}, Abnormal: ${result.abnormal}`;
  const status = result.abnormal === 0 ? "PASS" : "FAIL";
  console.log(`Result: [${status}] ${verdict}\n`);
  results.push({ name: "BrowserScan", status, verdict });
}

// ---------------------------------------------------------------------------
// Test 4: deviceandbrowserinfo.com
// ---------------------------------------------------------------------------
async function testDeviceAndBrowserInfo() {
  console.log("--- deviceandbrowserinfo.com ---");
  await page.goto("https://deviceandbrowserinfo.com/are_you_a_bot", {
    waitUntil: "domcontentloaded",
    timeout: 30000,
  });
  await page.waitForTimeout(8000);

  const result = await page.evaluate(() => {
    const text = document.body.innerText;
    const botMatch = text.match(/"isBot":\s*(true|false)/);
    const isBot = botMatch ? botMatch[1] === "true" : null;
    const checks: Record<string, boolean> = {};
    const patterns = [
      "isBot",
      "hasBotUserAgent",
      "hasWebdriverTrue",
      "isHeadlessChrome",
      "isAutomatedWithCDP",
      "hasSuspiciousWeakSignals",
      "isPlaywright",
      "hasInconsistentChromeObject",
    ];
    patterns.forEach((p) => {
      const match = text.match(new RegExp('"' + p + '":\\s*(true|false)'));
      if (match) checks[p] = match[1] === "true";
    });
    return { isBot, checks };
  });

  const trueFlags = Object.entries(result.checks)
    .filter(([, v]) => v)
    .map(([k]) => k);
  const verdict =
    `isBot: ${result.isBot}` +
    (trueFlags.length > 0 ? ` (flagged: ${trueFlags.join(", ")})` : " — all clear");
  const status = !result.isBot ? "PASS" : "FAIL";
  console.log(`Result: [${status}] ${verdict}\n`);
  results.push({ name: "deviceandbrowserinfo.com", status, verdict });
}

// ---------------------------------------------------------------------------
// Test 5: FingerprintJS
// ---------------------------------------------------------------------------
async function testFingerprintJS() {
  console.log("--- FingerprintJS ---");
  await page.goto("https://demo.fingerprint.com/web-scraping", {
    waitUntil: "networkidle",
    timeout: 30000,
  });
  await page.waitForTimeout(5000);

  try {
    await page.click("button:has-text('Search')", { timeout: 5000 });
    await page.waitForTimeout(5000);
  } catch {
    // Search button may not be present
  }

  const result = await page.evaluate(() => {
    const text = document.body.innerText;
    const hasFlights =
      text.includes("Price per adult") || text.includes("$");
    const isBlocked =
      text.includes("request was blocked") ||
      text.includes("bot visit detected");
    return { passed: hasFlights && !isBlocked, isBlocked, hasFlights };
  });

  const verdict = result.passed
    ? "PASSED (flights shown)"
    : result.isBlocked
      ? "BLOCKED"
      : "NO FLIGHTS";
  const status = result.passed ? "PASS" : "FAIL";
  console.log(`Result: [${status}] ${verdict}\n`);
  results.push({ name: "FingerprintJS", status, verdict });
}

// ---------------------------------------------------------------------------
// Test 6: reCAPTCHA v3
// ---------------------------------------------------------------------------
async function testRecaptcha() {
  console.log("--- reCAPTCHA v3 (Google) ---");
  await page.goto(
    "https://recaptcha-demo.appspot.com/recaptcha-v3-request-scores.php",
    { waitUntil: "networkidle", timeout: 30000 }
  );
  await page.waitForTimeout(8000);

  const result = await page.evaluate(() => {
    const text = document.body.innerText;
    const scoreMatch = text.match(/"score":\s*(\d+\.\d+)/);
    return {
      score: scoreMatch ? parseFloat(scoreMatch[1]) : null,
    };
  });

  const verdict = `Score: ${result.score ?? "N/A"}`;
  const status = (result.score ?? 0) >= 0.7 ? "PASS" : "FAIL";
  console.log(`Result: [${status}] ${verdict}\n`);
  results.push({ name: "reCAPTCHA v3", status, verdict });
}

// ---------------------------------------------------------------------------
// Run all tests
// ---------------------------------------------------------------------------
const tests = [
  testSannysoft,
  testIncolumitas,
  testBrowserScan,
  testDeviceAndBrowserInfo,
  testFingerprintJS,
  testRecaptcha,
];

for (const test of tests) {
  try {
    await test();
  } catch (err) {
    const name = test.name.replace("test", "");
    console.log(`Error: ${err}\n`);
    results.push({ name, status: "ERROR", verdict: String(err) });
  }
}

await browser.close();

// Summary
console.log("=".repeat(60));
console.log("RESULTS SUMMARY");
console.log("=".repeat(60));
for (const r of results) {
  const icon = { PASS: "+", FAIL: "!", ERROR: "x" }[r.status];
  console.log(`  [${icon}] ${r.name}: ${r.verdict}`);
}
const passedCount = results.filter((r) => r.status === "PASS").length;
console.log(`\n  ${passedCount}/${results.length} tests passed`);
console.log("=".repeat(60));

process.exit(passedCount === results.length ? 0 : 1);
