import { describe, it, expect } from "vitest";
import { parseProxyUrl } from "../src/proxy.js";

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
