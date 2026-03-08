/**
 * Playwright launch wrapper for cloakbrowser.
 * Mirrors Python cloakbrowser/browser.py.
 */

import type { Browser, BrowserContext } from "playwright-core";
import type { LaunchOptions, LaunchContextOptions, LaunchPersistentContextOptions } from "./types.js";
import { DEFAULT_VIEWPORT } from "./config.js";
import { buildArgs } from "./args.js";
import { ensureBinary } from "./download.js";
import { parseProxyUrl } from "./proxy.js";

/** @internal Migrate deprecated timezoneId → timezone, warn once. Exported for testing. */
export function migrateTimezoneId<T extends { timezone?: string; timezoneId?: string }>(options: T): T {
  if (options.timezoneId != null) {
    console.warn("[cloakbrowser] timezoneId is deprecated, use timezone instead");
    const merged = { ...options, timezone: options.timezone ?? options.timezoneId };
    delete (merged as any).timezoneId;
    return merged;
  }
  return options;
}

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
    ...(options.proxy
      ? { proxy: typeof options.proxy === "string" ? parseProxyUrl(options.proxy) : options.proxy }
      : {}),
    ...options.launchOptions,
  });

  // Human-like behavioral patching
  if (options.humanize) {
    const { patchBrowser } = await import('./human/index.js');
    const { resolveConfig } = await import('./human/config.js');
    const cfg = resolveConfig(
      (options.humanPreset as any) ?? 'default',
      options.humanConfig as any,
    );
    patchBrowser(browser, cfg);
  }

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
  options = migrateTimezoneId(options);
  // Resolve geoip BEFORE launch() to avoid double-resolution
  const resolved = await maybeResolveGeoip(options);
  // Skip --fingerprint-timezone binary flag: it only applies to the default
  // context and interferes with Playwright's timezoneId on new contexts.
  // Timezone is set via browser.newContext(timezoneId: ...) below instead.
  const browser = await launch({ ...options, ...resolved, geoip: false, timezone: undefined });

  let context: BrowserContext;
  try {
    context = await browser.newContext({
      ...(options.userAgent ? { userAgent: options.userAgent } : {}),
      viewport: options.viewport ?? DEFAULT_VIEWPORT,
      ...(resolved.locale ? { locale: resolved.locale } : {}),
      ...(resolved.timezone ? { timezoneId: resolved.timezone } : {}),
      ...(options.colorScheme ? { colorScheme: options.colorScheme } : {}),
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

  // Human-like behavioral patching
  if (options.humanize) {
    const { patchContext } = await import('./human/index.js');
    const { resolveConfig } = await import('./human/config.js');
    const cfg = resolveConfig(
      (options.humanPreset as any) ?? 'default',
      options.humanConfig as any,
    );
    patchContext(context, cfg);
  }

  return context;
}

/**
 * Launch stealth browser with a persistent user profile (non-incognito).
 * Uses Playwright's chromium.launchPersistentContext() under the hood.
 *
 * This avoids incognito detection by services like BrowserScan (-10% penalty)
 * and enables session persistence (cookies, localStorage) across launches.
 *
 * @example
 * ```ts
 * import { launchPersistentContext } from 'cloakbrowser';
 * const context = await launchPersistentContext({
 *   userDataDir: './chrome-profile',
 *   headless: false,
 *   proxy: 'http://user:pass@host:port',
 *   geoip: true,
 * });
 * const page = context.pages()[0] || await context.newPage();
 * await page.goto('https://example.com');
 * await context.close();
 * ```
 */
export async function launchPersistentContext(
  options: LaunchPersistentContextOptions
): Promise<BrowserContext> {
  options = migrateTimezoneId(options);
  const { chromium } = await import("playwright-core");

  const binaryPath = process.env.CLOAKBROWSER_BINARY_PATH || (await ensureBinary());
  const resolved = await maybeResolveGeoip(options);
  const args = buildArgs({ ...options, ...resolved });

  const context = await chromium.launchPersistentContext(options.userDataDir, {
    executablePath: binaryPath,
    headless: options.headless ?? true,
    args,
    ignoreDefaultArgs: ["--enable-automation"],
    ...(options.proxy
      ? { proxy: typeof options.proxy === "string" ? parseProxyUrl(options.proxy) : options.proxy }
      : {}),
    ...(options.userAgent ? { userAgent: options.userAgent } : {}),
    viewport: options.viewport ?? DEFAULT_VIEWPORT,
    ...(resolved.locale ? { locale: resolved.locale } : {}),
    ...(resolved.timezone ? { timezoneId: resolved.timezone } : {}),
    ...(options.colorScheme ? { colorScheme: options.colorScheme } : {}),
    ...options.launchOptions,
  });

  // Human-like behavioral patching
  if (options.humanize) {
    const { patchContext } = await import('./human/index.js');
    const { resolveConfig } = await import('./human/config.js');
    const cfg = resolveConfig(
      (options.humanPreset as any) ?? 'default',
      options.humanConfig as any,
    );
    patchContext(context, cfg);
  }

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
  const proxyUrl = typeof options.proxy === "string" ? options.proxy : options.proxy.server;
  if (!proxyUrl) return { timezone: options.timezone, locale: options.locale };
  const { timezone: geoTz, locale: geoLocale } = await resolveProxyGeo(proxyUrl);
  return {
    timezone: options.timezone ?? geoTz ?? undefined,
    locale: options.locale ?? geoLocale ?? undefined,
  };
}

/** @internal Exposed for unit tests only. */
export { buildArgs as _buildArgsForTest } from "./args.js";
