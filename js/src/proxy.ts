/**
 * Shared proxy URL parsing for Playwright and Puppeteer wrappers.
 */

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
