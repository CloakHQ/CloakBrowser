/**
 * Windows example: launch stealth browser with custom binary path.
 *
 * This example demonstrates how to use CloakBrowser on Windows 10/11
 * with a custom (self-built) Chromium binary.
 *
 * Usage:
 *   set CLOAKBROWSER_BINARY_PATH=C:\path\to\chrome.exe
 *   npx tsx examples/windows-example.ts
 *
 * Or set in code:
 *   process.env.CLOAKBROWSER_BINARY_PATH = "C:\\path\\to\\chrome.exe";
 */

import { launch, binaryInfo } from "../src/index.js";

// Option 1: Set in code
// Replace with your actual Chrome path
process.env.CLOAKBROWSER_BINARY_PATH = "C:\\path\\to\\your\\chromium\\build\\chrome.exe";

// Print binary info to verify
const info = binaryInfo();
console.log(`Binary: ${info.binaryPath}`);
console.log(`Installed: ${info.installed}`);

// Launch the browser
const browser = await launch({ headless: false });
const page = await browser.newPage();

// Navigate to a test page
await page.goto("https://example.com");
console.log(`Title: ${await page.title()}`);
console.log(`URL: ${page.url()}`);

// Close browser
await browser.close();
console.log("Done.");
