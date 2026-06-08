/**
 * Puppeteer launch wrapper for cloakbrowser.
 * NOW WITH HUMANIZE SUPPORT — humanize: true enables human-like
 * mouse curves, keyboard timing, and scroll patterns (same as Playwright).
 */

import type { Browser } from "puppeteer-core";
import type { LaunchOptions } from "./types.js";
import { IGNORE_DEFAULT_ARGS } from "./config.js";
import { buildArgs } from "./args.js";
import { ensureBinary } from "./download.js";
import { isSocksProxy, normalizeHttpStringUrl, parseProxyUrl, reconstructHttpUrl, resolveProxyConfig, supportsHttpProxyInlineAuth } from "./proxy.js";
import { maybeResolveGeoip, resolveWebrtcArgs } from "./geoip.js";
import { seedWidevineHint } from "./widevine.js";

/** Resolve binary path, geoip, webrtc, and build final Chrome args. */
async function resolveArgs(options: LaunchOptions): Promise<{ binaryPath: string; args: string[] }> {
  const binaryPath = process.env.CLOAKBROWSER_BINARY_PATH || (await ensureBinary());
  const { exitIp, ...resolved } = (await maybeResolveGeoip(options)) ?? {};
  let resolvedArgs = (await resolveWebrtcArgs(options)) ?? options.args;

  if (exitIp && !(resolvedArgs ?? []).some(a => a.startsWith("--fingerprint-webrtc-ip"))) {
    resolvedArgs = [...(resolvedArgs ?? []), `--fingerprint-webrtc-ip=${exitIp}`];
  }
  return { binaryPath, args: buildArgs({ ...options, ...resolved, args: resolvedArgs }) };
}

/**
 * Resolve proxy into Chrome CLI args and optional HTTP auth credentials.
 * SOCKS5: Chrome handles inline credentials natively (RFC 1929 auth).
 * HTTP on supported platforms: inline credentials via --proxy-server.
 * HTTP on unsupported platforms: strip credentials, use page.authenticate() fallback.
 */
function resolveProxy(options: LaunchOptions, args: string[]): { username: string; password: string } | undefined {
  if (!options.proxy) return undefined;

  if (isSocksProxy(options.proxy)) {
    const { proxyArgs } = resolveProxyConfig(options.proxy);
    args.push(...proxyArgs);
    return undefined;
  }

  // On supported platforms: pass full URL with inline creds to --proxy-server
  if (supportsHttpProxyInlineAuth()) {
    if (typeof options.proxy === "string") {
      args.push(`--proxy-server=${normalizeHttpStringUrl(options.proxy)}`);
      return undefined;
    }
    const url = options.proxy.username
      ? reconstructHttpUrl(options.proxy)
      : options.proxy.server;
    args.push(`--proxy-server=${url}`);
    if (options.proxy.bypass) {
      args.push(`--proxy-bypass-list=${options.proxy.bypass}`);
    }
    return undefined;
  }

  // Unsupported platform: strip credentials, fall back to page.authenticate()
  if (typeof options.proxy === "string") {
    const { server, username, password } = parseProxyUrl(options.proxy);
    args.push(`--proxy-server=${server}`);
    return username ? { username, password: password ?? "" } : undefined;
  }

  const parsed = parseProxyUrl(options.proxy.server);
  args.push(`--proxy-server=${parsed.server}`);
  if (options.proxy.bypass) {
    args.push(`--proxy-bypass-list=${options.proxy.bypass}`);
  }
  const username = options.proxy.username ?? parsed.username;
  const password = options.proxy.password ?? parsed.password;
  return username ? { username, password: password ?? "" } : undefined;
}

/** Apply proxy auth fallback (unsupported platforms) and humanize patching. */
async function applyPostLaunch(
  browser: Browser,
  options: LaunchOptions,
  proxyAuth?: { username: string; password: string },
): Promise<void> {
  if (proxyAuth) {
    const origNewPage = browser.newPage.bind(browser);
    const auth = proxyAuth;
    browser.newPage = async (...pageArgs: Parameters<typeof origNewPage>) => {
      const page = await origNewPage(...pageArgs);
      await page.authenticate(auth);
      return page;
    };
  }

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
  const proxyAuth = resolveProxy(options, args);

  const browser = await puppeteer.default.launch({
    ...options.launchOptions,
    executablePath: binaryPath,
    headless: options.headless ?? true,
    args,
    ignoreDefaultArgs: IGNORE_DEFAULT_ARGS,
  });

  await applyPostLaunch(browser, options, proxyAuth);
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
  const proxyAuth = resolveProxy(options, args);

  seedWidevineHint(options.userDataDir, binaryPath);

  const browser = await puppeteer.default.launch({
    ...options.launchOptions,
    executablePath: binaryPath,
    headless: options.headless ?? true,
    args,
    ignoreDefaultArgs: IGNORE_DEFAULT_ARGS,
    userDataDir: options.userDataDir,
  });

  await applyPostLaunch(browser, options, proxyAuth);
  return browser;
}
