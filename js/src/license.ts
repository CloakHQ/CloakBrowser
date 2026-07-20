/**
 * License validation and caching for CloakBrowser Pro.
 * Mirrors Python cloakbrowser/license.py.
 *
 * Handles license key resolution, server validation with local caching,
 * and Pro version checks.
 */

import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { getCacheDir, getPlatformTag } from "./config.js";

const VALIDATE_URL = "https://cloakbrowser.dev/api/license/validate";
const PRO_VERSION_URL = "https://cloakbrowser.dev/api/download/version";
const SESSION_COUNT_URL = "https://cloakbrowser.dev/api/license/session/count";

const LICENSE_CACHE_TTL_MS = 86_400_000; // 24 hours
const PRO_VERSION_CHECK_INTERVAL_MS = 3_600_000; // 1 hour

export interface LicenseInfo {
  valid: boolean;
  plan: string;
  expires: string | null;
}

/**
 * The Pro binary refused to run for a license reason. Thrown when a launch
 * fails and the browser process exited with one of the Pro binary's license
 * exit codes, carrying a human-readable reason instead of the opaque
 * "target/browser closed" error the caller would otherwise see.
 */
export class CloakBrowserLicenseError extends Error {
  constructor(message: string, options?: { cause?: unknown }) {
    super(message, options);
    this.name = "CloakBrowserLicenseError";
  }
}

// Exit codes the Pro binary uses for honest-user license denials. The binary
// emits only the number (no diagnostic strings, by design); the message text
// lives here in the wrapper. Mirrors Python _LICENSE_EXIT_MESSAGES.
const LICENSE_EXIT_MESSAGES: Record<number, string> = {
  76: "CloakBrowser Pro: session limit reached for your plan. Close another running session or upgrade your plan.",
  77: "CloakBrowser Pro: license key is invalid, expired, or missing. Check CLOAKBROWSER_LICENSE_KEY.",
  78: "CloakBrowser Pro: couldn't verify your license (license server unreachable or a connection problem).",
  79: "CloakBrowser Pro: local configuration problem, ~/.cloakbrowser is not writable.",
};

// Playwright embeds the child-process exit as "<process did exit: exitCode=N, ...>".
// Puppeteer surfaces it as "Browser process exited with code N" / "with exit code N".
// Anchored so an unrelated "exitCode=" elsewhere in the error can't false-match.
const EXIT_CODE_PATTERNS = [
  /process did exit:\s*exitCode=(\d+)/,
  /exited with (?:exit )?code (\d+)/i,
];

/**
 * Map a launch-failure message to a license reason, or null. Returns the human
 * message when the browser process exited with a known license exit code, else
 * null so a genuine crash propagates unchanged.
 */
export function licenseErrorMessage(errorText: string): string | null {
  const text = errorText || "";
  for (const re of EXIT_CODE_PATTERNS) {
    const match = text.match(re);
    if (match) {
      const msg = LICENSE_EXIT_MESSAGES[Number(match[1])];
      if (msg) return msg;
    }
  }
  return null;
}

/**
 * Return a CloakBrowserLicenseError if a launch failure was a license deny,
 * else null so the original error propagates unchanged.
 */
export function licenseErrorFrom(err: unknown): CloakBrowserLicenseError | null {
  const text = err instanceof Error ? err.message : String(err);
  const msg = licenseErrorMessage(text);
  return msg !== null ? new CloakBrowserLicenseError(msg, { cause: err }) : null;
}

/**
 * Source of a resolved license key.  Determines whether env injection
 * into the child browser process is needed.
 *
 * - ``param`` / ``custom_file`` -> must inject (binary can't see these).
 * - ``env`` -> already in parent ``os.environ``, child inherits naturally.
 * - ``default_file`` -> binary reads ``~/.cloakbrowser/license.key`` directly.
 * - ``none`` / ``undefined`` -> no key.
 */
export type LicenseKeySource =
  | "param"
  | "env"
  | "default_file"
  | "custom_file"
  | "none";

/**
 * Like ``resolveLicenseKey`` but also returns the source for env-injection
 * decisions.  Internal; consumers should use ``resolveLicenseKey`` or
 * ``buildLaunchEnv``.
 */
export function resolveLicenseKeyWithSource(
  licenseKey?: string,
): { key: string | undefined; source: LicenseKeySource } {
  const trimmed = licenseKey?.trim();
  if (trimmed) return { key: trimmed, source: "param" };

  const envKey = (process.env.CLOAKBROWSER_LICENSE_KEY ?? "").trim();
  if (envKey) return { key: envKey, source: "env" };

  try {
    const cacheDir = getCacheDir();
    const keyFile = path.join(cacheDir, "license.key");
    const content = fs.readFileSync(keyFile, "utf-8").trim();
    if (content) {
      const defaultCache = path.join(os.homedir(), ".cloakbrowser");
      // Symlink-safe comparison via resolve()
      const source =
        path.resolve(cacheDir) === path.resolve(defaultCache)
          ? "default_file"
          : "custom_file";
      return { key: content, source };
    }
  } catch {
    // File doesn't exist or unreadable
  }

  return { key: undefined, source: "none" };
}

/**
 * Resolve the license key: explicit param > env var > file > undefined.
 */
export function resolveLicenseKey(licenseKey?: string): string | undefined {
  return resolveLicenseKeyWithSource(licenseKey).key;
}

/**
 * Build a child-process env dict with any needed license key injection.
 *
 * The Pro binary reads ``CLOAKBROWSER_LICENSE_KEY`` from its own process
 * environment at startup.  This helper merges the resolved key into the
 * child process env dict **only** when injection is necessary:
 *
 * * **param** / **custom_file** source -> inject into child env.
 * * **env** source -> child inherits from parent (no injection).
 * * **default_file** source -> binary reads the file directly (no injection),
 *   unless a custom userEnv is passed (Playwright replaces the child env and
 *   can drop HOME, hiding the file), in which case the key is injected.
 *
 * When *userEnv* is provided it is used as the base (Playwright replaces
 * the child env entirely when ``env`` is set), with the key injected only
 * when needed.
 *
 * Returns ``undefined`` when no injection is needed and no custom userEnv
 * was given — Playwright treats ``env=undefined`` as "inherit parent env".
 */
export function buildLaunchEnv(
  licenseKey?: string,
  userEnv?: Record<string, string | undefined>,
): Record<string, string> | undefined {
  const { key, source } = resolveLicenseKeyWithSource(licenseKey);

  // Normalize the custom env once so every return path behaves identically:
  // drop undefined values (Playwright's env is typed string→string).
  const baseEnv = userEnv
    ? (Object.fromEntries(
        Object.entries(userEnv).filter(([, v]) => v !== undefined),
      ) as Record<string, string>)
    : undefined;

  // Default file: binary reads it directly — no env injection needed,
  // UNLESS the caller passes a custom env. Playwright replaces (not merges)
  // the child env, which can drop HOME and hide the file from the binary,
  // so inject the key too in that case (fall through to the merge below).
  if (source === "default_file" && !baseEnv) {
    return undefined;
  }

  // No key at all: pass through the custom env or undefined.
  if (source === "none" || key === undefined) {
    return baseEnv;
  }

  // Env source, no custom user env: child inherits parent env, which
  // already has CLOAKBROWSER_LICENSE_KEY.
  if (source === "env" && !baseEnv) {
    return undefined;
  }

  // Build the merged env dict.
  const merged: Record<string, string> = {};

  if (baseEnv) {
    Object.assign(merged, baseEnv);
  } else {
    for (const [k, v] of Object.entries(process.env)) {
      if (v !== undefined) merged[k] = v;
    }
  }

  // For param/custom_file this is THE injection into the child env.
  // For env source with a custom userEnv this ensures the key persists
  // through the user's env override (Playwright replaces, not merges).
  merged.CLOAKBROWSER_LICENSE_KEY = key;

  return merged;
}

/**
 * Validate a license key with the CloakBrowser server.
 *
 * Checks a local file cache first (24h TTL). Falls back to stale
 * cache if the server is unreachable.
 *
 * Returns LicenseInfo if validation succeeded, null on total failure.
 */
export async function validateLicense(licenseKey: string): Promise<LicenseInfo | null> {
  const cachePath = path.join(getCacheDir(), ".license_cache");
  const keySha = createHash("sha256").update(licenseKey).digest("hex");

  const cached = readCache(cachePath, keySha);
  if (cached) return cached;

  try {
    const resp = await fetch(VALIDATE_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ license_key: licenseKey }),
      signal: AbortSignal.timeout(10_000),
    });

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
    }

    const data = (await resp.json()) as Record<string, unknown>;

    const info: LicenseInfo = {
      valid: Boolean(data.valid ?? false),
      plan: String(data.plan ?? "solo"),
      expires: data.expires != null ? String(data.expires) : null,
    };

    if (info.valid) {
      writeCache(cachePath, keySha, info);
    }
    return info;
  } catch (e) {
    console.warn(
      `[cloakbrowser] License validation request failed: ${e instanceof Error ? e.message : e}`
    );

    // Fall back to stale cache
    const stale = readCache(cachePath, keySha, true);
    if (stale) {
      console.warn("[cloakbrowser] Using cached license validation (server unreachable)");
      return stale;
    }

    return null;
  }
}

/**
 * Get the latest Pro binary version from the server.
 * Rate-limited to 1 call per hour via a marker file.
 */
export async function getProLatestVersion(): Promise<string | null> {
  const marker = path.join(
    getCacheDir(),
    `.last_pro_version_check_${getPlatformTag()}`,
  );

  try {
    if (fs.existsSync(marker)) {
      const stats = fs.statSync(marker);
      const age = Date.now() - stats.mtimeMs;
      if (age < PRO_VERSION_CHECK_INTERVAL_MS) {
        const content = fs.readFileSync(marker, "utf-8").trim();
        return content || null;
      }
    }
  } catch {
    // Marker unreadable — proceed with fetch
  }

  try {
    const resp = await fetch(PRO_VERSION_URL, {
      headers: { "X-Platform": getPlatformTag() },
      signal: AbortSignal.timeout(10_000),
    });

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
    }

    const data = (await resp.json()) as Record<string, unknown>;
    const version = data.version != null ? String(data.version) : null;
    if (!version) return null;

    try {
      fs.mkdirSync(path.dirname(marker), { recursive: true });
      fs.writeFileSync(marker, version);
    } catch {
      // Non-fatal
    }

    return version;
  } catch {
    return null;
  }
}

/**
 * How many concurrent sessions (seats) this license is holding right now.
 *
 * Deliberately NOT cached: a cached seat count is a wrong seat count. Returns
 * null when the number is unknown — the server couldn't be reached, or it
 * reported the count as unavailable (it does that instead of a false 0 while
 * running in leaseless mode). Callers render null as "unavailable".
 */
export async function getActiveSessionCount(licenseKey: string): Promise<number | null> {
  try {
    const resp = await fetch(SESSION_COUNT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ license_key: licenseKey }),
      signal: AbortSignal.timeout(10_000),
    });

    if (!resp.ok) {
      throw new Error(`HTTP ${resp.status} ${resp.statusText}`);
    }

    const data = (await resp.json()) as Record<string, unknown>;
    return typeof data.active === "number" ? data.active : null;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Cache helpers
// ---------------------------------------------------------------------------

interface CacheData {
  key_sha256: string;
  valid: boolean;
  plan: string;
  expires: string | null;
  validated_at: number;
}

function readCache(
  cachePath: string,
  keySha: string,
  ignoreTtl = false,
): LicenseInfo | null {
  try {
    if (!fs.existsSync(cachePath)) return null;

    const data = JSON.parse(fs.readFileSync(cachePath, "utf-8")) as CacheData;

    if (data.key_sha256 !== keySha) return null;

    if (!ignoreTtl) {
      const validatedAt = data.validated_at ?? 0;
      // A non-numeric validated_at (corrupted cache) is treated as absent rather
      // than coercing to NaN and silently trusting the entry.
      if (!Number.isFinite(validatedAt) || Date.now() - validatedAt * 1000 > LICENSE_CACHE_TTL_MS) {
        return null;
      }
    }

    if (data.expires) {
      try {
        if (new Date(data.expires).getTime() < Date.now()) {
          return { valid: false, plan: String(data.plan ?? "solo"), expires: data.expires };
        }
      } catch {
        // unparseable date — skip check
      }
    }

    return {
      valid: Boolean(data.valid ?? false),
      plan: String(data.plan ?? "solo"),
      expires: data.expires ?? null,
    };
  } catch {
    return null;
  }
}

function writeCache(cachePath: string, keySha: string, info: LicenseInfo): void {
  try {
    const dir = path.dirname(cachePath);
    fs.mkdirSync(dir, { recursive: true });
    const tmpPath = cachePath + ".tmp";
    fs.writeFileSync(
      tmpPath,
      JSON.stringify({
        key_sha256: keySha,
        valid: info.valid,
        plan: info.plan,
        expires: info.expires,
        validated_at: Date.now() / 1000,
      }),
    );
    fs.renameSync(tmpPath, cachePath);
  } catch {
    // Non-fatal
  }
}
