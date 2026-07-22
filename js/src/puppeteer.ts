/**
 * Puppeteer launch wrapper for cloakbrowser.
 * NOW WITH HUMANIZE SUPPORT — humanize: true enables human-like
 * mouse curves, keyboard timing, and scroll patterns (same as Playwright).
 */

import type { Browser } from "puppeteer-core";
import type { LaunchOptions, ConnectOptions } from "./types.js";
import {
  DEFAULT_VIEWPORT,
  IGNORE_DEFAULT_ARGS,
  binarySupportsHeadlessNoViewport,
  binarySupportsHttpProxyInlineAuth,
} from "./config.js";
import { buildArgs } from "./args.js";
import { maybeWarnWindowsFonts } from "./fonts.js";
import { ensureBinary } from "./download.js";
import { isSocksProxy, normalizeHttpStringUrl, parseProxyUrl, reconstructHttpUrl, resolveProxyConfig } from "./proxy.js";
import { maybeResolveGeoip, resolveWebrtcArgs, appendWebrtcExitIp } from "./geoip.js";
import { buildLaunchEnv, licenseErrorFrom } from "./license.js";
import { seedWidevineHint } from "./widevine.js";

export { CloakBrowserLicenseError } from "./license.js";

/**
 * Resolve Puppeteer's defaultViewport. Headed -> null (track the real window so
 * outerWidth >= innerWidth stays coherent; Puppeteer otherwise forces an 800x600
 * emulated viewport = a physically impossible window = bot tell). Headless has no
 * window chrome (outer == inner), so a fixed viewport stays coherent and keeps
 * dimensions deterministic. A user-supplied launchOptions.defaultViewport wins.
 */
function resolveDefaultViewport(options: LaunchOptions): { width: number; height: number } | null {
  const launchOpts = (options.launchOptions ?? {}) as Record<string, unknown>;
  // A user-supplied defaultViewport wins (incl. explicit null). undefined is NOT
  // "supplied" — fall through to our default. Puppeteer sets `headless` AFTER the
  // launchOptions spread, so the top-level field wins at launch — match it here.
  if (launchOpts.defaultViewport !== undefined) {
    return launchOpts.defaultViewport as { width: number; height: number } | null;
  }
  const headless = options.headless ?? true;
  // Headed and newer headless binaries: null (no emulation, coherent dimensions).
  // Older headless binaries: a fixed viewport keeps dimensions coherent.
  if (!headless || binarySupportsHeadlessNoViewport(options.licenseKey, options.browserVersion)) {
    return null;
  }
  return DEFAULT_VIEWPORT;
}

/** Resolve binary path, geoip, webrtc, and build final Chrome args. */
async function resolveArgs(options: LaunchOptions): Promise<{ binaryPath: string; args: string[] }> {
  const binaryPath =
    process.env.CLOAKBROWSER_BINARY_PATH ||
    (await ensureBinary(options.licenseKey, options.browserVersion));
  const { exitIp, ...resolved } = (await maybeResolveGeoip(options)) ?? {};
  let resolvedArgs = (await resolveWebrtcArgs(options)) ?? options.args;

  resolvedArgs = appendWebrtcExitIp(resolvedArgs, exitIp);
  const args = buildArgs({ ...options, ...resolved, args: resolvedArgs });
  maybeWarnWindowsFonts(args);
  return { binaryPath, args };
}

/**
 * Resolve proxy into Chrome CLI args and optional HTTP auth credentials.
 * SOCKS5: Chrome handles inline credentials natively (RFC 1929 auth).
 * HTTP on binaries with inline proxy auth: inline credentials via --proxy-server.
 * HTTP on older binaries (free macOS/linux-arm64): strip credentials, use
 * page.authenticate() fallback.
 */
function resolveProxy(options: LaunchOptions, args: string[]): { username: string; password: string } | undefined {
  if (!options.proxy) return undefined;

  if (isSocksProxy(options.proxy)) {
    const { proxyArgs } = resolveProxyConfig(options.proxy, options.browserVersion);
    args.push(...proxyArgs);
    return undefined;
  }

  // On binaries that ship inline proxy auth: pass full URL with inline creds.
  if (binarySupportsHttpProxyInlineAuth(options.licenseKey, options.browserVersion)) {
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

  // Older binary: strip credentials, fall back to page.authenticate()
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

/** Apply proxy auth fallback (older binaries) and humanize patching. */
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

  // Resolve env for the browser process (license key injection, if needed).
  const { env: userEnv, ...restLaunchOptions } = options.launchOptions ?? {};
  const launchEnv = buildLaunchEnv(
    options.licenseKey,
    userEnv as Record<string, string | undefined> | undefined,
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
    const lic = licenseErrorFrom(err);
    if (lic) throw lic;
    throw err;
  }

  await applyPostLaunch(browser, options, proxyAuth);
  return browser;
}

/**
 * Connect to an already-running CloakBrowser instance over CDP via Puppeteer
 * (e.g. one started via cloakserve in Docker) and apply the humanize behavioral
 * layer. Accepts an http(s):// endpoint (Puppeteer resolves the ws URL from
 * /json/version) or a ws(s):// endpoint directly.
 *
 * The C++ fingerprint patches live in the running binary and persist across the
 * connection; select a fingerprint via the endpoint URL's query string
 * (e.g. "http://host:9222?fingerprint=12345"). `browser.disconnect()` detaches
 * from the remote instance; it does not terminate it.
 *
 * @example
 * ```ts
 * import { connect } from 'cloakbrowser/puppeteer';
 * const browser = await connect('http://localhost:9222', { humanize: true });
 * const page = await browser.newPage();
 * await page.goto('https://example.com');
 * await browser.disconnect();
 * ```
 */
export async function connect(
  endpoint: string,
  options: ConnectOptions = {}
): Promise<Browser> {
  const puppeteer = await import("puppeteer-core");
  const target = /^wss?:\/\//i.test(endpoint)
    ? { browserWSEndpoint: endpoint }
    : { browserURL: endpoint };
  const browser = await puppeteer.default.connect({
    ...target,
    // null disables Puppeteer's 800x600 emulated viewport (bot tell); undefined
    // keeps its default. defaultNoViewport defaults to true.
    defaultViewport: options.defaultNoViewport === false ? undefined : null,
    ...(options.connectOptions ?? {}),
  });

  if (options.humanize) {
    const { patchBrowser } = await import('./human-puppeteer/index.js');
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

  // Resolve env for the browser process (license key injection, if needed).
  const { env: userEnv, ...restLaunchOptions } = options.launchOptions ?? {};
  const launchEnv = buildLaunchEnv(
    options.licenseKey,
    userEnv as Record<string, string | undefined> | undefined,
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
    const lic = licenseErrorFrom(err);
    if (lic) throw lic;
    throw err;
  }

  await applyPostLaunch(browser, options, proxyAuth);
  return browser;
}
