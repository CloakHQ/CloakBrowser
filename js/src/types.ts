/**
 * Shared types for cloakbrowser launch wrappers.
 */

export interface LaunchOptions {
  /** Run in headless mode (default: true). */
  headless?: boolean;
  /**
   * Proxy server — URL string or Playwright proxy object.
   * String: 'http://user:pass@proxy:8080' (credentials auto-extracted).
   * Object: { server: "http://proxy:8080", bypass: ".google.com", ... }
   *   — passed directly to Playwright.
   */
  proxy?: string | { server: string; bypass?: string; username?: string; password?: string };
  /** Additional Chromium CLI arguments. */
  args?: string[];
  /** Include default stealth fingerprint args (default: true). Set false to use custom --fingerprint flags. */
  stealthArgs?: boolean;
  /** IANA timezone, e.g. "America/New_York". Sets --fingerprint-timezone binary flag. */
  timezone?: string;
  /** BCP 47 locale, e.g. "en-US". Sets --lang binary flag. */
  locale?: string;
  /** Auto-detect timezone/locale from proxy IP (requires: npm install mmdb-lib). */
  geoip?: boolean;
  /** Raw options passed directly to playwright/puppeteer launch(). */
  launchOptions?: Record<string, unknown>;
  /** Enable human-like mouse, keyboard, and scroll behavior. */
  humanize?: boolean;
  /** Human behavior preset: 'default' or 'careful'. */
  humanPreset?: 'default' | 'careful';
  /** Override individual human behavior parameters. */
  humanConfig?: Record<string, unknown>;
}

export interface LaunchContextOptions extends LaunchOptions {
  /** Custom user agent string. */
  userAgent?: string;
  /** Viewport size. */
  viewport?: { width: number; height: number };
  /** Browser locale, e.g. "en-US". */
  locale?: string;
  /** @deprecated Use `timezone` (inherited from LaunchOptions) instead. */
  timezoneId?: string;
  /** Color scheme preference — 'light', 'dark', or 'no-preference'. */
  colorScheme?: "light" | "dark" | "no-preference";
}

export interface LaunchPersistentContextOptions extends LaunchContextOptions {
  /** Path to user data directory for persistent profile. */
  userDataDir: string;
}

export interface BinaryInfo {
  version: string;
  platform: string;
  binaryPath: string;
  installed: boolean;
  cacheDir: string;
  downloadUrl: string;
}
