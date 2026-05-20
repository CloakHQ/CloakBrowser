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
export { launch, launchContext, launchPersistentContext, buildLaunchOptions, buildContextOptions, humanizeBrowser } from "./playwright.js";

// Binary management
export { ensureBinary, clearCache, binaryInfo, checkForUpdate } from "./download.js";

// Config
export { CHROMIUM_VERSION, getDefaultStealthArgs } from "./config.js";

// Types
export type { LaunchOptions, LaunchContextOptions, LaunchPersistentContextOptions, BinaryInfo } from "./types.js";
