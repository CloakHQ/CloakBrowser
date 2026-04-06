/**
 * Playwright launch wrapper for cloakbrowser.
 * Mirrors Python cloakbrowser/browser.py.
 */

import type { Browser, BrowserContext } from "playwright-core";
import type { LaunchOptions, LaunchContextOptions, LaunchPersistentContextOptions } from "./types.js";
import { DEFAULT_VIEWPORT, IGNORE_DEFAULT_ARGS } from "./config.js";
import { buildArgs } from "./args.js";
import { ensureBinary } from "./download.js";
import { parseProxyUrl } from "./proxy.js";
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
  let resolvedArgs = await resolveWebrtcArgs(options);
  if (exitIp && !(resolvedArgs ?? []).some(a => a.startsWith("--fingerprint-webrtc-ip"))) {
    resolvedArgs = [...(resolvedArgs ?? []), `--fingerprint-webrtc-ip=${exitIp}`];
  }
  const args = buildArgs({ ...options, ...resolved, args: resolvedArgs });

  const browser = await chromium.launch({
    executablePath: binaryPath,
    headless: options.headless ?? true,
    args,
    ignoreDefaultArgs: IGNORE_DEFAULT_ARGS,
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

  // Stealth evaluate — always attached
  const { patchBrowser: patchStealthEval } = await import('./stealth-eval.js');
  patchStealthEval(browser);

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
      ...(options.userAgent ? { userAgent: options.userAgent } : {}),
      viewport: options.viewport ?? DEFAULT_VIEWPORT,
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

  // Stealth evaluate — always attached
  const { patchContext: patchStealthEvalCtx } = await import('./stealth-eval.js');
  patchStealthEvalCtx(context);

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
  let resolvedArgs = await resolveWebrtcArgs(options);
  if (exitIp && !(resolvedArgs ?? []).some(a => a.startsWith("--fingerprint-webrtc-ip"))) {
    resolvedArgs = [...(resolvedArgs ?? []), `--fingerprint-webrtc-ip=${exitIp}`];
  }
  const args = buildArgs({ ...options, ...resolved, args: resolvedArgs });

  // locale and timezone are set via binary flags (--lang, --fingerprint-timezone)
  // — NOT via Playwright context kwargs which use detectable CDP emulation.
  const context = await chromium.launchPersistentContext(options.userDataDir, {
    executablePath: binaryPath,
    headless: options.headless ?? true,
    args,
    ignoreDefaultArgs: IGNORE_DEFAULT_ARGS,
    ...(options.proxy
      ? { proxy: typeof options.proxy === "string" ? parseProxyUrl(options.proxy) : options.proxy }
      : {}),
    ...(options.userAgent ? { userAgent: options.userAgent } : {}),
    viewport: options.viewport ?? DEFAULT_VIEWPORT,
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

  // Stealth evaluate — always attached
  const { patchContext: patchStealthEvalCtx2 } = await import('./stealth-eval.js');
  patchStealthEvalCtx2(context);

  return context;
}

// ---------------------------------------------------------------------------
// Internal
// ---------------------------------------------------------------------------

/** @internal Exposed for unit tests only. */
export { buildArgs as _buildArgsForTest } from "./args.js";
