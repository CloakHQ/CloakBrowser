/**
 * Proxy rotation example: rotate through a pool of proxies with health tracking.
 *
 * Usage:
 *   npx tsx examples/proxy-rotation.ts
 *
 * Replace the proxy URLs below with your actual proxy servers.
 */

import { ProxyRotator } from "../src/index.js";
// import { launch } from "../src/index.js";

// ---- 1. Basic setup: create a rotator with multiple proxies ----
const rotator = new ProxyRotator(
  [
    "http://user:pass@proxy1.example.com:8080",
    "http://user:pass@proxy2.example.com:8080",
    "http://user:pass@proxy3.example.com:8080",
  ],
  {
    strategy: "round_robin", // Options: round_robin, random, least_used, least_failures
  }
);

// ---- 2. Simple usage: get next proxy for each browser launch ----
console.log(`Pool: ${rotator}`);
console.log(`Available: ${rotator.availableCount}/${rotator.size}`);

for (let i = 0; i < 3; i++) {
  const proxy = rotator.next();
  console.log(`\nRequest ${i + 1}: Using proxy ${proxy}`);

  // In real usage:
  // const browser = await launch({ proxy });
  // const page = await browser.newPage();
  // await page.goto("https://example.com");
  // rotator.reportSuccess(proxy);
  // await browser.close();

  // Simulate success
  rotator.reportSuccess(proxy);
}

// ---- 3. withSession: auto-reports success/failure ----
console.log("\n--- withSession ---");
try {
  await rotator.withSession(async (proxy) => {
    console.log(`Using proxy: ${proxy}`);
    // const browser = await launch({ proxy });
    // ... do work ...
    // await browser.close();
  });
} catch (e) {
  console.error(`Failed: ${e}`);
}

// ---- 4. Direct integration: pass rotator to launch() ----
console.log("\n--- Direct integration ---");
// CloakBrowser accepts ProxyRotator directly — it calls .next() internally
// const browser = await launch({ proxy: rotator });
// const page = await browser.newPage();
// await page.goto("https://example.com");
// // Use current() to report success/failure for the proxy that was used
// rotator.reportSuccess(rotator.current()!);
// await browser.close();
console.log("launch({ proxy: rotator }) — rotator.next() is called automatically");
console.log("rotator.current() — returns the proxy that was last selected");

// ---- 5. Sticky sessions: reuse the same proxy for N requests ----
console.log("\n--- Sticky sessions (3 requests per proxy) ---");
const stickyRotator = new ProxyRotator(
  [
    "http://user:pass@proxy1.example.com:8080",
    "http://user:pass@proxy2.example.com:8080",
  ],
  {
    strategy: "round_robin",
    stickyCount: 3, // Use same proxy for 3 consecutive requests
  }
);

for (let i = 0; i < 6; i++) {
  const proxy = stickyRotator.next();
  console.log(`  Request ${i + 1}: ${proxy}`);
}

// ---- 6. Health tracking & stats ----
console.log("\n--- Stats ---");
for (const stat of rotator.stats()) {
  console.log(
    `  ${stat.proxy}: uses=${stat.useCount}, fails=${stat.failCount}, available=${stat.available}`
  );
}

// ---- 7. Dynamic pool management ----
console.log("\n--- Dynamic pool ---");
console.log(`Before: ${rotator.size} proxies`);
rotator.add("http://user:pass@proxy4.example.com:8080");
console.log(`After add: ${rotator.size} proxies`);
rotator.remove("http://user:pass@proxy4.example.com:8080");
console.log(`After remove: ${rotator.size} proxies`);

console.log("\nDone!");
