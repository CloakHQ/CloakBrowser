/**
 * Shared argument builder for Playwright and Puppeteer wrappers.
 */
import path from "path";
import type { LaunchOptions } from "./types.js";
import { getDefaultStealthArgs } from "./config.js";

const DEBUG = /\bcloakbrowser\b/.test(process.env.DEBUG ?? "");

/**
 * Build deduplicated Chromium CLI args from stealth defaults + user overrides.
 *
 * Priority: stealth defaults < user args < dedicated params (timezone/locale).
 */
export function buildArgs(options: LaunchOptions): string[] {
  const seen = new Map<string, string>();

  if (options.stealthArgs !== false) {
    for (const arg of getDefaultStealthArgs()) {
      seen.set(arg.split("=")[0], arg);
    }
  }
  // GPU blocklist bypass:
  // - Headed mode (all platforms): Chromium blocks WebGL on software GPUs
  //   in Docker/Xvfb. Flag lets SwiftShader serve WebGL. See issue #56.
  // - Windows (all modes): Chromium's GPU blocklist blocks WebGPU for the
  //   Microsoft Basic Render Driver. Dawn's adapter_blocklist bypass alone
  //   isn't enough. Linux doesn't need it.
  if (options.headless === false || process.platform === "win32") {
    seen.set("--ignore-gpu-blocklist", "--ignore-gpu-blocklist");
  }
  if (options.args) {
    for (const arg of options.args) {
      const key = arg.split("=")[0];
      if (seen.has(key)) {
        if (DEBUG) console.debug(`[cloakbrowser] Arg override: ${seen.get(key)} -> ${arg}`);
      }
      seen.set(key, arg);
    }
  }
  if (options.timezone) {
    const key = "--fingerprint-timezone";
    const flag = `${key}=${options.timezone}`;
    if (seen.has(key)) {
      if (DEBUG) console.debug(`[cloakbrowser] Arg override: ${seen.get(key)} -> ${flag}`);
    }
    seen.set(key, flag);
  }
  if (options.locale) {
    for (const k of ["--lang", "--fingerprint-locale"] as const) {
      const flag = `${k}=${options.locale}`;
      if (seen.has(k)) {
        if (DEBUG) console.debug(`[cloakbrowser] Arg override: ${seen.get(k)} -> ${flag}`);
      }
      seen.set(k, flag);
    }
  }

  if (options.extensionPaths?.length) {
    const absPaths = options.extensionPaths.map(p => path.resolve(p));
    const joined = absPaths.join(",");

    seen.set("--load-extension", `--load-extension=${joined}`);
    seen.set(
      "--disable-extensions-except",
      `--disable-extensions-except=${joined}`
    );
  }
  return [...seen.values()];
}
