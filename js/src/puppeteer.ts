/**
 * Puppeteer launch wrapper for cloakbrowser.
 * NOW WITH HUMANIZE SUPPORT — humanize: true enables human-like
 * mouse curves, keyboard timing, and scroll patterns (same as Playwright).
 */

import type { Browser } from "puppeteer-core";
import type { LaunchOptions } from "./types.js";
import { IGNORE_DEFAULT_ARGS } from "./config.js";
import { buildArgs } from "./args.js";
import { maybeWarnWindowsFonts } from "./fonts.js";
import { ensureBinary } from "./download.js";
import { isSocksProxy, normalizeHttpStringUrl, reconstructHttpUrl, resolveProxyConfig } from "./proxy.js";
import { maybeResolveGeoip, resolveWebrtcArgs, appendWebrtcExitIp } from "./geoip.js";
import {
  buildLaunchEnv,
  installLicenseGuard,
  licenseErrorFrom,
  mintDenialFile,
  resolveLicenseKey,
} from "./license.js";
import { seedWidevineHint } from "./widevine.js";
import { persistentSeedArgs } from "./profile-seed.js";

export { CloakBrowserLicenseError } from "./license.js";

/**
 * Resolve Puppeteer's defaultViewport: null (no emulation) unless the user
 * supplied one. Headed, the page tracks the real window (Puppeteer otherwise
 * forces an 800x600 viewport = outerWidth < innerWidth = bot tell); headless,
 * the binary reports coherent dimensions itself.
 */
function resolveDefaultViewport(options: LaunchOptions): { width: number; height: number } | null {
  const launchOpts = (options.launchOptions ?? {}) as Record<string, unknown>;
  // A user-supplied defaultViewport wins (incl. explicit null). undefined is NOT
  // "supplied" — fall through to our default.
  if (launchOpts.defaultViewport !== undefined) {
    return launchOpts.defaultViewport as { width: number; height: number } | null;
  }
  return null;
}

/** Resolve binary path, geoip, webrtc, and build final Chrome args. */
async function resolveArgs(
  options: LaunchOptions & { userDataDir?: string },
): Promise<{ binaryPath: string; args: string[] }> {
  const binaryPath =
    process.env.CLOAKBROWSER_BINARY_PATH ||
    (await ensureBinary(
      options.licenseKey,
      options.browserVersion,
      options.releaseChannel,
    ));
  const { exitIp, ...resolved } = (await maybeResolveGeoip(options)) ?? {};
  let resolvedArgs = (await resolveWebrtcArgs(options)) ?? options.args;

  resolvedArgs = appendWebrtcExitIp(resolvedArgs, exitIp);
  // Only launchPersistentContext passes userDataDir; plain launch() stays random.
  resolvedArgs = persistentSeedArgs(options.userDataDir, options.stealthArgs, resolvedArgs);
  const args = buildArgs({ ...options, ...resolved, args: resolvedArgs });
  maybeWarnWindowsFonts(args);
  return { binaryPath, args };
}

/**
 * Resolve proxy into Chrome CLI args. Credentials go inline via --proxy-server:
 * SOCKS5 natively (RFC 1929), HTTP through the binary's inline proxy auth.
 */
function resolveProxy(options: LaunchOptions, args: string[]): void {
  if (!options.proxy) return;

  if (isSocksProxy(options.proxy)) {
    args.push(...resolveProxyConfig(options.proxy).proxyArgs);
    return;
  }
  if (typeof options.proxy === "string") {
    args.push(`--proxy-server=${normalizeHttpStringUrl(options.proxy)}`);
    return;
  }
  const url = options.proxy.username
    ? reconstructHttpUrl(options.proxy)
    : options.proxy.server;
  args.push(`--proxy-server=${url}`);
  if (options.proxy.bypass) {
    args.push(`--proxy-bypass-list=${options.proxy.bypass}`);
  }
}

/** Apply humanize patching. */
async function applyPostLaunch(browser: Browser, options: LaunchOptions): Promise<void> {
  if (options.humanize) {
    const { patchBrowser } = await import('./human-puppeteer/index.js');
    const { resolveConfig } = await import('./human/config.js');
    const cfg = resolveConfig(
      options.humanPreset ?? 'default',
      options.humanConfig,
    );
    patchBrowser(browser, cfg);
  }
}

/**
 * Launch stealth Chromium browser via Puppeteer.
 *
 * @example
 * ```ts
 * import { launch } from 'cloakbrowser/puppeteer';
 * // With humanize — human-like mouse, keyboard, scroll
 * const browser = await launch({ humanize: true });
 * const page = await browser.newPage();
 * await page.goto('https://example.com');
 * await page.click('#login');  // Bézier curve mouse movement
 * await page.type('#email', 'user@example.com');  // Per-character timing
 * ```
 */
export async function launch(options: LaunchOptions = {}): Promise<Browser> {
  const puppeteer = await import("puppeteer-core");
  const { binaryPath, args } = await resolveArgs(options);
  resolveProxy(options, args);

  // Resolve env for the browser process (license key injection, if needed).
  const denialPath = resolveLicenseKey(options.licenseKey) ? mintDenialFile() : undefined;
  const { env: userEnv, ...restLaunchOptions } = options.launchOptions ?? {};
  const launchEnv = buildLaunchEnv(
    options.licenseKey,
    userEnv as Record<string, string | undefined> | undefined,
    denialPath,
  );
  const envResult = launchEnv !== undefined ? { env: launchEnv } : {};

  let browser;
  try {
    browser = await puppeteer.default.launch({
      ...restLaunchOptions,
      executablePath: binaryPath,
      headless: options.headless ?? true,
      args,
      ignoreDefaultArgs: IGNORE_DEFAULT_ARGS,
      defaultViewport: resolveDefaultViewport(options),
      ...envResult,
    });
  } catch (err) {
    const lic = licenseErrorFrom(err, denialPath);
    if (lic) throw lic;
    throw err;
  }

  // Convert a post-handshake license denial into a clear error on first use.
  // Installed before applyPostLaunch so it sits closest to the real call.
  if (denialPath) {
    // Guarding the browser deeply covers newPage AND the context factories
    // (createBrowserContext) and every page/context they hand back — so a user
    // who creates their own context is covered too.
    installLicenseGuard(browser, denialPath);
  }
  await applyPostLaunch(browser, options);
  return browser;
}

/**
 * Launch stealth Chromium with a persistent user profile via Puppeteer.
 * Passes `userDataDir` to Puppeteer's launch options so cookies,
 * localStorage, and session data persist across launches.
 *
 * @example
 * ```ts
 * import { launchPersistentContext } from 'cloakbrowser/puppeteer';
 * const browser = await launchPersistentContext({
 *   userDataDir: './chrome-profile',
 *   headless: false,
 *   proxy: 'http://user:pass@proxy:8080',
 * });
 * const page = await browser.newPage();
 * await page.goto('https://example.com');
 * await browser.close();
 * ```
 */
export async function launchPersistentContext(
  options: LaunchOptions & { userDataDir: string }
): Promise<Browser> {
  const puppeteer = await import("puppeteer-core");
  const { binaryPath, args } = await resolveArgs(options);
  resolveProxy(options, args);

  seedWidevineHint(options.userDataDir, binaryPath);

  // Resolve env for the browser process (license key injection, if needed).
  const denialPath = resolveLicenseKey(options.licenseKey) ? mintDenialFile() : undefined;
  const { env: userEnv, ...restLaunchOptions } = options.launchOptions ?? {};
  const launchEnv = buildLaunchEnv(
    options.licenseKey,
    userEnv as Record<string, string | undefined> | undefined,
    denialPath,
  );
  const envResult = launchEnv !== undefined ? { env: launchEnv } : {};

  let browser;
  try {
    browser = await puppeteer.default.launch({
      ...restLaunchOptions,
      executablePath: binaryPath,
      headless: options.headless ?? true,
      args,
      ignoreDefaultArgs: IGNORE_DEFAULT_ARGS,
      userDataDir: options.userDataDir,
      defaultViewport: resolveDefaultViewport(options),
      ...envResult,
    });
  } catch (err) {
    const lic = licenseErrorFrom(err, denialPath);
    if (lic) throw lic;
    throw err;
  }

  // Guard the browser deeply for a post-handshake denial (see launch()).
  if (denialPath) {
    installLicenseGuard(browser, denialPath);
    // A persistent browser arrives with a page already open, so the user drives
    // pages()[0] directly and never calls newPage. Guard those existing pages
    // too. Mirrors Python / Playwright wrapper.
    for (const pg of await browser.pages()) {
      installLicenseGuard(pg, denialPath);
    }
  }
  await applyPostLaunch(browser, options);
  return browser;
}
