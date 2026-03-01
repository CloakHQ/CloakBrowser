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

// P3TERX mirror of MaxMind GeoLite2-City — no license key needed
const GEOIP_DB_URL =
  "https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb";
const GEOIP_DB_FILENAME = "GeoLite2-City.mmdb";
const GEOIP_UPDATE_INTERVAL_MS = 30 * 86_400_000; // 30 days

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
};

export interface GeoResult {
  timezone: string | null;
  locale: string | null;
}

/**
 * Resolve timezone and locale from a proxy's IP address.
 * Returns `{ timezone, locale }` — either may be null on failure.
 * Never throws.
 */
export async function resolveProxyGeo(
  proxyUrl: string
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

  const dbPath = await ensureGeoipDb();
  if (!dbPath) return { timezone: null, locale: null };

  // Exit IP (through proxy) is most accurate — gateway DNS may differ from exit
  let ip = await resolveExitIp(proxyUrl);
  if (!ip) ip = await resolveProxyIp(proxyUrl);
  if (!ip) return { timezone: null, locale: null };

  try {
    const buf = fs.readFileSync(dbPath);
    const reader = new Reader(buf);
    const result = reader.get(ip) as any;
    const timezone: string | null = result?.location?.time_zone ?? null;
    const countryCode: string | null = result?.country?.iso_code ?? null;
    const locale =
      countryCode ? (COUNTRY_LOCALE_MAP[countryCode] ?? null) : null;
    return { timezone, locale };
  } catch {
    return { timezone: null, locale: null };
  }
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

function isPrivateIp(ip: string): boolean {
  // Quick check for common private ranges
  if (ip.startsWith("10.") || ip.startsWith("127.") || ip === "::1") return true;
  if (ip.startsWith("172.")) {
    const second = parseInt(ip.split(".")[1], 10);
    if (second >= 16 && second <= 31) return true;
  }
  if (ip.startsWith("192.168.")) return true;
  return false;
}

const IP_ECHO_URLS = [
  "https://api.ipify.org",
  "https://checkip.amazonaws.com",
  "https://ifconfig.me/ip",
];

async function resolveExitIp(proxyUrl: string): Promise<string | null> {
  // Node.js fetch doesn't support proxy natively — use a CONNECT tunnel via http
  // For simplicity, use a direct HTTP request to a plain-text IP echo service
  // through the proxy using Node's http module
  try {
    const { default: http } = await import("node:http");
    const { default: https } = await import("node:https");
    const proxyUrlObj = new URL(proxyUrl);

    for (const echoUrl of IP_ECHO_URLS) {
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
            timeout: 10_000,
          });

          connectReq.on("connect", (_res, socket) => {
            const req = https.request(
              echoUrl,
              { socket, timeout: 5_000 } as any,
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

async function ensureGeoipDb(): Promise<string | null> {
  const dir = getGeoipDir();
  const dbPath = path.join(dir, GEOIP_DB_FILENAME);

  if (fs.existsSync(dbPath)) {
    maybeTriggerUpdate(dbPath);
    return dbPath;
  }

  try {
    await downloadGeoipDb(dbPath);
    return dbPath;
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
    const response = await fetch(GEOIP_DB_URL, { redirect: "follow" });
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
  // Fire-and-forget background update
  downloadGeoipDb(dbPath).catch(() => {});
}
