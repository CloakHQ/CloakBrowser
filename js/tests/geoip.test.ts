import { describe, it, expect, afterEach, vi } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { COUNTRY_LOCALE_MAP, maybeResolveGeoip, resolveProxyGeo, resolveProxyIp } from "../src/geoip.js";

const tempDirs: string[] = [];

afterEach(() => {
  vi.restoreAllMocks();
  delete process.env.CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS;
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
  it("does not apply the GeoIP resolution timeout to first-use database download", async () => {
    const cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), "cloak-geoip-download-"));
    tempDirs.push(cacheDir);
    process.env.CLOAKBROWSER_CACHE_DIR = cacheDir;
    process.env.CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS = "0.001";

    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      body: new ReadableStream({
        start(controller) {
          controller.enqueue(new Uint8Array([1, 2, 3]));
          controller.close();
        },
      }),
    } as Response);

    const result = await resolveProxyGeo("http://203.0.113.10:8080");

    expect(result).toEqual({ timezone: null, locale: null, exitIp: null });
    expect(fetchSpy).toHaveBeenCalledOnce();
    expect(fetchSpy.mock.calls[0][1]).toEqual({ redirect: "follow" });
  });

  it("returns quickly when GeoIP resolution times out", async () => {
    const cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), "cloak-geoip-timeout-"));
    tempDirs.push(cacheDir);
    process.env.CLOAKBROWSER_CACHE_DIR = cacheDir;
    process.env.CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS = "0.025";

    const start = performance.now();
    const result = await maybeResolveGeoip({
      geoip: true,
      proxy: "http://203.0.113.10:8080",
      timezone: "Europe/Paris",
      locale: "fr-FR",
    });
    const elapsed = performance.now() - start;

    expect(result).toEqual({ timezone: "Europe/Paris", locale: "fr-FR", exitIp: undefined });
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
