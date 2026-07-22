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

  it("downloads the database once under concurrent first-use launches (#458)", async () => {
    const cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), "cloak-geoip-concurrent-"));
    tempDirs.push(cacheDir);
    process.env.CLOAKBROWSER_CACHE_DIR = cacheDir;
    // Short resolution budget so the post-download reader on the fake DB bails
    // fast (the download itself is exempt from this timeout).
    process.env.CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS = "0.2";

    // Slow response so all launches queue behind the first download.
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(
      () =>
        new Promise<Response>((resolve) =>
          setTimeout(
            () =>
              resolve({
                ok: true,
                body: new ReadableStream({
                  start(controller) {
                    controller.enqueue(new Uint8Array([1, 2, 3]));
                    controller.close();
                  },
                }),
              } as Response),
            50,
          ),
        ),
    );

    await Promise.all(
      Array.from({ length: 5 }, () => resolveProxyGeo("http://203.0.113.10:8080")),
    );

    // Only one launch actually fetched the shared ~70 MB file.
    expect(fetchSpy).toHaveBeenCalledOnce();
  });

  it("no proxy + both explicit: skips the exit-IP fetch entirely", async () => {
    // With no proxy the WebRTC IP would just be the real connection IP the site
    // already sees (a no-op), so maybeResolveGeoip must not call the echo services.
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      text: async () => "5.6.7.8",
    } as Response);

    const result = await maybeResolveGeoip({
      geoip: true,
      timezone: "Europe/Berlin",
      locale: "de-DE",
    });

    expect(result).toEqual({ timezone: "Europe/Berlin", locale: "de-DE" });
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("promotes raw tz/locale flags in args: no proxy + both raw-flagged skips fetch", async () => {
    // A raw --fingerprint-timezone/--fingerprint-locale in args counts as explicit,
    // so geoip must not clobber them (and, with no proxy, skips the echo fetch).
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      text: async () => "5.6.7.8",
    } as Response);

    const result = await maybeResolveGeoip({
      geoip: true,
      args: ["--fingerprint-timezone=Asia/Tokyo", "--fingerprint-locale=ja-JP"],
    });

    expect(result).toEqual({ timezone: "Asia/Tokyo", locale: "ja-JP" });
    expect(fetchSpy).not.toHaveBeenCalled();
    fetchSpy.mockRestore();
  });

  it("promoted raw flags survive a GeoIP timeout (with proxy)", async () => {
    const cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), "cloak-geoip-rawflag-"));
    tempDirs.push(cacheDir);
    process.env.CLOAKBROWSER_CACHE_DIR = cacheDir;
    process.env.CLOAKBROWSER_GEOIP_TIMEOUT_SECONDS = "0.025";

    const result = await maybeResolveGeoip({
      geoip: true,
      proxy: "http://203.0.113.10:8080",
      args: ["--fingerprint-timezone=Asia/Tokyo", "--lang=ja-JP"],
    });

    // --lang promotes to locale; both explicit → exit-IP-only path (times out → undefined).
    expect(result.timezone).toBe("Asia/Tokyo");
    expect(result.locale).toBe("ja-JP");
  });

  it("explicit timezone option beats a differing raw flag", async () => {
    const result = await maybeResolveGeoip({
      geoip: true,
      timezone: "America/New_York",
      locale: "en-US",
      args: ["--fingerprint-timezone=Asia/Tokyo"],
    });
    expect(result.timezone).toBe("America/New_York");
    expect(result.locale).toBe("en-US");
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
