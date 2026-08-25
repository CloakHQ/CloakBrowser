/**
 * License validation and caching for CloakBrowser Pro.
 * Mirrors Python cloakbrowser/license.py.
 *
 * Handles license key resolution, server validation with local caching,
 * and Pro version checks.
 */

import { createHash, randomUUID } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { getCacheDir, getPlatformTag, normalizeReleaseChannel } from "./config.js";

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
 * Result of a seat lookup: the count, the cap it counts against, and the reason
 * either is missing.
 *
 * state:
 *   "ok"          active is a real number (0 is a real answer, not an error)
 *   "unreachable" never got an answer — DNS, refused, timeout, TLS
 *   "denied"      the server refused; `reason` carries its error code
 *   "unknown"     the server is up and the key is fine, but it cannot count
 *                 right now (leaseless mode, or its seat store is unreachable)
 *
 * limit is null whenever the server declined to state a cap: unlimited, an
 * unrecognised plan, or a server too old to send the field. Callers must fall back
 * to the bare count, never invent a denominator.
 */
export interface SessionSeats {
  active: number | null;
  limit: number | null;
  state: "ok" | "unreachable" | "denied" | "unknown";
  reason: string | null;
}

export interface ProReleaseInfo {
  version: string;
  requestedChannel: "stable" | "preview";
  resolvedChannel: "stable" | "preview";
  fallback: boolean;
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

// Env var the wrapper uses to tell the Pro binary where to record a license
// denial. A denial that resolves AFTER the CDP handshake (e.g. an over-cap seat)
// kills the browser once the driver already holds a live connection, so the exit
// code never reaches the wrapper as a launch failure. The binary writes the code
// to this path just before exiting; the wrapper reads it when the user's next
// call fails. Old binaries ignore the unknown var and never write.
export const LICENSE_STATUS_FILE_ENV = "CLOAKBROWSER_LICENSE_STATUS_FILE";

/**
 * Map a raw license exit code (76-79) to a CloakBrowserLicenseError, or null
 * for any code that is not a known license denial (so a genuine crash is never
 * mislabelled). Companion to licenseErrorMessage for the post-handshake,
 * file-based path where we hold the integer directly.
 */
export function licenseErrorForCode(code: number): CloakBrowserLicenseError | null {
  const msg = LICENSE_EXIT_MESSAGES[code];
  return msg ? new CloakBrowserLicenseError(msg) : null;
}

// Once a denial has been observed for a per-launch path, remember it. The read
// is destructive, so a concurrent second guarded call for the same launch would
// otherwise find the file gone and miss the denial. Paths are unique per launch.
const observedDenials = new Map<string, number>();

/**
 * Read and consume a denial file written by the binary, returning its code.
 * The file holds a single JSON integer (the exit code). Reading is destructive:
 * the file is unlinked afterwards so a later launch can't see a stale code, but
 * the observed code is cached in-process so a concurrent second guarded call
 * still surfaces the denial. Any problem — absent, unreadable, or not a valid
 * int — yields null.
 */
export function readDenialFile(filePath: string): number | null {
  const cached = observedDenials.get(filePath);
  if (cached !== undefined) return cached;
  // Fast path: the guard calls this after *every* browser call to catch a
  // denial that lands while calls still succeed, so the no-denial case (file
  // absent) must be cheap — a single stat, not a read()+catch per call.
  if (!fs.existsSync(filePath)) return null;
  let code: number | null = null;
  try {
    const raw = fs.readFileSync(filePath, "utf-8");
    const parsed = Number(JSON.parse(raw));
    code = Number.isInteger(parsed) ? parsed : null;
  } catch {
    code = null;
  }
  try {
    fs.unlinkSync(filePath);
  } catch {
    // best-effort cleanup
  }
  if (code !== null) observedDenials.set(filePath, code);
  return code;
}

/**
 * Return a fresh, unique path for the binary to write a denial code to. Only
 * computes the path (and ensures the parent dir exists) — the file is created
 * by the binary, and only on a denial, so a granted launch leaves nothing
 * behind. Returns undefined if the directory can't be created; the caller then
 * skips the feature (the fix must never break a launch).
 */
// A denial file is orphaned when the binary writes one but the user never calls
// a guarded method afterwards. It is only consumed on a guarded call, so sweep
// leftovers older than this at mint time — long enough that a live in-flight
// denial from a concurrent launch is never deleted before its owner reads it.
const DENIAL_FILE_TTL_MS = 3600_000;

function sweepStaleDenials(denialDir: string): void {
  try {
    const now = Date.now();
    for (const name of fs.readdirSync(denialDir)) {
      if (!name.endsWith(".json")) continue;
      const p = path.join(denialDir, name);
      try {
        if (now - fs.statSync(p).mtimeMs > DENIAL_FILE_TTL_MS) fs.unlinkSync(p);
      } catch {
        // best-effort
      }
    }
  } catch {
    // best-effort
  }
}

export function mintDenialFile(): string | undefined {
  try {
    const denialDir = path.join(os.homedir(), ".cloakbrowser", "denials");
    fs.mkdirSync(denialDir, { recursive: true });
    sweepStaleDenials(denialDir);
    return path.join(denialDir, `${randomUUID()}.json`);
  } catch {
    return undefined;
  }
}

// Factory methods whose return value is itself a handle the user drives (a page
// or context handed back after launch). Guarding these *deeply* — guarding the
// object they return — lets a denial that lands AFTER the handshake surface on
// the returned page's first call, not only on a second newPage(). Covers both
// the Playwright and Puppeteer surfaces.
const GUARD_FACTORY_METHODS = [
  "newPage",
  "newContext",
  "createBrowserContext",
  "createIncognitoBrowserContext",
];

// Never wrap these. `close` already carries teardown logic; the EventEmitter
// surface is called INTERNALLY by playwright/puppeteer (e.g. emit('close')
// during teardown), so throwing a license error from inside their own event
// dispatch would crash the driver rather than surface cleanly to the user.
const GUARD_SKIP_METHODS = new Set([
  "close",
  "on", "off", "once", "emit", "addListener", "removeListener",
  "removeAllListeners", "listeners", "rawListeners", "listenerCount",
  "eventNames", "prependListener", "prependOnceListener",
  "setMaxListeners", "getMaxListeners",
]);

/** Read the denial file and map it to a license error, or null. */
function denialLicenseError(denialPath: string): CloakBrowserLicenseError | null {
  const code = readDenialFile(denialPath);
  return code !== null ? licenseErrorForCode(code) : null;
}

/**
 * Public, non-getter method names on `target` and its prototype chain — the
 * methods that can throw a TargetClosedError once the browser dies. Getters are
 * skipped so they are never triggered here; this covers every real method
 * without enumerating them by hand.
 */
function guardableMethodNames(target: any): string[] {
  const names = new Set<string>();
  for (let obj = target; obj && obj !== Object.prototype; obj = Object.getPrototypeOf(obj)) {
    for (const name of Object.getOwnPropertyNames(obj)) {
      if (name === "constructor" || name.startsWith("_") || names.has(name)) continue;
      if (GUARD_SKIP_METHODS.has(name)) continue;
      const desc = Object.getOwnPropertyDescriptor(obj, name);
      if (!desc || typeof desc.get === "function") continue; // skip getters
      if (typeof target[name] === "function") names.add(name);
    }
  }
  return [...names];
}

/**
 * Guard every public method of `target` (a browser, context, or page) so a
 * post-handshake license denial surfaces as CloakBrowserLicenseError on the
 * user's first failing call — whichever method that is.
 *
 * A denial that lands after the driver connected kills the browser without a
 * launch failure; the user's next call would otherwise throw a bare
 * TargetClosedError. Each wrapped method checks the denial file the binary
 * wrote — on error AND on success (the binary writes the file the instant it's
 * over cap but keeps serving blank responses for ~1s before it exits, so a fast
 * flow that never throws must still surface it). A genuine, non-license error
 * propagates unchanged. Factory methods (newPage/newContext/…) additionally
 * guard the object they return, so a page obtained after launch is covered too.
 *
 * Sync-ness is preserved: an async method's promise is chained, a sync method
 * (`url()`, `isClosed()`, `on()`) returns its value directly — wrapping those in
 * an async function would break them. Mirrors Python _install_license_guard.
 */
export function installLicenseGuard(target: any, denialPath: string): void {
  for (const name of guardableMethodNames(target)) {
    const original = target[name].bind(target);
    const deep = GUARD_FACTORY_METHODS.includes(name);
    target[name] = (...callArgs: any[]) => {
      let result: any;
      try {
        result = original(...callArgs);
      } catch (err) {
        const lic = denialLicenseError(denialPath);
        if (lic) throw lic;
        throw err;
      }
      if (result != null && typeof result.then === "function") {
        return result.then(
          (val: any) => {
            const lic = denialLicenseError(denialPath);
            if (lic) throw lic;
            if (deep && val != null) installLicenseGuard(val, denialPath);
            return val;
          },
          (err: any) => {
            const lic = denialLicenseError(denialPath);
            if (lic) throw lic;
            throw err;
          },
        );
      }
      const lic = denialLicenseError(denialPath);
      if (lic) throw lic;
      if (deep && result != null) installLicenseGuard(result, denialPath);
      return result;
    };
  }
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
  statusFile?: string,
): Record<string, string> | undefined {
  const { key, source } = resolveLicenseKeyWithSource(licenseKey);

  // Normalize the custom env once so every return path behaves identically:
  // drop undefined values (Playwright's env is typed string→string).
  const baseEnv = userEnv
    ? (Object.fromEntries(
        Object.entries(userEnv).filter(([, v]) => v !== undefined),
      ) as Record<string, string>)
    : undefined;

  let result = buildKeyEnv(key, source, baseEnv);

  // Add the denial-status file path last so it rides along even on the
  // inherit-parent-env (undefined) paths, which then have to become a full
  // process.env copy (Playwright replaces, not merges). Only set when the
  // caller asked for it, which it only does when a license key is in play.
  if (statusFile !== undefined) {
    if (result === undefined) {
      result = {};
      for (const [k, v] of Object.entries(process.env)) {
        if (v !== undefined) result[k] = v;
      }
    }
    result[LICENSE_STATUS_FILE_ENV] = statusFile;
  }

  return result;
}

/** The license-key half of buildLaunchEnv (unchanged behavior). */
function buildKeyEnv(
  key: string | undefined,
  source: LicenseKeySource,
  baseEnv: Record<string, string> | undefined,
): Record<string, string> | undefined {
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

/** Get the server-resolved Pro release and channel for this platform. */
export async function getProLatestRelease(releaseChannel?: string): Promise<ProReleaseInfo | null> {
  const channel = normalizeReleaseChannel(releaseChannel);
  const markerSuffix = channel === "preview"
    ? `preview_${getPlatformTag()}`
    : getPlatformTag();
  const marker = path.join(getCacheDir(), `.last_pro_version_check_${markerSuffix}`);
  const resolutionMarker = path.join(
    getCacheDir(),
    `.last_pro_version_resolution_${markerSuffix}`,
  );

  try {
    if (fs.existsSync(marker) && fs.existsSync(resolutionMarker)) {
      const stats = fs.statSync(marker);
      const age = Date.now() - stats.mtimeMs;
      if (age < PRO_VERSION_CHECK_INTERVAL_MS) {
        const version = fs.readFileSync(marker, "utf-8").trim();
        const cached = JSON.parse(fs.readFileSync(resolutionMarker, "utf-8")) as {
          version?: string;
          requested_channel?: "stable" | "preview";
          resolved_channel?: "stable" | "preview";
          requestedChannel?: "stable" | "preview";
          resolvedChannel?: "stable" | "preview";
          fallback?: boolean;
        };
        if (version && cached.version === version) {
          const requestedChannel = cached.requested_channel ?? cached.requestedChannel ?? channel;
          const resolvedChannel = cached.resolved_channel ?? cached.resolvedChannel ?? "stable";
          return {
            version,
            requestedChannel,
            resolvedChannel,
            fallback: cached.fallback ?? requestedChannel !== resolvedChannel,
          };
        }
      }
    }
  } catch {
    // Cache unreadable — proceed with fetch.
  }

  try {
    const versionUrl = channel === "preview"
      ? `${PRO_VERSION_URL}?channel=preview`
      : PRO_VERSION_URL;
    const resp = await fetch(versionUrl, {
      headers: { "X-Platform": getPlatformTag() },
      signal: AbortSignal.timeout(10_000),
    });

    if (!resp.ok) throw new Error(`HTTP ${resp.status} ${resp.statusText}`);

    const data = (await resp.json()) as Record<string, unknown>;
    const version = data.version != null ? String(data.version) : null;
    if (!version) return null;
    const requestedChannel = data.requested_channel === "preview" ? "preview" : channel;
    const resolvedChannel = data.resolved_channel === "preview" ? "preview" : "stable";
    const release: ProReleaseInfo = {
      version,
      requestedChannel,
      resolvedChannel,
      fallback: typeof data.fallback === "boolean"
        ? data.fallback
        : requestedChannel !== resolvedChannel,
    };

    try {
      fs.mkdirSync(path.dirname(marker), { recursive: true });
      fs.writeFileSync(resolutionMarker, JSON.stringify({
        version: release.version,
        requested_channel: release.requestedChannel,
        resolved_channel: release.resolvedChannel,
        fallback: release.fallback,
      }));
      fs.writeFileSync(marker, version);
    } catch {
      // Non-fatal
    }
    return release;
  } catch {
    try {
      const version = fs.readFileSync(marker, "utf-8").trim();
      if (!version) return null;
      // Prefer the last successful fetch's channel metadata (the resolution
      // sidecar) so an offline preview build is not mislabeled as a stable
      // fallback. Older wrappers left only the version marker, so its channel is
      // unknowable — hardcode a conservative stable fallback then.
      try {
        const cached = JSON.parse(fs.readFileSync(resolutionMarker, "utf-8")) as {
          version?: string;
          requested_channel?: "stable" | "preview";
          resolved_channel?: "stable" | "preview";
          requestedChannel?: "stable" | "preview";
          resolvedChannel?: "stable" | "preview";
          fallback?: boolean;
        };
        if (cached.version === version) {
          const requestedChannel = cached.requested_channel ?? cached.requestedChannel ?? channel;
          const resolvedChannel = cached.resolved_channel ?? cached.resolvedChannel ?? "stable";
          return {
            version,
            requestedChannel,
            resolvedChannel,
            fallback: cached.fallback ?? requestedChannel !== resolvedChannel,
          };
        }
      } catch {
        // Sidecar missing or unreadable — fall through to the conservative default.
      }
      return {
        version,
        requestedChannel: channel,
        resolvedChannel: "stable",
        fallback: channel === "preview",
      };
    } catch {
      return null;
    }
  }
}

/** Get only the version from the server-resolved Pro release. */
export async function getProLatestVersion(releaseChannel?: string): Promise<string | null> {
  return (await getProLatestRelease(releaseChannel))?.version ?? null;
}

/**
 * Seats held right now, the cap they count against, and why either is missing.
 *
 * Deliberately NOT cached: a cached seat count is a wrong seat count.
 *
 * Six different things can stop us answering — no route to the host, a timeout, a
 * 403 for a dead key, a 429, the server reporting the count as unknown in leaseless
 * mode, and its seat store being unreachable. They used to collapse into one bare
 * null, so `info` printed the same "unavailable" for "your key is dead" and "our
 * backend is degraded, you are fine". `state` keeps them apart.
 */
export async function getSessionSeats(licenseKey: string): Promise<SessionSeats> {
  let resp: Response;
  try {
    resp = await fetch(SESSION_COUNT_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ license_key: licenseKey }),
      signal: AbortSignal.timeout(10_000),
    });
  } catch {
    // Never reached the server: DNS, refused, timed out, TLS.
    return { active: null, limit: null, state: "unreachable", reason: null };
  }

  if (!resp.ok) {
    // The server answered, and the answer was a refusal. Its `error` field is the
    // actionable part (invalid_key / license_inactive / rate_limited); fall back to
    // the status when the body is missing or not JSON.
    let reason: string | null = null;
    try {
      const body = (await resp.json()) as Record<string, unknown>;
      if (typeof body.error === "string") reason = body.error;
    } catch {
      // fall through to the status
    }
    return { active: null, limit: null, state: "denied", reason: reason ?? `HTTP ${resp.status}` };
  }

  let data: Record<string, unknown>;
  try {
    data = (await resp.json()) as Record<string, unknown>;
  } catch {
    return { active: null, limit: null, state: "unknown", reason: null };
  }

  if (typeof data.active !== "number") {
    // 200 with active=null is the server saying "up, your key is fine, but I
    // genuinely cannot count right now" — deliberate, so it never reports a false 0.
    return { active: null, limit: null, state: "unknown", reason: null };
  }

  // limit absent (older server) or null (unlimited / unknown plan): callers fall back
  // to the bare count rather than printing a made-up denominator.
  const limit = typeof data.limit === "number" ? data.limit : null;
  return { active: data.active, limit, state: "ok", reason: null };
}

/**
 * How many concurrent sessions (seats) this license is holding right now.
 *
 * Kept for callers outside `info` that only want the number. Prefer
 * getSessionSeats(), which also carries the cap and the reason a lookup failed.
 */
export async function getActiveSessionCount(licenseKey: string): Promise<number | null> {
  return (await getSessionSeats(licenseKey)).active;
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
