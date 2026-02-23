/**
 * Playwright launch wrapper for cloakbrowser.
 * Mirrors Python cloakbrowser/browser.py.
 */

import type { Browser, BrowserContext } from "playwright-core";
import type { LaunchOptions, LaunchContextOptions } from "./types.js";
import { getDefaultStealthArgs } from "./config.js";
import { ensureBinary } from "./download.js";

/**
 * Launch stealth Chromium browser via Playwright.
 *
 * @example
 * ```ts
 * import { launch } from 'cloakbrowser';
 * const browser = await launch();
 * const page = await browser.newPage();
 * await page.goto('https://bot.incolumitas.com');
 * console.log(await page.title());
 * await browser.close();
 * ```
 */
export async function launch(options: LaunchOptions = {}): Promise<Browser> {
  const { chromium } = await import("playwright-core");

  const binaryPath = process.env.CLOAKBROWSER_BINARY_PATH || (await ensureBinary());
  const args = buildArgs(options);

  const browser = await chromium.launch({
    executablePath: binaryPath,
    headless: options.headless ?? true,
    args,
    ignoreDefaultArgs: ["--enable-automation"],
    ...(options.proxy ? { proxy: { server: options.proxy } } : {}),
    ...options.launchOptions,
  });

  return browser;
}

/**
 * Launch stealth browser and return a BrowserContext with common options pre-set.
 * Closing the context also closes the browser.
 *
 * @example
 * ```ts
 * import { launchContext } from 'cloakbrowser';
 * const context = await launchContext({
 *   userAgent: 'Mozilla/5.0...',
 *   viewport: { width: 1920, height: 1080 },
 * });
 * const page = await context.newPage();
 * await page.goto('https://example.com');
 * await context.close(); // also closes browser
 * ```
 */
export async function launchContext(
  options: LaunchContextOptions = {}
): Promise<BrowserContext> {
  const browser = await launch(options);

  let context: BrowserContext;
  try {
    context = await browser.newContext({
      ...(options.userAgent ? { userAgent: options.userAgent } : {}),
      ...(options.viewport ? { viewport: options.viewport } : {}),
      ...(options.locale ? { locale: options.locale } : {}),
      ...(options.timezoneId ? { timezoneId: options.timezoneId } : {}),
    });
  } catch (err) {
    await browser.close();
    throw err;
  }

  // Patch close() to also close the browser
  const origClose = context.close.bind(context);
  context.close = async () => {
    await origClose();
    await browser.close();
  };

  return context;
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
