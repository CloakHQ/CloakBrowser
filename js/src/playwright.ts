/**
 * Playwright launch wrapper for cloakbrowser.
 * Mirrors Python cloakbrowser/browser.py.
 */

import type { Browser, BrowserContext } from "playwright-core";
import type { LaunchOptions, LaunchContextOptions } from "./types.js";
import { DEFAULT_VIEWPORT, getDefaultStealthArgs } from "./config.js";
import { ensureBinary } from "./download.js";
import { parseProxyUrl } from "./proxy.js";

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
  const resolved = await maybeResolveGeoip(options);
  const args = buildArgs({ ...options, ...resolved });

  const browser = await chromium.launch({
    executablePath: binaryPath,
    headless: options.headless ?? true,
    args,
    ignoreDefaultArgs: ["--enable-automation"],
    ...(options.proxy ? { proxy: parseProxyUrl(options.proxy) } : {}),
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
  // Resolve geoip BEFORE launch() to avoid double-resolution
  const resolved = await maybeResolveGeoip(options);
  const browser = await launch({ ...options, ...resolved, geoip: false });

  let context: BrowserContext;
  try {
    context = await browser.newContext({
      ...(options.userAgent ? { userAgent: options.userAgent } : {}),
      viewport: options.viewport ?? DEFAULT_VIEWPORT,
      ...(resolved.locale ? { locale: resolved.locale } : {}),
      ...(resolved.timezone ? { timezoneId: resolved.timezone } : {}),
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

async function maybeResolveGeoip(
  options: LaunchOptions
): Promise<{ timezone?: string; locale?: string }> {
  if (!options.geoip || !options.proxy) return { timezone: options.timezone, locale: options.locale };
  if (options.timezone && options.locale) return { timezone: options.timezone, locale: options.locale };

  const { resolveProxyGeo } = await import("./geoip.js");
  const { timezone: geoTz, locale: geoLocale } = await resolveProxyGeo(options.proxy);
  return {
    timezone: options.timezone ?? geoTz ?? undefined,
    locale: options.locale ?? geoLocale ?? undefined,
  };
}

/** @internal Exposed for unit tests only. */
export function _buildArgsForTest(options: LaunchOptions): string[] {
  return buildArgs(options);
}

function buildArgs(options: LaunchOptions): string[] {
  const args: string[] = [];
  if (options.stealthArgs !== false) {
    args.push(...getDefaultStealthArgs());
  }
  if (options.args) {
    args.push(...options.args);
  }
  // Timezone/locale flags — always inject when set
  if (options.timezone) {
    args.push(`--timezone=${options.timezone}`);
  }
  if (options.locale) {
    args.push(`--lang=${options.locale}`);
  }
  return args;
}
