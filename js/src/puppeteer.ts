/**
 * Puppeteer launch wrapper for cloakbrowser.
 * Alternative to the Playwright wrapper for users who prefer Puppeteer.
 */

import type { Browser } from "puppeteer-core";
import type { LaunchOptions } from "./types.js";
import { getDefaultStealthArgs } from "./config.js";
import { ensureBinary } from "./download.js";

/**
 * Launch stealth Chromium browser via Puppeteer.
 *
 * @example
 * ```ts
 * import { launch } from 'cloakbrowser/puppeteer';
 * const browser = await launch();
 * const page = await browser.newPage();
 * await page.goto('https://bot.incolumitas.com');
 * console.log(await page.title());
 * await browser.close();
 * ```
 */
export async function launch(options: LaunchOptions = {}): Promise<Browser> {
  const puppeteer = await import("puppeteer-core");

  const binaryPath = process.env.CLOAKBROWSER_BINARY_PATH || (await ensureBinary());
  const args = buildArgs(options);

  // Puppeteer handles proxy via CLI args, not a separate option
  if (options.proxy) {
    args.push(`--proxy-server=${options.proxy}`);
  }

  const browser = await puppeteer.default.launch({
    executablePath: binaryPath,
    headless: options.headless ?? true,
    args,
    ignoreDefaultArgs: ["--enable-automation"],
    ...options.launchOptions,
  });

  return browser;
}

// ---------------------------------------------------------------------------
// Internal
// ---------------------------------------------------------------------------

function buildArgs(options: LaunchOptions): string[] {
  const args: string[] = [];
  if (options.stealthArgs !== false) {
    args.push(...getDefaultStealthArgs());
  }
  if (options.args) {
    args.push(...options.args);
  }
  return args;
}
