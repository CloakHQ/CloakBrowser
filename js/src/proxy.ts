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
 * Also handles: no credentials, URL-encoded special chars, socks5://, missing port.
 */
export function parseProxyUrl(proxy: string): ParsedProxy {
  let url: URL;
  try {
    url = new URL(proxy);
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
