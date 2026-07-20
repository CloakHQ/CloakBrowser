/**
 * Playwright launch wrapper for cloakbrowser.
 * Mirrors Python cloakbrowser/browser.py.
 */

import type { Browser, BrowserContext, BrowserContextOptions, LaunchOptions as PlaywrightLaunchOptions } from "playwright-core";
import type { LaunchOptions, LaunchContextOptions, LaunchPersistentContextOptions } from "./types.js";
import {
  DEFAULT_VIEWPORT,
  IGNORE_DEFAULT_ARGS,
  binarySupportsHeadlessNoViewport,
} from "./config.js";
import { buildArgs } from "./args.js";
import { maybeWarnWindowsFonts } from "./fonts.js";
import { ensureBinary } from "./download.js";
import { resolveProxyConfig } from "./proxy.js";
import { maybeResolveGeoip, resolveWebrtcArgs, appendWebrtcExitIp } from "./geoip.js";
import { buildLaunchEnv, licenseErrorFrom } from "./license.js";
import { seedWidevineHint } from "./widevine.js";

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
 * Build Playwright BrowserContext options for CloakBrowser without launching a browser
 * or creating a context.
 *
 * Useful when integrating CloakBrowser with an existing Playwright Browser while
 * keeping the wrapper's stealth-safe defaults for `newContext()`.
 */
/**
 * Effective headless mode for viewport decisions. buildLaunchOptions() spreads
 * `...options.launchOptions` LAST, so a raw `launchOptions.headless` overrides the
 * top-level field at the actual chromium.launch() call. Viewport logic must read
 * the same effective value — otherwise a headed browser gets a fixed viewport
 * (reintroducing the impossible-window tell). Playwright-specific (Puppeteer
 * resolves headless the opposite way).
 */
function effectiveHeadless(options: LaunchOptions): boolean {
  return (
    (options.launchOptions as { headless?: boolean } | undefined)?.headless ??
    options.headless ??
    true
  );
}

export function buildContextOptions(
  options: LaunchContextOptions = {}
): BrowserContextOptions {
  // Headed: viewport=null (no emulation) so the page tracks the real window and
  // outerWidth >= innerWidth stays coherent. Headless on a newer binary: also
  // null, since it reports coherent dimensions without emulation. Headless on an
  // older binary: a fixed DEFAULT_VIEWPORT keeps dimensions coherent and
  // deterministic. Explicit viewport (incl. null) is always honored.
  const headless = effectiveHeadless(options);
  const headlessNoViewport =
    headless && binarySupportsHeadlessNoViewport(options.licenseKey, options.browserVersion);
  const viewport =
    options.viewport !== undefined
      ? options.viewport
      : headless && !headlessNoViewport
        ? DEFAULT_VIEWPORT
        : null;
  return {
    // contextOptions first — explicit wrapper fields below override it.
    // filterStealthCtxOptions strips locale/timezoneId to prevent CDP detection.
    ...filterStealthCtxOptions(options.contextOptions),
    ...(options.userAgent ? { userAgent: options.userAgent } : {}),
    viewport,
    ...(options.colorScheme ? { colorScheme: options.colorScheme } : {}),
  } as BrowserContextOptions;
}

/**
 * Build Playwright launch options for CloakBrowser without starting Chromium.
 *
 * Useful when integrating CloakBrowser with a custom Playwright build or another
 * wrapper that needs to call `chromium.launch()` itself.
 */
export async function buildLaunchOptions(
  options: LaunchOptions = {}
): Promise<PlaywrightLaunchOptions> {
  const binaryPath =
    process.env.CLOAKBROWSER_BINARY_PATH ||
    (await ensureBinary(options.licenseKey, options.browserVersion));
  const { exitIp, ...resolved } = await maybeResolveGeoip(options);
  const { proxyOption, proxyArgs } = resolveProxyConfig(options.proxy, options.browserVersion, options.licenseKey);
  let resolvedArgs = await resolveWebrtcArgs(options);
  resolvedArgs = appendWebrtcExitIp(resolvedArgs, exitIp);
  const args = buildArgs({ ...options, ...resolved, args: [...(resolvedArgs ?? []), ...proxyArgs] });
  maybeWarnWindowsFonts(args);

  // Resolve env for the browser process (license key injection, if needed).
  const { env: userEnv, ...restLaunchOptions } = options.launchOptions ?? {};
  const launchEnv = buildLaunchEnv(
    options.licenseKey,
    userEnv as Record<string, string | undefined> | undefined,
  );
  const envResult = launchEnv !== undefined ? { env: launchEnv } : {};

  return {
    executablePath: binaryPath,
    headless: options.headless ?? true,
    args,
    ignoreDefaultArgs: IGNORE_DEFAULT_ARGS,
    ...(proxyOption ? { proxy: proxyOption } : {}),
    ...restLaunchOptions,
    ...envResult,
  } as PlaywrightLaunchOptions;
}

/**
 * Apply CloakBrowser's human-like behavioral layer to an existing Playwright browser.
 */
export async function humanizeBrowser(
  browser: Browser,
  options: LaunchOptions = {}
): Promise<void> {
  if (!options.humanize) return;

  const { patchBrowser } = await import('./human/index.js');
  const { resolveConfig } = await import('./human/config.js');
  const cfg = resolveConfig(
    options.humanPreset ?? 'default',
    options.humanConfig,
  );
  patchBrowser(browser, cfg);
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
  let browser: Browser;
  try {
    browser = await chromium.launch(await buildLaunchOptions(options));
  } catch (err) {
    const lic = licenseErrorFrom(err);
    if (lic) throw lic;
    throw err;
  }
  // Headed: a bare browser.newPage() would inherit Playwright's emulated 1280x720
  // viewport -> outerWidth < innerWidth (impossible window = bot tell). Default
  // newPage()/newContext() to viewport:null so the page tracks the real window.
  // Headless on a newer binary also qualifies (coherent dimensions natively);
  // older headless keeps Playwright's default viewport. Mirrors Python launch().
  if (
    !effectiveHeadless(options) ||
    binarySupportsHeadlessNoViewport(options.licenseKey, options.browserVersion)
  ) {
    applyDefaultNoViewport(browser);
  }
  await humanizeBrowser(browser, options);
  return browser;
}

/**
 * Wrap a Browser's newContext()/newPage() to default to viewport:null (no
 * emulation) when the caller didn't specify a viewport. setdefault-style: an
 * explicit viewport (including null) is always honored. Apply before humanize's
 * patchBrowser so the wraps compose.
 */
function applyDefaultNoViewport(browser: Browser): void {
  const origNewContext = browser.newContext.bind(browser);
  (browser as any).newContext = (options?: Parameters<typeof origNewContext>[0]) =>
    origNewContext(options?.viewport === undefined ? { ...options, viewport: null } : options);

  const origNewPage = browser.newPage.bind(browser);
  (browser as any).newPage = (options?: Parameters<typeof origNewPage>[0]) =>
    origNewPage(options?.viewport === undefined ? { ...options, viewport: null } : options);
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
  launchArgs = appendWebrtcExitIp(launchArgs, exitIp);
  // --fingerprint-timezone is process-wide (reads CommandLine in renderer),
  // so it applies to ALL contexts, not just the default one.
  // locale and timezone are set via binary flags only — no CDP emulation.
  // humanize:false on the inner launch — patchContext below applies humanize
  // exactly once (else launch()'s humanizeBrowser would patch it a second time).
  const browser = await launch({ ...options, ...resolved, args: launchArgs, geoip: false, humanize: false });

  let context: BrowserContext;
  try {
    context = await browser.newContext(buildContextOptions(options));
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

  const binaryPath =
    process.env.CLOAKBROWSER_BINARY_PATH ||
    (await ensureBinary(options.licenseKey, options.browserVersion));
  const { exitIp, ...resolved } = await maybeResolveGeoip(options);
  const { proxyOption, proxyArgs } = resolveProxyConfig(options.proxy, options.browserVersion, options.licenseKey);
  let resolvedArgs = await resolveWebrtcArgs(options);
  resolvedArgs = appendWebrtcExitIp(resolvedArgs, exitIp);
  const args = buildArgs({ ...options, ...resolved, args: [...(resolvedArgs ?? []), ...proxyArgs] });
  maybeWarnWindowsFonts(args);

  seedWidevineHint(options.userDataDir, binaryPath);

  // Resolve env for the browser process (license key injection, if needed).
  const { env: userEnv, ...restLaunchOptions } = options.launchOptions ?? {};
  const launchEnv = buildLaunchEnv(
    options.licenseKey,
    userEnv as Record<string, string | undefined> | undefined,
  );
  const envResult = launchEnv !== undefined ? { env: launchEnv } : {};

  // locale and timezone are set via binary flags (--lang, --fingerprint-timezone)
  // — NOT via Playwright context kwargs which use detectable CDP emulation.
  let context: BrowserContext;
  try {
    context = await chromium.launchPersistentContext(options.userDataDir, {
      executablePath: binaryPath,
      headless: options.headless ?? true,
      args,
      ignoreDefaultArgs: IGNORE_DEFAULT_ARGS,
      ...(proxyOption ? { proxy: proxyOption } : {}),
      ...buildContextOptions(options),
      ...restLaunchOptions,
      ...envResult,
    });
  } catch (err) {
    const lic = licenseErrorFrom(err);
    if (lic) throw lic;
    throw err;
  }

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
