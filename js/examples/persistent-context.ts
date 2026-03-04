/**
 * Persistent context example: cookies and localStorage survive across sessions.
 *
 * Usage:
 *   CLOAKBROWSER_BINARY_PATH=/path/to/chrome npx tsx examples/persistent-context.ts
 */

import { launchPersistentContext } from "../src/index.js";

const PROFILE_DIR = "./my-profile";

// Session 1 — set some state
console.log("=== Session 1: Setting state ===");
let ctx = await launchPersistentContext({
  userDataDir: PROFILE_DIR,
  headless: false,
});
let page = ctx.pages()[0] || (await ctx.newPage());
await page.goto("https://example.com");
await page.evaluate(() => {
  document.cookie = "session=abc123; path=/; max-age=3600";
  localStorage.setItem("user", "returning");
});
console.log(`Cookie: ${await page.evaluate(() => document.cookie)}`);
console.log(`localStorage: ${await page.evaluate(() => localStorage.getItem("user"))}`);
await ctx.close();

// Session 2 — state is restored
console.log("\n=== Session 2: Verifying persistence ===");
ctx = await launchPersistentContext({
  userDataDir: PROFILE_DIR,
  headless: false,
});
page = ctx.pages()[0] || (await ctx.newPage());
await page.goto("https://example.com");
console.log(`Cookie: ${await page.evaluate(() => document.cookie)}`);
console.log(`localStorage: ${await page.evaluate(() => localStorage.getItem("user"))}`);
await ctx.close();

console.log("\nDone!");
