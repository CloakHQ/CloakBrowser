/**
 * Shared proxy URL parsing for Playwright and Puppeteer wrappers.
 */

import { getChromiumVersion, getPlatformTag, parseVersion } from "./config.js";

export interface ParsedProxy {
  server: string;
  username?: string;
  password?: string;
}

/**
 * Prepend http:// to schemeless proxy URLs so parsers can extract hostname.
 * Used by geoip resolution which only needs a valid hostname, not auth fields.
 */
export function ensureProxyScheme(proxyUrl: string): string {
  return proxyUrl.includes("://") ? proxyUrl : `http://${proxyUrl}`;
}

/**
 * Parse a proxy URL, extracting credentials into separate fields.
 *
 * Handles: "http://user:pass@host:port" -> { server: "http://host:port", username: "user", password: "pass" }
 * Also handles: no credentials, URL-encoded special chars, socks5://, missing port,
 * and bare proxy strings without a scheme (e.g. "user:pass@host:port" -> treated as http).
 */
/** Proxy dict shape accepted by Playwright/Puppeteer wrappers. */
export type ProxyDict = { server: string; bypass?: string; username?: string; password?: string };

/** Result of resolveProxyConfig — either Playwright dict OR Chrome arg, never both. */
export interface ProxyConfig {
  /** Playwright proxy option (for HTTP proxies). */
  proxyOption?: ParsedProxy;
  /** Chrome CLI args (for SOCKS5 proxies, e.g. ["--proxy-server=socks5://..."]). */
  proxyArgs: string[];
}

/**
 * Check if a proxy uses the SOCKS5 protocol.
 */
export function isSocksProxy(proxy: string | ProxyDict | undefined | null): boolean {
  if (!proxy) return false;
  const url = typeof proxy === "string" ? proxy : proxy.server;
  return /^socks5h?:\/\//i.test(url);
}

/**
 * Build a SOCKS URL from already-percent-encoded credentials and a host suffix.
 *
 * `encPass === null` means no password (no colon in userinfo). Empty string
 * means present-but-empty (colon preserved).
 */
function assembleSocksUrl(
  scheme: string,
  encUser: string,
  encPass: string | null,
  hostAndRest: string,
): string {
  let userinfo: string;
  if (encPass !== null) {
    userinfo = `${encUser}:${encPass}@`;
  } else if (encUser) {
    userinfo = `${encUser}@`;
  } else {
    userinfo = "";
  }
  return `${scheme}://${userinfo}${hostAndRest}`;
}

/**
 * Lenient percent-decode that handles malformed escapes gracefully, matching
 * Python's ``urllib.parse.unquote``: valid ``%XX`` sequences are decoded,
 * bare ``%`` not followed by two hex digits is left as a literal ``%``.
 */
function lenientDecodeURIComponent(s: string): string {
  return s.replace(/%([0-9A-Fa-f]{2})|%/g, (match, hex) =>
    hex ? String.fromCharCode(parseInt(hex, 16)) : "%",
  );
}

/**
 * Reconstruct a SOCKS5 URL with inline credentials from a proxy dict.
 */
export function reconstructSocksUrl(proxy: ProxyDict): string {
  const url = new URL(proxy.server);
  if (proxy.username) {
    url.username = encodeURIComponent(proxy.username);
    if (proxy.password) url.password = encodeURIComponent(proxy.password);
  }
  return url.href.replace(/\/$/, "");
}

/**
 * Re-encode credentials in a SOCKS5 URL string so Chromium's parser doesn't
 * truncate them at special chars like '='. Idempotent: pre-encoded input stays
 * the same (decoded then re-encoded).
 *
 * Parsing is done manually rather than via `new URL` + setters, because WHATWG
 * URL's username/password setters re-encode `%` on assignment, causing
 * double-encoding when we round-trip decode-then-encode.
 *
 * On any unexpected failure, logs a warning and returns the original string
 * so Chromium's own error handling can surface the real problem.
 */
export function normalizeSocksStringUrl(urlStr: string): string {
  // Split userinfo from host at the LAST '@' (RFC 3986), so a raw '@' inside
  // a password like `socks5://user:p@ss@host:1080` parses correctly. Matches
  // Python urlparse's rpartition('@') behavior.
  const schemeMatch = urlStr.match(/^([a-z][a-z0-9+\-.]*):\/\/(.*)$/i);
  if (!schemeMatch) return urlStr;
  const [, scheme, rest] = schemeMatch;
  const hostStart = rest.search(/[/?#]/);
  const authority = hostStart === -1 ? rest : rest.slice(0, hostStart);
  const suffix = hostStart === -1 ? "" : rest.slice(hostStart);
  const atIdx = authority.lastIndexOf("@");
  if (atIdx === -1) return urlStr;  // no creds
  const userinfo = authority.slice(0, atIdx);
  const hostPart = authority.slice(atIdx + 1);
  // Validate port (matches Python's urlparse().port ValueError guard).
  // Extract port after last ':' — but skip IPv6 brackets (e.g. [::1]:1080).
  const bracketEnd = hostPart.lastIndexOf("]");
  const portColonIdx = hostPart.indexOf(":", Math.max(bracketEnd, 0));
  if (portColonIdx !== -1) {
    const portStr = hostPart.slice(portColonIdx + 1);
    if (portStr && !/^\d+$/.test(portStr)) {
      console.warn(`[cloakbrowser] Malformed SOCKS5 proxy URL, passing through unchanged: invalid port`);
      return urlStr;
    }
  }
  const hostAndRest = hostPart + suffix;
  const colonIdx = userinfo.indexOf(":");
  const rawUserEnc = colonIdx === -1 ? userinfo : userinfo.slice(0, colonIdx);
  const hasPassword = colonIdx !== -1;
  const rawPassEnc = hasPassword ? userinfo.slice(colonIdx + 1) : "";
  try {
    const encUser = rawUserEnc ? encodeURIComponent(lenientDecodeURIComponent(rawUserEnc)) : "";
    const encPass = hasPassword
      ? (rawPassEnc ? encodeURIComponent(lenientDecodeURIComponent(rawPassEnc)) : "")
      : null;
    const normalized = assembleSocksUrl(scheme, encUser, encPass, hostAndRest);
    // Compare credentials, not the full URL: keeps the log condition focused
    // on real encoding work, not cosmetic differences (parity with the Python
    // implementation, which has to skip urlparse's hostname lowercasing).
    const credsChanged = encUser !== rawUserEnc
      || (hasPassword ? encPass !== rawPassEnc : false);
    if (credsChanged) {
      console.info(
        "[cloakbrowser] Auto URL-encoded SOCKS5 proxy credentials (special " +
        "characters detected). Pre-encode the URL to suppress this notice.",
      );
    }
    return normalized;
  } catch (e) {
    console.warn(`[cloakbrowser] Could not normalize SOCKS5 proxy URL, passing through unchanged: ${(e as Error).message}`);
    return urlStr;
  }
}

const HTTP_PROXY_INLINE_AUTH_MIN_VERSION = "146.0.7680.177.5";
const HTTP_PROXY_INLINE_AUTH_PLATFORMS = new Set(["linux-x64", "windows-x64"]);

export function supportsHttpProxyInlineAuth(): boolean {
  try {
    const tag = getPlatformTag();
    if (!HTTP_PROXY_INLINE_AUTH_PLATFORMS.has(tag)) return false;
    const current = parseVersion(getChromiumVersion());
    const minimum = parseVersion(HTTP_PROXY_INLINE_AUTH_MIN_VERSION);
    for (let i = 0; i < Math.max(current.length, minimum.length); i++) {
      if ((current[i] ?? 0) > (minimum[i] ?? 0)) return true;
      if ((current[i] ?? 0) < (minimum[i] ?? 0)) return false;
    }
    return true; // equal = supported
  } catch {
    return false;
  }
}

function hasCredentials(proxy: string | ProxyDict): boolean {
  if (typeof proxy === "string") return proxy.includes("@");
  return !!proxy.username;
}

/**
 * Reconstruct an HTTP(S) proxy URL with inline credentials from a proxy dict.
 */
export function reconstructHttpUrl(proxy: ProxyDict): string {
  if (!proxy.username) return proxy.server;
  const url = new URL(ensureProxyScheme(proxy.server));
  url.username = encodeURIComponent(proxy.username);
  if (proxy.password) url.password = encodeURIComponent(proxy.password);
  return url.href.replace(/\/$/, "");
}

/**
 * Re-encode credentials in an HTTP(S) proxy URL string for --proxy-server.
 * Same pattern as normalizeSocksStringUrl.
 */
export function normalizeHttpStringUrl(urlStr: string): string {
  const normalized = urlStr.includes("://") ? urlStr : `http://${urlStr}`;
  const schemeMatch = normalized.match(/^([a-z][a-z0-9+\-.]*):\/\/(.*)$/i);
  if (!schemeMatch) return normalized;
  const [, scheme, rest] = schemeMatch;
  const hostStart = rest.search(/[/?#]/);
  const authority = hostStart === -1 ? rest : rest.slice(0, hostStart);
  const suffix = hostStart === -1 ? "" : rest.slice(hostStart);
  const atIdx = authority.lastIndexOf("@");
  if (atIdx === -1) return normalized;
  const userinfo = authority.slice(0, atIdx);
  const hostPart = authority.slice(atIdx + 1);
  const bracketEnd = hostPart.lastIndexOf("]");
  const portColonIdx = hostPart.indexOf(":", Math.max(bracketEnd, 0));
  if (portColonIdx !== -1) {
    const portStr = hostPart.slice(portColonIdx + 1);
    if (portStr && !/^\d+$/.test(portStr)) {
      console.warn(`[cloakbrowser] Malformed HTTP proxy URL, passing through unchanged: invalid port`);
      return normalized;
    }
  }
  const hostAndRest = hostPart + suffix;
  const colonIdx = userinfo.indexOf(":");
  const rawUserEnc = colonIdx === -1 ? userinfo : userinfo.slice(0, colonIdx);
  const hasPassword = colonIdx !== -1;
  const rawPassEnc = hasPassword ? userinfo.slice(colonIdx + 1) : "";
  try {
    const encUser = rawUserEnc ? encodeURIComponent(lenientDecodeURIComponent(rawUserEnc)) : "";
    const encPass = hasPassword
      ? (rawPassEnc ? encodeURIComponent(lenientDecodeURIComponent(rawPassEnc)) : "")
      : null;
    let userinfoPart: string;
    if (encPass !== null) {
      userinfoPart = `${encUser}:${encPass}@`;
    } else if (encUser) {
      userinfoPart = `${encUser}@`;
    } else {
      userinfoPart = "";
    }
    const result = `${scheme}://${userinfoPart}${hostAndRest}`;
    const credsChanged = encUser !== rawUserEnc
      || (hasPassword ? encPass !== rawPassEnc : false);
    if (credsChanged) {
      console.info(
        "[cloakbrowser] Auto URL-encoded HTTP proxy credentials (special " +
        "characters detected). Pre-encode the URL to suppress this notice.",
      );
    }
    return result;
  } catch (e) {
    console.warn(`[cloakbrowser] Could not normalize HTTP proxy URL, passing through unchanged: ${(e as Error).message}`);
    return normalized;
  }
}

/**
 * Resolve proxy into Playwright option and/or Chrome args.
 *
 * Proxies with credentials (SOCKS5 or HTTP/HTTPS on supported platforms) are
 * passed via Chrome's --proxy-server flag with inline credentials, bypassing
 * Playwright's CDP auth interceptor which breaks on some proxies (#182).
 */
export function resolveProxyConfig(proxy: string | ProxyDict | undefined): ProxyConfig {
  if (!proxy) return { proxyArgs: [] };

  if (isSocksProxy(proxy)) {
    // SOCKS5: bypass Playwright, pass directly to Chrome via --proxy-server.
    if (typeof proxy === "string") {
      // Re-encode creds to work around Chromium parser truncating passwords
      // at '=' and other special chars (#157).
      return { proxyArgs: [`--proxy-server=${normalizeSocksStringUrl(proxy)}`] };
    }
    const socksUrl = reconstructSocksUrl(proxy);
    const args = [`--proxy-server=${socksUrl}`];
    if (proxy.bypass) args.push(`--proxy-bypass-list=${proxy.bypass}`);
    return { proxyArgs: args };
  }

  // HTTP/HTTPS with credentials on supported platforms: bypass Playwright's
  // CDP auth interceptor, use Chrome's preemptive Proxy-Authorization (#182).
  if (hasCredentials(proxy) && supportsHttpProxyInlineAuth()) {
    if (typeof proxy === "string") {
      return { proxyArgs: [`--proxy-server=${normalizeHttpStringUrl(proxy)}`] };
    }
    const httpUrl = reconstructHttpUrl(proxy);
    const args = [`--proxy-server=${httpUrl}`];
    if (proxy.bypass) args.push(`--proxy-bypass-list=${proxy.bypass}`);
    return { proxyArgs: args };
  }

  // HTTP/HTTPS without credentials (or unsupported platform): use Playwright's proxy dict
  if (typeof proxy === "string") {
    return { proxyOption: parseProxyUrl(proxy), proxyArgs: [] };
  }
  return { proxyOption: proxy as ParsedProxy, proxyArgs: [] };
}

export function parseProxyUrl(proxy: string): ParsedProxy {
  let url: URL;
  // Bare format: "user:pass@host:port" — new URL() throws without a scheme.
  const normalized =
    proxy.includes("@") && !proxy.includes("://") ? `http://${proxy}` : proxy;
  try {
    url = new URL(normalized);
  } catch {
    // Not a parseable URL (e.g. bare "host:port") — pass through as-is
    return { server: proxy };
  }

  if (!url.username) {
    return { server: proxy };
  }

  // Rebuild server URL without credentials
  const server = `${url.protocol}//${url.hostname}${url.port ? `:${url.port}` : ""}`;

  const result: ParsedProxy = {
    server,
    username: decodeURIComponent(url.username),
  };
  if (url.password) {
    result.password = decodeURIComponent(url.password);
  }

  return result;
}
