import { describe, it, expect, afterEach } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { COUNTRY_LOCALE_MAP, maybeResolveGeoip, resolveProxyIp } from "../src/geoip.js";

const tempDirs: string[] = [];

afterEach(() => {
  delete process.env.CLOAKBROWSER_GEOIP_TIMEOUT_MS;
  delete process.env.CLOAKBROWSER_CACHE_DIR;
  for (const dir of tempDirs.splice(0)) fs.rmSync(dir, { recursive: true, force: true });
});

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

  it("returns null for schemeless proxy (shows why normalization is needed)", async () => {
    // no scheme — new URL() gives empty hostname for both bare formats
    expect(await resolveProxyIp("user:pass@10.50.96.5:8888")).toBeNull();
    expect(await resolveProxyIp("10.50.96.5:8888")).toBeNull();
  });

  it("extracts IP after normalization (http:// prepended by maybeResolveGeoip)", async () => {
    expect(await resolveProxyIp("http://user:pass@10.50.96.5:8888")).toBe("10.50.96.5");
    expect(await resolveProxyIp("http://10.50.96.5:8888")).toBe("10.50.96.5");
  });
});

describe("maybeResolveGeoip", () => {
  it("returns quickly when GeoIP resolution times out", async () => {
    const cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), "cloak-geoip-timeout-"));
    tempDirs.push(cacheDir);
    process.env.CLOAKBROWSER_CACHE_DIR = cacheDir;
    process.env.CLOAKBROWSER_GEOIP_TIMEOUT_MS = "25";

    const start = performance.now();
    const result = await maybeResolveGeoip({
      geoip: true,
      proxy: "http://203.0.113.10:8080",
      locale: "fr-FR",
    });
    const elapsed = performance.now() - start;

    expect(result).toEqual({ timezone: undefined, locale: "fr-FR" });
    expect(elapsed).toBeLessThan(500);
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
