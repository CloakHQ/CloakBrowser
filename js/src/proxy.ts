/**
 * Shared proxy URL parsing for Playwright and Puppeteer wrappers.
 */

export interface ParsedProxy {
  server: string;
  username?: string;
  password?: string;
}

/**
 * Parse a proxy URL, extracting credentials into separate fields.
 *
 * Handles: "http://user:pass@host:port" -> { server: "http://host:port", username: "user", password: "pass" }
 * Also handles: no credentials, URL-encoded special chars, socks5://, missing port,
 * and bare proxy strings without a scheme (e.g. "user:pass@host:port" -> treated as http).
 */
export function parseProxyUrl(proxy: string): ParsedProxy {
  // Bare format: "user:pass@host:port" — no scheme.
  // new URL() needs a scheme to correctly parse credentials.
  let normalized = proxy;
  const hadScheme = proxy.includes("://");
  if (!hadScheme && proxy.includes("@")) {
    normalized = `http://${proxy}`;
  }

  let url: URL;
  try {
    url = new URL(normalized);
  } catch {
    // Not a parseable URL (e.g. bare "host:port") — pass through as-is
    return { server: proxy };
  }

  if (!url.username) {
    // No credentials found — if we added a scheme for bare host:port, keep it.
    if (!hadScheme && !proxy.includes("@")) {
      return { server: proxy };
    }
    return { server: normalized };
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
