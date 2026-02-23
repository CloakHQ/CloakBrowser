/**
 * Shared types for cloakbrowser launch wrappers.
 */

export interface LaunchOptions {
  /** Run in headless mode (default: true). */
  headless?: boolean;
  /** Proxy server URL, e.g. 'http://proxy:8080' or 'socks5://proxy:1080'. */
  proxy?: string;
  /** Additional Chromium CLI arguments. */
  args?: string[];
  /** Include default stealth fingerprint args (default: true). Set false to use custom --fingerprint flags. */
  stealthArgs?: boolean;
  /** Raw options passed directly to playwright/puppeteer launch(). */
  launchOptions?: Record<string, unknown>;
}

export interface LaunchContextOptions extends LaunchOptions {
  /** Custom user agent string. */
  userAgent?: string;
  /** Viewport size. */
  viewport?: { width: number; height: number };
  /** Browser locale, e.g. "en-US". */
  locale?: string;
  /** Timezone, e.g. "America/New_York". */
  timezoneId?: string;
}

export interface BinaryInfo {
  version: string;
  platform: string;
  binaryPath: string;
  installed: boolean;
  cacheDir: string;
  downloadUrl: string;
}
