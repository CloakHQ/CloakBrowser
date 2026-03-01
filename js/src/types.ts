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
  /** IANA timezone, e.g. "America/New_York". Sets --timezone binary flag. */
  timezone?: string;
  /** BCP 47 locale, e.g. "en-US". Sets --lang binary flag. */
  locale?: string;
  /** Auto-detect timezone/locale from proxy IP (requires: npm install mmdb-lib). */
  geoip?: boolean;
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
  /** Color scheme preference — 'light', 'dark', or 'no-preference'. */
  colorScheme?: "light" | "dark" | "no-preference";
}

export interface BinaryInfo {
  version: string;
  platform: string;
  binaryPath: string;
  installed: boolean;
  cacheDir: string;
  downloadUrl: string;
}
