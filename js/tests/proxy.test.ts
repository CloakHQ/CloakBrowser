import { describe, it, expect, vi } from "vitest";
import { isSocksProxy, resolveProxyConfig } from "../src/proxy.js";
import type { LaunchOptions } from "../src/types.js";

describe("proxy without credentials", () => {
  it("passes the string through as the Playwright server", () => {
    expect(resolveProxyConfig("http://proxy:8080")).toEqual({
      proxyOption: { server: "http://proxy:8080" },
      proxyArgs: [],
    });
  });

  it("passes an unparseable string through", () => {
    expect(resolveProxyConfig("not-a-url").proxyOption).toEqual({ server: "not-a-url" });
  });
});

describe("proxy dict type", () => {
  it("accepts string proxy in LaunchOptions", () => {
    const opts: LaunchOptions = { proxy: "http://proxy:8080" };
    expect(typeof opts.proxy).toBe("string");
  });

  it("accepts dict proxy with bypass in LaunchOptions", () => {
    const opts: LaunchOptions = {
      proxy: { server: "http://proxy:8080", bypass: ".google.com,localhost" },
    };
    expect(typeof opts.proxy).toBe("object");
    if (typeof opts.proxy === "object") {
      expect(opts.proxy.server).toBe("http://proxy:8080");
      expect(opts.proxy.bypass).toBe(".google.com,localhost");
    }
  });

  it("accepts dict proxy with auth and bypass in LaunchOptions", () => {
    const opts: LaunchOptions = {
      proxy: {
        server: "http://proxy:8080",
        username: "user",
        password: "pass",
        bypass: ".example.com",
      },
    };
    if (typeof opts.proxy === "object") {
      expect(opts.proxy.username).toBe("user");
      expect(opts.proxy.password).toBe("pass");
      expect(opts.proxy.bypass).toBe(".example.com");
    }
  });
});

describe("bare proxy format (no scheme)", () => {
  it("bare no credentials passes through unchanged", () => {
    expect(resolveProxyConfig("proxy:8080").proxyOption).toEqual({ server: "proxy:8080" });
  });
});

describe("isSocksProxy", () => {
  it("detects socks5 string", () => {
    expect(isSocksProxy("socks5://user:pass@host:1080")).toBe(true);
  });

  it("detects socks5h string", () => {
    expect(isSocksProxy("socks5h://host:1080")).toBe(true);
  });

  it("case insensitive", () => {
    expect(isSocksProxy("SOCKS5://host:1080")).toBe(true);
  });

  it("rejects http", () => {
    expect(isSocksProxy("http://host:8080")).toBe(false);
  });

  it("detects socks5 dict", () => {
    expect(isSocksProxy({ server: "socks5://host:1080" })).toBe(true);
  });

  it("rejects http dict", () => {
    expect(isSocksProxy({ server: "http://host:8080" })).toBe(false);
  });

  it("returns false for undefined", () => {
    expect(isSocksProxy(undefined)).toBe(false);
  });
});

describe("resolveProxyConfig", () => {
  // getPlatformTag derives from process.platform/arch at call time, so override
  // those to prove no platform falls back to Playwright's proxy dict.
  const origPlatform = Object.getOwnPropertyDescriptor(process, "platform")!;
  const origArch = Object.getOwnPropertyDescriptor(process, "arch")!;
  function setPlatform(platform: string, arch: string): void {
    Object.defineProperty(process, "platform", { value: platform, configurable: true });
    Object.defineProperty(process, "arch", { value: arch, configurable: true });
  }
  function restorePlatform(): void {
    Object.defineProperty(process, "platform", origPlatform);
    Object.defineProperty(process, "arch", origArch);
  }

  it("returns empty for undefined", () => {
    const { proxyOption, proxyArgs } = resolveProxyConfig(undefined);
    expect(proxyOption).toBeUndefined();
    expect(proxyArgs).toEqual([]);
  });

  it.each([
    ["linux", "x64"], ["linux", "arm64"], ["darwin", "arm64"], ["darwin", "x64"], ["win32", "x64"],
  ])("sends http creds inline on %s-%s (every served build ships inline auth)", (platform, arch) => {
    setPlatform(platform, arch);
    const prev = process.env.CLOAKBROWSER_BINARY_PATH;
    process.env.CLOAKBROWSER_BINARY_PATH = "/x/chrome"; // an unversioned override too
    try {
      const { proxyOption, proxyArgs } = resolveProxyConfig("http://user:pass@proxy:8080");
      expect(proxyOption).toBeUndefined();
      expect(proxyArgs).toEqual(["--proxy-server=http://user:pass@proxy:8080"]);
    } finally {
      restorePlatform();
      if (prev === undefined) delete process.env.CLOAKBROWSER_BINARY_PATH;
      else process.env.CLOAKBROWSER_BINARY_PATH = prev;
    }
  });

  it("returns playwright dict for http dict", () => {
    const proxy = { server: "http://proxy:8080", bypass: ".example.com" };
    const { proxyOption, proxyArgs } = resolveProxyConfig(proxy);
    expect(proxyOption).toEqual(proxy);
    expect(proxyArgs).toEqual([]);
  });

  it("returns chrome arg for socks5 string", () => {
    const { proxyOption, proxyArgs } = resolveProxyConfig("socks5://user:pass@host:1080");
    expect(proxyOption).toBeUndefined();
    expect(proxyArgs).toEqual(["--proxy-server=socks5://user:pass@host:1080"]);
  });

  it("returns chrome arg for socks5 no auth", () => {
    const { proxyOption, proxyArgs } = resolveProxyConfig("socks5://host:1080");
    expect(proxyOption).toBeUndefined();
    expect(proxyArgs).toEqual(["--proxy-server=socks5://host:1080"]);
  });

  it("returns chrome arg for socks5h string", () => {
    const { proxyOption, proxyArgs } = resolveProxyConfig("socks5h://user:pass@host:1080");
    expect(proxyOption).toBeUndefined();
    expect(proxyArgs).toEqual(["--proxy-server=socks5h://user:pass@host:1080"]);
  });

  it("reconstructs URL from socks5 dict with auth", () => {
    const { proxyOption, proxyArgs } = resolveProxyConfig({
      server: "socks5://host:1080",
      username: "user",
      password: "p@ss",
    });
    expect(proxyOption).toBeUndefined();
    expect(proxyArgs).toEqual(["--proxy-server=socks5://user:p%40ss@host:1080"]);
  });

  it("includes bypass for socks5 dict", () => {
    const { proxyArgs } = resolveProxyConfig({
      server: "socks5://host:1080",
      bypass: ".example.com",
    });
    expect(proxyArgs).toContain("--proxy-server=socks5://host:1080");
    expect(proxyArgs).toContain("--proxy-bypass-list=.example.com");
  });

  // Chromium's --proxy-server parser truncates passwords at '=' (#157).
  // Wrapper must auto URL-encode before passing to Chrome.
  it("encodes '=' in socks5 string password", () => {
    const { proxyArgs } = resolveProxyConfig("socks5://user:pass=123@host:1080");
    expect(proxyArgs).toEqual(["--proxy-server=socks5://user:pass%3D123@host:1080"]);
  });

  it("encoding is idempotent for already-encoded socks5 string", () => {
    const { proxyArgs } = resolveProxyConfig("socks5://user:pass%3D123@host:1080");
    expect(proxyArgs).toEqual(["--proxy-server=socks5://user:pass%3D123@host:1080"]);
  });

  it("leaves socks5 string without creds unchanged", () => {
    const { proxyArgs } = resolveProxyConfig("socks5://host:1080");
    expect(proxyArgs).toEqual(["--proxy-server=socks5://host:1080"]);
  });

  it("encodes password even with empty username (password-only userinfo)", () => {
    // Regression: empty-username bypass would skip encoding, leaving the
    // Chromium truncation bug alive for this userinfo shape.
    const { proxyArgs } = resolveProxyConfig("socks5://:pass=123@host:1080");
    expect(proxyArgs).toEqual(["--proxy-server=socks5://:pass%3D123@host:1080"]);
  });

  it("handles literal '%' in password without throwing (malformed escape)", () => {
    // JS's decodeURIComponent throws on '%sure' (% not followed by 2 hex digits).
    // Must fall back to treating '%' as literal and percent-encoding it.
    const { proxyArgs } = resolveProxyConfig("socks5://user:100%sure@host:1080");
    expect(proxyArgs).toEqual(["--proxy-server=socks5://user:100%25sure@host:1080"]);
  });

  it("passes malformed SOCKS5 URLs through unchanged (no throw)", () => {
    // Broken IPv6 bracket — wrapper must not throw;
    // Chromium will surface its own error.
    const { proxyArgs: a1 } = resolveProxyConfig("socks5://user:pass@[::1");
    expect(a1).toEqual(["--proxy-server=socks5://user:pass@[::1"]);
  });

  it("passes non-numeric port through unchanged", () => {
    const { proxyArgs } = resolveProxyConfig("socks5://user:pass@host:abc");
    expect(proxyArgs).toEqual(["--proxy-server=socks5://user:pass@host:abc"]);
  });

  it("encodes special chars in IPv6 SOCKS5 string password", () => {
    const { proxyArgs } = resolveProxyConfig("socks5://user:pass=eq@[::1]:1080");
    expect(proxyArgs).toEqual(["--proxy-server=socks5://user:pass%3Deq@[::1]:1080"]);
  });

  // Regression #157: userinfo must be split at the LAST '@' (RFC 3986),
  // not the first, so raw '@' in a password parses correctly.
  it("encodes raw '@' in socks5 string password (last-@ split)", () => {
    const { proxyArgs } = resolveProxyConfig("socks5://user:p@ss@host:1080");
    expect(proxyArgs).toEqual(["--proxy-server=socks5://user:p%40ss@host:1080"]);
  });

  it("handles multiple raw '@' in password (splits at last)", () => {
    const { proxyArgs } = resolveProxyConfig("socks5://user:a@b@c@host:1080");
    expect(proxyArgs).toEqual(["--proxy-server=socks5://user:a%40b%40c@host:1080"]);
  });

  // Visibility for #157: when wrapper actually rewrites the URL, surface an
  // info log so users debugging silent SOCKS5 fallback can see what happened.
  it("logs info message when SOCKS5 credentials get re-encoded", () => {
    const debugSpy = vi.spyOn(console, "info").mockImplementation(() => {});
    try {
      resolveProxyConfig("socks5://user:pass=123@host:1080");
      expect(debugSpy).toHaveBeenCalledWith(
        expect.stringContaining("Auto URL-encoded SOCKS5"),
      );
      // Credentials must not leak into the log.
      const calls = debugSpy.mock.calls.flat().join(" ");
      expect(calls).not.toContain("pass=123");
      expect(calls).not.toContain("pass%3D123");
    } finally {
      debugSpy.mockRestore();
    }
  });

  it("stays silent when SOCKS5 URL is already encoded (no log spam)", () => {
    const debugSpy = vi.spyOn(console, "info").mockImplementation(() => {});
    try {
      resolveProxyConfig("socks5://user:pass%3D123@host:1080");
      const reencodedCalls = debugSpy.mock.calls
        .flat()
        .filter((arg) => typeof arg === "string" && arg.includes("Auto URL-encoded SOCKS5"));
      expect(reencodedCalls).toHaveLength(0);
    } finally {
      debugSpy.mockRestore();
    }
  });

  it("stays silent when SOCKS5 URL has no credentials", () => {
    const debugSpy = vi.spyOn(console, "info").mockImplementation(() => {});
    try {
      resolveProxyConfig("socks5://host:1080");
      const reencodedCalls = debugSpy.mock.calls
        .flat()
        .filter((arg) => typeof arg === "string" && arg.includes("Auto URL-encoded SOCKS5"));
      expect(reencodedCalls).toHaveLength(0);
    } finally {
      debugSpy.mockRestore();
    }
  });

  it("stays silent when only host case differs (no credential rewrite)", () => {
    // Parity with Python: log condition must track credential changes, not
    // cosmetic URL-string differences (regression for Copilot's PR #209 review).
    const debugSpy = vi.spyOn(console, "info").mockImplementation(() => {});
    try {
      resolveProxyConfig("socks5://USER:pass@HOST.com:1080");
      const reencodedCalls = debugSpy.mock.calls
        .flat()
        .filter((arg) => typeof arg === "string" && arg.includes("Auto URL-encoded SOCKS5"));
      expect(reencodedCalls).toHaveLength(0);
    } finally {
      debugSpy.mockRestore();
    }
  });

  // --- HTTP with credentials → always inline via --proxy-server ---

  it("sends an http dict with creds inline", () => {
    const { proxyOption, proxyArgs } = resolveProxyConfig({
      server: "http://proxy:8080",
      username: "user",
      password: "pass",
    });
    expect(proxyOption).toBeUndefined();
    expect(proxyArgs).toEqual(["--proxy-server=http://user:pass@proxy:8080"]);
  });

  it("keeps the bypass list for an http dict with creds", () => {
    const { proxyArgs } = resolveProxyConfig({
      server: "http://proxy:8080",
      username: "user",
      password: "pass",
      bypass: ".google.com",
    });
    expect(proxyArgs).toContain("--proxy-server=http://user:pass@proxy:8080");
    expect(proxyArgs).toContain("--proxy-bypass-list=.google.com");
  });

  it("encodes special chars in an inline http proxy password", () => {
    const { proxyArgs } = resolveProxyConfig("http://user:pass=123@proxy:8080");
    expect(proxyArgs).toEqual(["--proxy-server=http://user:pass%3D123@proxy:8080"]);
  });
});
