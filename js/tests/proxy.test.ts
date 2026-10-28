import { describe, it, expect, vi } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { parseProxyUrl, isSocksProxy, resolveProxyConfig } from "../src/proxy.js";
import * as config from "../src/config.js";
import type { LaunchOptions } from "../src/types.js";

describe("parseProxyUrl", () => {
  it("passes through URL without credentials", () => {
    expect(parseProxyUrl("http://proxy:8080")).toEqual({
      server: "http://proxy:8080",
    });
  });

  it("extracts credentials from URL", () => {
    expect(parseProxyUrl("http://user:pass@proxy:8080")).toEqual({
      server: "http://proxy:8080",
      username: "user",
      password: "pass",
    });
  });

  it("decodes URL-encoded special chars", () => {
    const result = parseProxyUrl("http://user:p%40ss%3Aword@proxy:8080");
    expect(result.password).toBe("p@ss:word");
    expect(result.username).toBe("user");
    expect(result.server).toBe("http://proxy:8080");
  });

  it("handles socks5 protocol", () => {
    const result = parseProxyUrl("socks5://user:pass@proxy:1080");
    expect(result.server).toBe("socks5://proxy:1080");
    expect(result.username).toBe("user");
    expect(result.password).toBe("pass");
  });

  it("handles URL without port", () => {
    const result = parseProxyUrl("http://user:pass@proxy");
    expect(result.server).toBe("http://proxy");
    expect(result.username).toBe("user");
  });

  it("handles username only (no password)", () => {
    const result = parseProxyUrl("http://user@proxy:8080");
    expect(result.server).toBe("http://proxy:8080");
    expect(result.username).toBe("user");
    expect(result.password).toBeUndefined();
  });

  it("passes through unparseable string", () => {
    expect(parseProxyUrl("not-a-url")).toEqual({ server: "not-a-url" });
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

describe("bare proxy format (user:pass@host:port)", () => {
  it("extracts credentials from bare format", () => {
    expect(parseProxyUrl("user:pass@proxy:8080")).toEqual({
      server: "http://proxy:8080",
      username: "user",
      password: "pass",
    });
  });

  it("credentials not in server", () => {
    const r = parseProxyUrl("user:pass@proxy1.example.com:5610");
    expect(r.server).not.toContain("user");
    expect(r.server).not.toContain("pass");
  });

  it("bare username only", () => {
    const r = parseProxyUrl("user@proxy:8080");
    expect(r.username).toBe("user");
    expect(r.password).toBeUndefined();
    expect(r.server).toBe("http://proxy:8080");
  });

  it("bare no port", () => {
    const r = parseProxyUrl("user:pass@proxy.example.com");
    expect(r.username).toBe("user");
    expect(r.server).toBe("http://proxy.example.com");
  });

  it("bare no credentials passes through unchanged", () => {
    expect(parseProxyUrl("proxy:8080")).toEqual({ server: "proxy:8080" });
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
  // binarySupportsHttpProxyInlineAuth reads getPlatformTag() intra-config, which
  // a vi.spyOn(config, ...) can't intercept (ESM live binding). getPlatformTag
  // derives from process.platform/arch at call time, so override those instead —
  // this correctly drives the per-platform floor lookup and version resolution.
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

  it("falls back to playwright dict for http string on free macOS", () => {
    setPlatform("darwin", "arm64");
    try {
      const { proxyOption, proxyArgs } = resolveProxyConfig("http://user:pass@proxy:8080");
      expect(proxyOption).toEqual({ server: "http://proxy:8080", username: "user", password: "pass" });
      expect(proxyArgs).toEqual([]);
    } finally {
      restorePlatform();
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

  // --- HTTP with credentials → --proxy-server (supported platform + version) ---

  // Supported cases pass the version via the browserVersion param (declared-pin
  // path) so resolution is deterministic; setPlatform drives the floor lookup.
  it("routes http string with creds through --proxy-server on linux-x64 v177.5", () => {
    setPlatform("linux", "x64");
    try {
      const { proxyOption, proxyArgs } = resolveProxyConfig(
        "http://user:pass@proxy:8080",
        "146.0.7680.177.5",
      );
      expect(proxyOption).toBeUndefined();
      expect(proxyArgs).toEqual(["--proxy-server=http://user:pass@proxy:8080"]);
    } finally {
      restorePlatform();
    }
  });

  it("routes http dict with creds through --proxy-server on linux-x64 v177.5", () => {
    setPlatform("linux", "x64");
    try {
      const { proxyOption, proxyArgs } = resolveProxyConfig(
        {
          server: "http://proxy:8080",
          username: "user",
          password: "pass",
        },
        "146.0.7680.177.5",
      );
      expect(proxyOption).toBeUndefined();
      expect(proxyArgs).toEqual(["--proxy-server=http://user:pass@proxy:8080"]);
    } finally {
      restorePlatform();
    }
  });

  it("includes bypass for http dict with creds on windows-x64 v177.5", () => {
    setPlatform("win32", "x64");
    try {
      const { proxyArgs } = resolveProxyConfig(
        {
          server: "http://proxy:8080",
          username: "user",
          password: "pass",
          bypass: ".google.com",
        },
        "146.0.7680.177.5",
      );
      expect(proxyArgs).toContain("--proxy-server=http://user:pass@proxy:8080");
      expect(proxyArgs).toContain("--proxy-bypass-list=.google.com");
    } finally {
      restorePlatform();
    }
  });

  it("encodes special chars in http proxy password on supported platform v177.5", () => {
    setPlatform("linux", "x64");
    try {
      const { proxyArgs } = resolveProxyConfig(
        "http://user:pass=123@proxy:8080",
        "146.0.7680.177.5",
      );
      expect(proxyArgs).toEqual(["--proxy-server=http://user:pass%3D123@proxy:8080"]);
    } finally {
      restorePlatform();
    }
  });

  it("falls back to playwright dict with an old pinned version", () => {
    setPlatform("linux", "x64");
    try {
      const { proxyOption, proxyArgs } = resolveProxyConfig(
        "http://user:pass@proxy:8080",
        "146.0.7680.177.3",
      );
      expect(proxyOption).toEqual({ server: "http://proxy:8080", username: "user", password: "pass" });
      expect(proxyArgs).toEqual([]);
    } finally {
      restorePlatform();
    }
  });

  it("inline auth for http with creds on a new pinned darwin-arm64 build", () => {
    setPlatform("darwin", "arm64");
    try {
      const { proxyOption, proxyArgs } = resolveProxyConfig(
        "http://user:pass@proxy:8080",
        "148.0.7778.215.3",
      );
      expect(proxyOption).toBeUndefined();
      expect(proxyArgs).toEqual(["--proxy-server=http://user:pass@proxy:8080"]);
    } finally {
      restorePlatform();
    }
  });

  it("falls back to playwright dict for http with creds on free linux-arm64", () => {
    setPlatform("linux", "arm64");
    try {
      const { proxyOption, proxyArgs } = resolveProxyConfig(
        "http://user:pass@proxy:8080",
        "146.0.7680.177.3",
      );
      expect(proxyOption).toBeDefined();
      expect(proxyArgs).toEqual([]);
    } finally {
      restorePlatform();
    }
  });

  it("uses the selected release channel for inline-auth gating", () => {
    const originalCacheDir = process.env.CLOAKBROWSER_CACHE_DIR;
    const cacheDir = `/tmp/cloakbrowser-proxy-preview-${Date.now()}`;
    process.env.CLOAKBROWSER_CACHE_DIR = cacheDir;
    try {
      for (const [channel, version] of [
        ["stable", "145.0.1000.1"],
        ["preview", "148.0.7778.215.4"],
      ] as const) {
        const binaryPath = config.getBinaryPath(version, true);
        fs.mkdirSync(path.dirname(binaryPath), { recursive: true });
        fs.writeFileSync(binaryPath, "fake");
        fs.chmodSync(binaryPath, 0o755);
        const markerPrefix = channel === "preview"
          ? "latest_pro_version_preview"
          : "latest_pro_version";
        fs.writeFileSync(
          path.join(cacheDir, `${markerPrefix}_${config.getPlatformTag()}`),
          version,
        );
      }

      const stable = resolveProxyConfig(
        "http://user:pass@proxy:8080",
        undefined,
        "cb_test",
        "stable",
      );
      const preview = resolveProxyConfig(
        "http://user:pass@proxy:8080",
        undefined,
        "cb_test",
        "preview",
      );

      expect(stable.proxyOption).toBeDefined();
      expect(stable.proxyArgs).toEqual([]);
      expect(preview.proxyOption).toBeUndefined();
      expect(preview.proxyArgs).toEqual([
        "--proxy-server=http://user:pass@proxy:8080",
      ]);
    } finally {
      fs.rmSync(cacheDir, { recursive: true, force: true });
      if (originalCacheDir === undefined) delete process.env.CLOAKBROWSER_CACHE_DIR;
      else process.env.CLOAKBROWSER_CACHE_DIR = originalCacheDir;
    }
  });
});
