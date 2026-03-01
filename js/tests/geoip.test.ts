import { describe, it, expect } from "vitest";
import { COUNTRY_LOCALE_MAP, resolveProxyIp } from "../src/geoip.js";

describe("resolveProxyIp", () => {
  it("returns literal IPv4 from proxy URL", async () => {
    expect(await resolveProxyIp("http://10.50.96.5:8888")).toBe("10.50.96.5");
  });

  it("handles proxy URL with credentials", async () => {
    expect(await resolveProxyIp("http://user:pass@10.50.96.5:8888")).toBe(
      "10.50.96.5"
    );
  });

  it("resolves localhost", async () => {
    const ip = await resolveProxyIp("http://localhost:8888");
    expect(ip).toBeTruthy();
    expect(["127.0.0.1", "::1"]).toContain(ip);
  });

  it("returns null for invalid URL", async () => {
    expect(await resolveProxyIp("not-a-url")).toBeNull();
  });

  it("returns null for empty string", async () => {
    expect(await resolveProxyIp("")).toBeNull();
  });
});

describe("COUNTRY_LOCALE_MAP", () => {
  it("contains common countries", () => {
    for (const code of ["US", "GB", "DE", "FR", "JP", "BR", "IL", "RU"]) {
      expect(COUNTRY_LOCALE_MAP[code]).toBeDefined();
    }
  });

  it("values are BCP 47 language-REGION format", () => {
    for (const [code, locale] of Object.entries(COUNTRY_LOCALE_MAP)) {
      const parts = locale.split("-");
      expect(parts).toHaveLength(2);
      expect(parts[0]).toMatch(/^[a-z]{2,3}$/);
      expect(parts[1]).toMatch(/^[A-Z]{2}$/);
    }
  });
});
