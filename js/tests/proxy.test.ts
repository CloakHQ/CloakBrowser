import { describe, it, expect } from "vitest";
import { parseProxyUrl } from "../src/proxy.js";
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
