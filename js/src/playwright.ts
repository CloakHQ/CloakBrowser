/**
 * Playwright launch wrapper for cloakbrowser.
 * Mirrors Python cloakbrowser/browser.py.
 */

import type { Browser, BrowserContext, BrowserContextOptions } from "playwright-core";
import type { LaunchOptions, LaunchContextOptions, LaunchPersistentContextOptions } from "./types.js";
import { DEFAULT_VIEWPORT, IGNORE_DEFAULT_ARGS } from "./config.js";
import { buildArgs } from "./args.js";
import { ensureBinary } from "./download.js";
import { resolveProxyConfig } from "./proxy.js";
import { maybeResolveGeoip, resolveWebrtcArgs } from "./geoip.js";

/** @internal Accept both timezone and timezoneId — either works, no warning. Exported for testing. */
export function resolveTimezone<T extends { timezone?: string; timezoneId?: string }>(options: T): T {
  if (options.timezoneId != null) {
    const merged = { ...options, timezone: options.timezone ?? options.timezoneId };
    delete (merged as any).timezoneId;
    return merged;
  }
  return options;
}

/**
 * Strip `locale` and `timezoneId` from user-provided contextOptions — both route
 * through detectable CDP emulation. The wrapper's top-level `locale`/`timezone`
 * fields use binary flags instead (undetectable). Warn so users notice.
 */
function filterStealthCtxOptions(ctx?: BrowserContextOptions): Partial<BrowserContextOptions> {
  if (!ctx) return {};
  const { locale, timezoneId, ...rest } = ctx;
  if (locale !== undefined) {
    console.warn(
      "[cloakbrowser] contextOptions.locale ignored — use top-level `locale` " +
      "instead (routes through binary flag, avoids detectable CDP emulation)."
    );
  }
  if (timezoneId !== undefined) {
    console.warn(
      "[cloakbrowser] contextOptions.timezoneId ignored — use top-level `timezone` " +
      "instead (routes through binary flag, avoids detectable CDP emulation)."
    );
  }
  return rest;
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
  const { exitIp, ...resolved } = await maybeResolveGeoip(options);
  const { proxyOption, proxyArgs } = resolveProxyConfig(options.proxy);
  let resolvedArgs = await resolveWebrtcArgs(options);
  if (exitIp && !(resolvedArgs ?? []).some(a => a.startsWith("--fingerprint-webrtc-ip"))) {
    resolvedArgs = [...(resolvedArgs ?? []), `--fingerprint-webrtc-ip=${exitIp}`];
  }
  const args = buildArgs({ ...options, ...resolved, args: [...(resolvedArgs ?? []), ...proxyArgs] });

  const browser = await chromium.launch({
    executablePath: binaryPath,
    headless: options.headless ?? true,
    args,
    ignoreDefaultArgs: IGNORE_DEFAULT_ARGS,
    ...(proxyOption ? { proxy: proxyOption } : {}),
    ...options.launchOptions,
  });

  // Human-like behavioral patching
  if (options.humanize) {
    const { patchBrowser } = await import('./human/index.js');
    const { resolveConfig } = await import('./human/config.js');
    const cfg = resolveConfig(
      options.humanPreset ?? 'default',
      options.humanConfig,
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
  options = resolveTimezone(options);
  // Resolve geoip BEFORE launch() to avoid double-resolution
  const { exitIp, ...resolved } = await maybeResolveGeoip(options);
  let launchArgs = await resolveWebrtcArgs(options);
  // Inject geoip exit IP for WebRTC spoofing (free — no extra HTTP call)
  if (exitIp && !(launchArgs ?? []).some(a => a.startsWith("--fingerprint-webrtc-ip"))) {
    launchArgs = [...(launchArgs ?? []), `--fingerprint-webrtc-ip=${exitIp}`];
  }
  // --fingerprint-timezone is process-wide (reads CommandLine in renderer),
  // so it applies to ALL contexts, not just the default one.
  // locale and timezone are set via binary flags only — no CDP emulation.
  const browser = await launch({ ...options, ...resolved, args: launchArgs, geoip: false });

  let context: BrowserContext;
  try {
    context = await browser.newContext({
      // contextOptions first — explicit wrapper fields below override it.
      // filterStealthCtxOptions strips locale/timezoneId to prevent CDP detection.
      ...filterStealthCtxOptions(options.contextOptions),
      ...(options.userAgent ? { userAgent: options.userAgent } : {}),
      viewport: options.viewport === undefined ? DEFAULT_VIEWPORT : options.viewport,
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
      options.humanPreset ?? 'default',
      options.humanConfig,
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
  options = resolveTimezone(options);
  const { chromium } = await import("playwright-core");

  const binaryPath = process.env.CLOAKBROWSER_BINARY_PATH || (await ensureBinary());
  const { exitIp, ...resolved } = await maybeResolveGeoip(options);
  const { proxyOption, proxyArgs } = resolveProxyConfig(options.proxy);
  let resolvedArgs = await resolveWebrtcArgs(options);
  if (exitIp && !(resolvedArgs ?? []).some(a => a.startsWith("--fingerprint-webrtc-ip"))) {
    resolvedArgs = [...(resolvedArgs ?? []), `--fingerprint-webrtc-ip=${exitIp}`];
  }
  const args = buildArgs({ ...options, ...resolved, args: [...(resolvedArgs ?? []), ...proxyArgs] });

  // locale and timezone are set via binary flags (--lang, --fingerprint-timezone)
  // — NOT via Playwright context kwargs which use detectable CDP emulation.
  const context = await chromium.launchPersistentContext(options.userDataDir, {
    executablePath: binaryPath,
    headless: options.headless ?? true,
    args,
    ignoreDefaultArgs: IGNORE_DEFAULT_ARGS,
    ...(proxyOption ? { proxy: proxyOption } : {}),
    // contextOptions before explicit wrapper fields so explicit wins.
    // filterStealthCtxOptions strips locale/timezoneId to prevent CDP detection.
    ...filterStealthCtxOptions(options.contextOptions),
    ...(options.userAgent ? { userAgent: options.userAgent } : {}),
    viewport: options.viewport === undefined ? DEFAULT_VIEWPORT : options.viewport,
    ...(options.colorScheme ? { colorScheme: options.colorScheme } : {}),
    ...options.launchOptions,
  });

  // Human-like behavioral patching
  if (options.humanize) {
    const { patchContext } = await import('./human/index.js');
    const { resolveConfig } = await import('./human/config.js');
    const cfg = resolveConfig(
      options.humanPreset ?? 'default',
      options.humanConfig,
    );
    patchContext(context, cfg);
  }

  return context;
}

// ---------------------------------------------------------------------------
// Internal
// ---------------------------------------------------------------------------

/** @internal Exposed for unit tests only. */
export { buildArgs as _buildArgsForTest } from "./args.js";
