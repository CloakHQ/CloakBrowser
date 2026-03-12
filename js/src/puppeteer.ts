/**
 * Puppeteer launch wrapper for cloakbrowser.
 * Alternative to the Playwright wrapper for users who prefer Puppeteer.
 */

import type { Browser } from "puppeteer-core";
import type { LaunchOptions } from "./types.js";
import { IGNORE_DEFAULT_ARGS } from "./config.js";
import { buildArgs } from "./args.js";
import { ensureBinary } from "./download.js";
import { parseProxyUrl } from "./proxy.js";
import { maybeResolveGeoip } from "./geoip.js";

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
  const resolved = await maybeResolveGeoip(options);
  const args = buildArgs({ ...options, ...resolved });

  // Puppeteer handles proxy via CLI args, not a separate option.
  // Chromium's --proxy-server does NOT support inline credentials,
  // so we strip them and use page.authenticate() instead.
  let proxyAuth: { username: string; password: string } | undefined;
  if (options.proxy) {
    if (typeof options.proxy === "string") {
      const { server, username, password } = parseProxyUrl(options.proxy);
      args.push(`--proxy-server=${server}`);
      if (username) {
        proxyAuth = { username, password: password ?? "" };
      }
    } else {
      // Strip any inline credentials from the server URL — Chromium's
      // --proxy-server doesn't support them; use page.authenticate() instead.
      const parsed = parseProxyUrl(options.proxy.server);
      args.push(`--proxy-server=${parsed.server}`);
      if (options.proxy.bypass) {
        args.push(`--proxy-bypass-list=${options.proxy.bypass}`);
      }
      // Explicit username/password fields take precedence over inline creds
      const username = options.proxy.username ?? parsed.username;
      const password = options.proxy.password ?? parsed.password;
      if (username) {
        proxyAuth = { username, password: password ?? "" };
      }
    }
  }

  const browser = await puppeteer.default.launch({
    executablePath: binaryPath,
    headless: options.headless ?? true,
    args,
    ignoreDefaultArgs: IGNORE_DEFAULT_ARGS,
    ...options.launchOptions,
  });

  // Monkey-patch newPage() to auto-authenticate proxy credentials
  if (proxyAuth) {
    const origNewPage = browser.newPage.bind(browser);
    const auth = proxyAuth;
    browser.newPage = async (...pageArgs: Parameters<typeof origNewPage>) => {
      const page = await origNewPage(...pageArgs);
      await page.authenticate(auth);
      return page;
    };
  }

  return browser;
}

// ---------------------------------------------------------------------------
// Internal
// ---------------------------------------------------------------------------

