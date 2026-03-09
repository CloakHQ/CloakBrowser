/**
 * Puppeteer launch wrapper for cloakbrowser.
 * Alternative to the Playwright wrapper for users who prefer Puppeteer.
 */

import type { Browser } from "puppeteer-core";
import type { LaunchOptions } from "./types.js";
import { buildArgs } from "./args.js";
import { ensureBinary } from "./download.js";
import { parseProxyUrl } from "./proxy.js";
import { resolveProxyRotator } from "./proxy-rotator.js";

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
  const resolvedProxy = resolveProxyRotator(options.proxy);
  const opts = { ...options, proxy: resolvedProxy };
  const resolved = await maybeResolveGeoip(opts);
  const args = buildArgs({ ...opts, ...resolved });

  // Puppeteer handles proxy via CLI args, not a separate option.
  // Chromium's --proxy-server does NOT support inline credentials,
  // so we strip them and use page.authenticate() instead.
  let proxyAuth: { username: string; password: string } | undefined;
  if (resolvedProxy) {
    if (typeof resolvedProxy === "string") {
      const { server, username, password } = parseProxyUrl(resolvedProxy);
      args.push(`--proxy-server=${server}`);
      if (username) {
        proxyAuth = { username, password: password ?? "" };
      }
    } else {
      // Strip any inline credentials from the server URL — Chromium's
      // --proxy-server doesn't support them; use page.authenticate() instead.
      const parsed = parseProxyUrl(resolvedProxy.server);
      args.push(`--proxy-server=${parsed.server}`);
      if (resolvedProxy.bypass) {
        args.push(`--proxy-bypass-list=${resolvedProxy.bypass}`);
      }
      // Explicit username/password fields take precedence over inline creds
      const username = resolvedProxy.username ?? parsed.username;
      const password = resolvedProxy.password ?? parsed.password;
      if (username) {
        proxyAuth = { username, password: password ?? "" };
      }
    }
  }

  const browser = await puppeteer.default.launch({
    executablePath: binaryPath,
    headless: options.headless ?? true,
    args,
    ignoreDefaultArgs: ["--enable-automation"],
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

async function maybeResolveGeoip(
  options: LaunchOptions
): Promise<{ timezone?: string; locale?: string }> {
  if (!options.geoip || !options.proxy) return { timezone: options.timezone, locale: options.locale };
  if (options.timezone && options.locale) return { timezone: options.timezone, locale: options.locale };

  const { resolveProxyGeo } = await import("./geoip.js");
  const proxy = options.proxy;
  const proxyUrl = typeof proxy === "string"
    ? proxy
    : "server" in proxy ? proxy.server : undefined;
  if (!proxyUrl) return { timezone: options.timezone, locale: options.locale };
  const { timezone: geoTz, locale: geoLocale } = await resolveProxyGeo(proxyUrl);
  return {
    timezone: options.timezone ?? geoTz ?? undefined,
    locale: options.locale ?? geoLocale ?? undefined,
  };
}

