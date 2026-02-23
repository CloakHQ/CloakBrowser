/**
 * CloakBrowser — Stealth Chromium for Node.js
 *
 * Default export uses Playwright. For Puppeteer, import from 'cloakbrowser/puppeteer'.
 *
 * @example
 * ```ts
 * // Playwright (default)
 * import { launch } from 'cloakbrowser';
 * const browser = await launch();
 *
 * // Puppeteer
 * import { launch } from 'cloakbrowser/puppeteer';
 * const browser = await launch();
 * ```
 */

// Launch functions (Playwright API)
export { launch, launchContext } from "./playwright.js";

// Binary management
export { ensureBinary, clearCache, binaryInfo } from "./download.js";

// Config
export { CHROMIUM_VERSION, getDefaultStealthArgs } from "./config.js";

// Types
export type { LaunchOptions, LaunchContextOptions, BinaryInfo } from "./types.js";
