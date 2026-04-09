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
import { parseProxyUrl } from "./proxy.js";
import { maybeResolveGeoip, resolveWebrtcArgs } from "./geoip.js";

/**
 * Launch stealth Chromium browser via Puppeteer.
 *
 * @example
 * ```ts
 * import { launch } from 'cloakbrowser/puppeteer';
 * * // With humanize — human-like mouse, keyboard, scroll
 * const browser = await launch({ humanize: true });
 * const page = await browser.newPage();
 * await page.goto('[https://example.com](https://example.com)');
 * await page.click('#login');  // Bézier curve mouse movement
 * await page.type('#email', 'user@example.com');  // Per-character timing
 * ```
 */
export async function launch(options: LaunchOptions = {}): Promise<Browser> {
  const puppeteer = await import("puppeteer-core");

  const binaryPath = process.env.CLOAKBROWSER_BINARY_PATH || (await ensureBinary());
  const { exitIp, ...resolved } = (await maybeResolveGeoip(options)) ?? {};
  let resolvedArgs = (await resolveWebrtcArgs(options)) ?? options.args;
  
  if (exitIp && !(resolvedArgs ?? []).some(a => a.startsWith("--fingerprint-webrtc-ip"))) {
    resolvedArgs = [...(resolvedArgs ?? []), `--fingerprint-webrtc-ip=${exitIp}`];
  }
  const args = buildArgs({ ...options, ...resolved, args: resolvedArgs });

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

  // Human-like behavioral patching — FULL coverage, same as Playwright.
  // This enables Bézier mouse movements, organic typing rhythms, and 
  // natural scrolling to bypass advanced anti-bot detection.
  if (options.humanize) {
    const { patchBrowser } = await import('./human-puppeteer/index.js');
    const { resolveConfig } = await import('./human/config.js');
    const cfg = resolveConfig(
      (options.humanPreset as any) ?? 'default',
      options.humanConfig as any,
    );
    patchBrowser(browser, cfg);
  }

  return browser;
}
