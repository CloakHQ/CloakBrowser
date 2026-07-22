/**
 * GeoIP-based timezone and locale detection from proxy IP.
 *
 * Optional feature — requires `mmdb-lib` package:
 *   npm install mmdb-lib
 *
 * Downloads GeoLite2-City.mmdb (~70 MB) on first use,
 * caches in `~/.cloakbrowser/geoip/`.
 */

import fs from "node:fs";
import path from "node:path";
import { createWriteStream } from "node:fs";
import dns from "node:dns/promises";
import net from "node:net";
import { getCacheDir } from "./config.js";
import type { LaunchOptions } from "./types.js";
import { ensureProxyScheme, isSocksProxy, reconstructSocksUrl, type ProxyDict } from "./proxy.js";

// P3TERX mirror of MaxMind GeoLite2-City — no license key needed
const GEOIP_DB_URL =
  "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb";
const GEOIP_DB_FILENAME = "GeoLite2-City.mmdb";
const GEOIP_UPDATE_INTERVAL_MS = 30 * 86_400_000; // 30 days
const DEFAULT_GEOIP_TIMEOUT_MS = 5_000;

/** Country ISO code → BCP 47 locale (covers ~90% of proxy traffic). */
export const COUNTRY_LOCALE_MAP: Record<string, string> = {
  US: "en-US", GB: "en-GB", AU: "en-AU", CA: "en-CA", NZ: "en-NZ",
  IE: "en-IE", ZA: "en-ZA", SG: "en-SG",
  DE: "de-DE", AT: "de-AT", CH: "de-CH",
  FR: "fr-FR", BE: "fr-BE",
  ES: "es-ES", MX: "es-MX", AR: "es-AR", CO: "es-CO", CL: "es-CL",
  BR: "pt-BR", PT: "pt-PT",
  IT: "it-IT", NL: "nl-NL",
  JP: "ja-JP", KR: "ko-KR", CN: "zh-CN", TW: "zh-TW", HK: "zh-HK",
  RU: "ru-RU", UA: "uk-UA", PL: "pl-PL", CZ: "cs-CZ", RO: "ro-RO",
  IL: "he-IL", TR: "tr-TR", SA: "ar-SA", AE: "ar-AE", EG: "ar-EG",
  IN: "hi-IN", ID: "id-ID", PH: "en-PH",
  TH: "th-TH", VN: "vi-VN", MY: "ms-MY",
  SE: "sv-SE", NO: "nb-NO", DK: "da-DK", FI: "fi-FI",
  GR: "el-GR", HU: "hu-HU", BG: "bg-BG",
  // Extended coverage — common residential/mobile proxy exits
  SI: "sl-SI", SK: "sk-SK", HR: "hr-HR", RS: "sr-RS", LT: "lt-LT",
  LV: "lv-LV", EE: "et-EE", IS: "is-IS", LU: "fr-LU", MT: "en-MT",
  CY: "el-CY", MD: "ro-MD", BY: "ru-BY", GE: "ka-GE", AL: "sq-AL",
  MK: "mk-MK", BA: "bs-BA",
  PE: "es-PE", VE: "es-VE", EC: "es-EC", UY: "es-UY", CR: "es-CR",
  DO: "es-DO", GT: "es-GT", BO: "es-BO", PY: "es-PY",
  PK: "en-PK", BD: "bn-BD", LK: "si-LK", KZ: "ru-KZ", IR: "fa-IR",
  IQ: "ar-IQ", JO: "ar-JO", LB: "ar-LB", KW: "ar-KW", QA: "ar-QA",
  OM: "ar-OM", BH: "ar-BH",
  NG: "en-NG", KE: "en-KE", MA: "fr-MA", DZ: "ar-DZ", TN: "ar-TN",
  GH: "en-GH",
  AM: "hy-AM", AZ: "az-AZ", UZ: "uz-UZ", KG: "ky-KG", TJ: "tg-TJ",
  TM: "tk-TM",
  ME: "sr-ME", XK: "sq-XK", LI: "de-LI", MC: "fr-MC", AD: "ca-AD",
  MM: "my-MM", KH: "km-KH", LA: "lo-LA", MN: "mn-MN", BN: "ms-BN",
  MO: "zh-MO",
  YE: "ar-YE", SY: "ar-SY", PS: "ar-PS", LY: "ar-LY",
  ET: "am-ET", TZ: "sw-TZ", UG: "en-UG", SN: "fr-SN", CI: "fr-CI",
  CM: "fr-CM", AO: "pt-AO", MZ: "pt-MZ", ZM: "en-ZM", ZW: "en-ZW",
  HN: "es-HN", NI: "es-NI", SV: "es-SV", PA: "es-PA", JM: "en-JM",
  TT: "en-TT", PR: "es-PR",
};

export interface GeoResult {
  timezone: string | null;
  locale: string | null;
  exitIp: string | null;
}

/**
 * Resolve timezone and locale from a proxy's IP address.
 * Returns `{ timezone, locale }` — either may be null on failure.
 * Never throws.
 *
 * When `proxyUrl` is falsy, the machine's own public IP is used instead
 * (echo services queried directly, no proxy), so geoip works proxy-free.
 */
export async function resolveProxyGeo(
  proxyUrl: string | null
): Promise<GeoResult> {
  let Reader: any;
  try {
    const mmdb = await import("mmdb-lib");
    Reader = mmdb.default?.Reader ?? mmdb.Reader;
  } catch {
    throw new Error(
      "mmdb-lib is required for geoip: true. Install it with:\n  npm install mmdb-lib"
    );
  }

  // Ensure the DB first — the download must NOT be bounded by the resolution
  // timeout (a first-use ~70MB fetch legitimately outlasts it).
  const dbPath = await ensureGeoipDb();

  const timeoutMs = getGeoipTimeoutMs();
  const deadline = deadlineFromTimeout(timeoutMs);

  // Exit IP (through proxy, or the machine's own public IP when proxyUrl is
  // falsy) is most accurate — gateway DNS may differ from exit. Resolved even
  // when the DB is unavailable: the IP does not need the DB, and dropping it on
  // a DB hiccup would let WebRTC fall back to the real IP behind a proxy while
  // the connection shows the proxy IP — a real deanonymization.
  let ip = await resolveExitIp(proxyUrl, remainingMs(deadline));
  // Hostname fallback only applies to a proxy; no proxy → echo services only
  if (!ip && proxyUrl && !deadlineExpired(deadline)) ip = await resolveProxyIp(proxyUrl);
  if (!ip || deadlineExpired(deadline)) {
    if (deadlineExpired(deadline)) {
      console.warn(`[cloakbrowser] GeoIP resolution timed out after ${timeoutMs}ms; continuing without GeoIP`);
    }
    return { timezone: null, locale: null, exitIp: null };
  }

  // DB only drives tz/locale; a missing/failed DB still returns the exit IP.
  if (!dbPath) return { timezone: null, locale: null, exitIp: ip };

  try {
    const buf = fs.readFileSync(dbPath);
    const reader = new Reader(buf);
    const result = reader.get(ip) as any;
    const timezone: string | null = result?.location?.time_zone ?? null;
    const countryCode: string | null = result?.country?.iso_code ?? null;
    const locale =
      countryCode ? (COUNTRY_LOCALE_MAP[countryCode] ?? null) : null;
    return { timezone, locale, exitIp: ip };
  } catch {
    return { timezone: null, locale: null, exitIp: ip };
  }
}

function getGeoipTimeoutMs(): number {
  const raw = process.env.CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS;
  if (!raw) return DEFAULT_GEOIP_TIMEOUT_MS;
  const timeoutSeconds = Number(raw);
  if (!Number.isFinite(timeoutSeconds)) {
    console.warn(`[cloakbrowser] Invalid CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS=${raw}; using ${DEFAULT_GEOIP_TIMEOUT_MS / 1000}s`);
    return DEFAULT_GEOIP_TIMEOUT_MS;
  }
  return Math.max(timeoutSeconds, 0) * 1000;
}

function deadlineFromTimeout(timeoutMs: number): number | null {
  return timeoutMs > 0 ? performance.now() + timeoutMs : null;
}

function remainingMs(deadline: number | null): number | undefined {
  if (deadline === null) return undefined;
  return Math.max(deadline - performance.now(), 0);
}

function deadlineExpired(deadline: number | null): boolean {
  return deadline !== null && performance.now() >= deadline;
}

// ---------------------------------------------------------------------------
// Proxy IP resolution
// ---------------------------------------------------------------------------

/** @internal Exported for testing. */
export async function resolveProxyIp(
  proxyUrl: string
): Promise<string | null> {
  try {
    const url = new URL(proxyUrl);
    const hostname = url.hostname;
    if (!hostname) return null;

    // Already a literal IP?
    if (net.isIP(hostname)) return hostname;

    // DNS resolve
    const { address } = await dns.lookup(hostname);
    return address;
  } catch {
    return null;
  }
}

const IP_ECHO_URLS = [
  "https://api.ipify.org",
  "https://checkip.amazonaws.com",
  "https://ifconfig.me/ip",
];

async function resolveExitIp(proxyUrl: string | null | undefined, timeoutMs?: number): Promise<string | null> {
  const deadline = timeoutMs && timeoutMs > 0 ? performance.now() + timeoutMs : null;

  // No proxy: query the echo services directly → the machine's own public IP.
  if (!proxyUrl) {
    for (const echoUrl of IP_ECHO_URLS) {
      const remaining = remainingMs(deadline);
      if (remaining !== undefined && remaining <= 0) return null;
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), Math.min(10_000, remaining ?? 10_000));
        try {
          const res = await fetch(echoUrl, { signal: controller.signal });
          if (!res.ok) continue;
          const ip = (await res.text()).trim();
          if (net.isIP(ip)) return ip;
        } finally {
          clearTimeout(timer);
        }
      } catch {
        continue;
      }
    }
    return null;
  }

  const isSocks = isSocksProxy(proxyUrl);

  // SOCKS5: tunnel through the SOCKS5 proxy via socks-proxy-agent
  if (isSocks) {
    let SocksProxyAgent: typeof import("socks-proxy-agent").SocksProxyAgent;
    try {
      ({ SocksProxyAgent } = await import("socks-proxy-agent"));
    } catch {
      console.warn("[cloakbrowser] socks-proxy-agent not installed — cannot resolve exit IP through SOCKS5 proxy. Install it: npm install socks-proxy-agent");
      return null;
    }
    const { default: https } = await import("node:https");
    const agent = new SocksProxyAgent(proxyUrl);

    for (const echoUrl of IP_ECHO_URLS) {
      const remaining = remainingMs(deadline);
      if (remaining !== undefined && remaining <= 0) return null;
      try {
        const ip = await new Promise<string | null>((resolve) => {
          const req = https.request(echoUrl, { agent, timeout: Math.min(10_000, remaining ?? 10_000) }, (res) => {
            let data = "";
            res.on("data", (chunk: Buffer) => (data += chunk.toString()));
            res.on("end", () => {
              const ip = data.trim();
              resolve(net.isIP(ip) ? ip : null);
            });
          });
          req.on("error", () => resolve(null));
          req.on("timeout", () => { req.destroy(); resolve(null); });
          req.end();
        });
        if (ip) return ip;
      } catch {
        continue;
      }
    }
    return null;
  }

  // HTTP/HTTPS: use a CONNECT tunnel via http
  try {
    const { default: http } = await import("node:http");
    const { default: https } = await import("node:https");
    const proxyUrlObj = new URL(proxyUrl);

    for (const echoUrl of IP_ECHO_URLS) {
      const remaining = remainingMs(deadline);
      if (remaining !== undefined && remaining <= 0) return null;
      try {
        const ip = await new Promise<string | null>((resolve, reject) => {
          const targetUrl = new URL(echoUrl);
          const connectReq = http.request({
            host: proxyUrlObj.hostname,
            port: parseInt(proxyUrlObj.port || "80", 10),
            method: "CONNECT",
            path: `${targetUrl.hostname}:443`,
            headers: proxyUrlObj.username
              ? {
                  "Proxy-Authorization":
                    "Basic " +
                    Buffer.from(
                      `${decodeURIComponent(proxyUrlObj.username)}:${decodeURIComponent(proxyUrlObj.password || "")}`
                    ).toString("base64"),
                }
              : {},
            timeout: Math.min(10_000, remaining ?? 10_000),
          });

          connectReq.on("connect", (_res, socket) => {
            const innerRemaining = remainingMs(deadline);
            const req = https.request(
              echoUrl,
              { socket, timeout: Math.min(5_000, innerRemaining ?? 5_000) } as any,
              (res) => {
                let data = "";
                res.on("data", (chunk: Buffer) => (data += chunk.toString()));
                res.on("end", () => {
                  const ip = data.trim();
                  resolve(net.isIP(ip) ? ip : null);
                });
              }
            );
            req.on("error", () => resolve(null));
            req.on("timeout", () => { req.destroy(); resolve(null); });
            req.end();
          });

          connectReq.on("error", () => resolve(null));
          connectReq.on("timeout", () => {
            connectReq.destroy();
            resolve(null);
          });
          connectReq.end();
        });

        if (ip) return ip;
      } catch {
        continue;
      }
    }
  } catch {
    // Fallback: couldn't import http modules
  }
  return null;
}

// ---------------------------------------------------------------------------
// GeoIP database management
// ---------------------------------------------------------------------------

function getGeoipDir(): string {
  return path.join(getCacheDir(), "geoip");
}

// Shared in-flight download so N concurrent launches don't each fetch the
// same ~70 MB file (issue #458). Per-process only.
let geoipDownloadPromise: Promise<void> | null = null;

function runGuardedDownload(dbPath: string): Promise<void> {
  if (geoipDownloadPromise) return geoipDownloadPromise;
  geoipDownloadPromise = downloadGeoipDb(dbPath).finally(() => {
    geoipDownloadPromise = null;
  });
  return geoipDownloadPromise;
}

async function ensureGeoipDb(): Promise<string | null> {
  const dir = getGeoipDir();
  const dbPath = path.join(dir, GEOIP_DB_FILENAME);

  if (fs.existsSync(dbPath)) {
    maybeTriggerUpdate(dbPath);
    return dbPath;
  }

  try {
    await runGuardedDownload(dbPath);
    // Another concurrent launch may have owned the download; reuse its result.
    return fs.existsSync(dbPath) ? dbPath : null;
  } catch {
    return null;
  }
}

async function downloadGeoipDb(dest: string): Promise<void> {
  const dir = path.dirname(dest);
  fs.mkdirSync(dir, { recursive: true });
  console.log("[cloakbrowser] Downloading GeoIP database (~70 MB)…");

  const tmpPath = `${dest}.tmp.${Date.now()}`;
  try {
    const response = await fetch(GEOIP_DB_URL, {
      redirect: "follow",
    });
    if (!response.ok || !response.body) {
      throw new Error(`HTTP ${response.status}`);
    }

    const fileStream = createWriteStream(tmpPath);
    const reader = response.body.getReader();

    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      fileStream.write(value);
    }

    await new Promise<void>((resolve, reject) => {
      fileStream.end(() => resolve());
      fileStream.on("error", reject);
    });

    fs.renameSync(tmpPath, dest);
    console.log(`[cloakbrowser] GeoIP database ready: ${dest}`);
  } catch (err) {
    if (fs.existsSync(tmpPath)) fs.unlinkSync(tmpPath);
    throw err;
  }
}

function maybeTriggerUpdate(dbPath: string): void {
  try {
    const age = Date.now() - fs.statSync(dbPath).mtimeMs;
    if (age < GEOIP_UPDATE_INTERVAL_MS) return;
  } catch {
    return;
  }
  // Fire-and-forget background update — skip if a download is already running.
  if (geoipDownloadPromise) return;
  runGuardedDownload(dbPath).catch(() => {});
}

/**
 * Extract a usable proxy URL from LaunchOptions.proxy.
 * For SOCKS5 dicts with separate credentials, reconstructs the full URL
 * with inline credentials so SOCKS5 auth works.
 */
function extractProxyUrl(proxy: string | ProxyDict | undefined): string | null {
  if (!proxy) return null;
  if (typeof proxy === "string") return ensureProxyScheme(proxy);
  const p = proxy as ProxyDict;
  if (!p.server) return null;
  if (p.username && isSocksProxy(p)) {
    return reconstructSocksUrl(p);
  }
  return ensureProxyScheme(p.server);
}

/** Return the value of the first `--key=value` flag found in args, else undefined. */
function getFlagValue(args: string[] | undefined, ...keys: string[]): string | undefined {
  for (const a of args ?? []) {
    for (const k of keys) {
      if (a.startsWith(k + "=")) return a.slice(k.length + 1);
    }
  }
  return undefined;
}

/**
 * Auto-fill timezone/locale from the egress IP when geoip is enabled.
 * Also returns exitIp as a free bonus (reused for WebRTC spoofing).
 *
 * With a proxy the egress IP is the proxy's exit IP; with no proxy it is
 * the machine's own public IP, so geoip works proxy-free too.
 *
 * A timezone/locale set as a raw flag in `args` (--fingerprint-timezone, --lang,
 * --fingerprint-locale) counts as explicit: it is promoted to the option so geoip
 * leaves it alone, mirroring the `timezone`/`locale` option override path.
 */
export async function maybeResolveGeoip(
  options: LaunchOptions
): Promise<{ timezone?: string; locale?: string; exitIp?: string }> {
  if (!options.geoip) return { timezone: options.timezone, locale: options.locale };

  // Promote raw flags to explicit values so geoip doesn't clobber them.
  const timezone = options.timezone ?? getFlagValue(options.args, "--fingerprint-timezone");
  const locale = options.locale ?? getFlagValue(options.args, "--lang", "--fingerprint-locale");

  // null when no proxy → echo services resolve the machine's own public IP
  const proxyUrl = options.proxy ? extractProxyUrl(options.proxy) : null;

  // When both tz/locale are explicit, resolve the exit IP for WebRTC — but only
  // with a proxy. With no proxy the WebRTC IP would just be the real connection
  // IP the site already sees (a no-op), so skip the third-party echo call.
  if (timezone && locale) {
    if (!proxyUrl) return { timezone, locale };
    const timeoutMs = getGeoipTimeoutMs();
    const exitIp = await resolveExitIp(proxyUrl, timeoutMs) ?? undefined;
    return { timezone, locale, exitIp };
  }

  const { timezone: geoTz, locale: geoLocale, exitIp: geoExitIp } = await resolveProxyGeo(proxyUrl);
  const exitIp = geoExitIp ?? undefined;
  return {
    timezone: timezone ?? geoTz ?? undefined,
    locale: locale ?? geoLocale ?? undefined,
    exitIp,
  };
}

/**
 * Append `--fingerprint-webrtc-ip=<exitIp>` unless the user already set the flag.
 * The exit IP comes free from the geoip lookup; it spoofs the WebRTC IP to the
 * egress IP. No-op when there is no exit IP or the flag is already present. This
 * rule must stay identical across every launch path, so it lives in one place.
 */
export function appendWebrtcExitIp(
  args: string[] | undefined,
  exitIp: string | undefined,
): string[] | undefined {
  if (exitIp && !(args ?? []).some(a => a.startsWith("--fingerprint-webrtc-ip"))) {
    return [...(args ?? []), `--fingerprint-webrtc-ip=${exitIp}`];
  }
  return args;
}

/**
 * Replace --fingerprint-webrtc-ip=auto with the resolved proxy exit IP.
 * Returns args unchanged if no ``auto`` value is present.
 */
export async function resolveWebrtcArgs(
  options: LaunchOptions
): Promise<string[] | undefined> {
  const args = options.args;
  if (!args) return args;
  const idx = args.findIndex(a => a === "--fingerprint-webrtc-ip=auto");
  if (idx === -1) return args;

  const proxyUrl = extractProxyUrl(options.proxy);
  if (!proxyUrl) {
    console.warn("[cloakbrowser] --fingerprint-webrtc-ip=auto requires a proxy; removing flag");
    const result = [...args];
    result.splice(idx, 1);
    return result;
  }

  try {
    const ip = await resolveExitIp(proxyUrl, getGeoipTimeoutMs());
    const result = [...args];
    if (ip) {
      result[idx] = `--fingerprint-webrtc-ip=${ip}`;
    } else {
      console.warn("[cloakbrowser] Could not resolve proxy exit IP for WebRTC spoofing; removing --fingerprint-webrtc-ip=auto");
      result.splice(idx, 1);
    }
    return result;
  } catch {
    console.warn("[cloakbrowser] Failed to resolve proxy exit IP for WebRTC spoofing; removing --fingerprint-webrtc-ip=auto");
    const result = [...args];
    result.splice(idx, 1);
    return result;
  }
}
