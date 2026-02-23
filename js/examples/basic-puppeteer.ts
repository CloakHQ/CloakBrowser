/**
 * Basic CloakBrowser example using Puppeteer API.
 *
 * Usage:
 *   CLOAKBROWSER_BINARY_PATH=/path/to/chrome npx tsx examples/basic-puppeteer.ts
 */

import { launch } from "../src/puppeteer.js";

const browser = await launch({ headless: true });
const page = await browser.newPage();

await page.goto("https://example.com");
console.log(`Title: ${await page.title()}`);
console.log(`URL: ${page.url()}`);

await browser.close();
console.log("Done.");
