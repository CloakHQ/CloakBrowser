import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import * as license from "../src/license.js";
import * as geoip from "../src/geoip.js";

// collectDiagnostics reads the cache dir (license key file, binary path) and,
// in --quick mode, never spawns the binary — so an isolated temp cache dir is
// enough to get a deterministic "free / not installed" result with no network.
let tmpDir: string;
let prevCache: string | undefined;

beforeEach(() => {
  tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "cloak-cli-"));
  prevCache = process.env.CLOAKBROWSER_CACHE_DIR;
  process.env.CLOAKBROWSER_CACHE_DIR = tmpDir;
  delete process.env.CLOAKBROWSER_LICENSE_KEY;
  delete process.env.CLOAKBROWSER_BINARY_PATH;
  delete process.env.CLOAKBROWSER_RELEASE_CHANNEL;
});

afterEach(() => {
  if (prevCache === undefined) delete process.env.CLOAKBROWSER_CACHE_DIR;
  else process.env.CLOAKBROWSER_CACHE_DIR = prevCache;
  delete process.env.CLOAKBROWSER_RELEASE_CHANNEL;
  vi.restoreAllMocks();
  fs.rmSync(tmpDir, { recursive: true, force: true });
});

describe("collectDiagnostics", () => {
  it("skips the launch test with quick=true and reports a free license", async () => {
    const { collectDiagnostics } = await import("../src/cli.js");
    const diag = (await collectDiagnostics(true)) as Record<string, any>;

    expect(diag.environment.node).toBe(process.version);
    expect(diag.launch.tested).toBe(false);
    expect(diag.launch.reason).toContain("--quick");
    expect(diag.license.tier).toBe("free");
    expect(diag.modules).toBeDefined();
  });

  it("reports Preview to Stable fallback and the next launch version", async () => {
    process.env.CLOAKBROWSER_LICENSE_KEY = "cb_test";
    process.env.CLOAKBROWSER_RELEASE_CHANNEL = "preview";
    vi.spyOn(license, "validateLicense").mockResolvedValue({
      valid: true,
      plan: "business",
      expires: null,
    });
    vi.spyOn(license, "getProLatestRelease").mockResolvedValue({
      version: "150.0.7871.114.3",
      requestedChannel: "preview",
      resolvedChannel: "stable",
      fallback: true,
    });
    vi.spyOn(license, "getSessionSeats").mockResolvedValue({
      active: null, limit: null, state: "unknown", reason: null,
    });

    const { collectDiagnostics } = await import("../src/cli.js");
    const diag = (await collectDiagnostics(false)) as Record<string, any>;

    expect(diag.binary.requested_channel).toBe("preview");
    expect(diag.binary.resolved_channel).toBe("stable");
    expect(diag.binary.channel_fallback).toBe(true);
    expect(diag.binary.version).toBe("150.0.7871.114.3");
  });

  it("includes binary, fonts, geoip and module sections", async () => {
    const { collectDiagnostics } = await import("../src/cli.js");
    const diag = (await collectDiagnostics(true)) as Record<string, any>;

    expect(diag.binary).toBeDefined();
    // fonts section only present on Linux
    if (os.platform() === "linux") expect(diag.fonts.windows).toBeDefined();
    else expect(diag.fonts).toBeUndefined();
    expect(typeof diag.geoip.db_present).toBe("boolean");
    expect(Object.keys(diag.modules).length).toBeGreaterThan(0);
  });

  it("does not resolve geoip when no proxy is given", async () => {
    const spy = vi.spyOn(geoip, "resolveProxyGeo");
    const { collectDiagnostics } = await import("../src/cli.js");
    const diag = (await collectDiagnostics(true)) as Record<string, any>;
    expect(spy).not.toHaveBeenCalled();
    expect(diag.geoip.resolved).toBeUndefined();
  });

  it("resolves exit IP + timezone + locale when a proxy is given", async () => {
    const spy = vi.spyOn(geoip, "resolveProxyGeo").mockResolvedValue({
      timezone: "Europe/Berlin",
      locale: "de-DE",
      exitIp: "203.0.113.9",
    });
    const { collectDiagnostics } = await import("../src/cli.js");
    const diag = (await collectDiagnostics(true, "http://p:8080")) as Record<string, any>;
    expect(spy).toHaveBeenCalledWith("http://p:8080");
    expect(diag.geoip.resolved).toEqual({
      exit_ip: "203.0.113.9",
      timezone: "Europe/Berlin",
      locale: "de-DE",
    });
  });

  it("reports a resolution failure without throwing", async () => {
    vi.spyOn(geoip, "resolveProxyGeo").mockRejectedValue(new Error("proxy refused"));
    const { collectDiagnostics } = await import("../src/cli.js");
    const diag = (await collectDiagnostics(true, "http://p:8080")) as Record<string, any>;
    expect(diag.geoip.resolved.error).toContain("proxy refused");
  });
});

// ── formatSeats ───────────────────────────────────────
//
// Kept byte-identical to the Python (_format_seats) and .NET (FormatSeats)
// renderers — the three wrappers must print the same line for the same state.

describe("formatSeats", () => {
  const fmt = async (section: Record<string, unknown>) => {
    const { formatSeats } = await import("../src/cli.js");
    return formatSeats(section);
  };

  it("shows used over limit", async () => {
    // The point of the change: a scale-plan customer can see they are nowhere
    // near the ceiling (or right on it) instead of reading a bare number.
    expect(await fmt({ active: 8, limit: 2000, state: "ok" })).toBe("8/2000 in use");
  });

  it("falls back to the bare count when the server sends no limit", async () => {
    // Older server, unlimited licence, or an unrecognised plan. Never "8/unknown".
    expect(await fmt({ active: 8, limit: null, state: "ok" })).toBe("8 seats in use");
  });

  it("uses the singular in the fallback", async () => {
    expect(await fmt({ active: 1, limit: null, state: "ok" })).toBe("1 seat in use");
  });

  it("shows the limit for a single seat", async () => {
    // A free key holds exactly one seat — the cohort most likely to hit its cap.
    expect(await fmt({ active: 1, limit: 1, state: "ok" })).toBe("1/1 in use");
  });

  it("keeps zero as a real answer", async () => {
    expect(await fmt({ active: 0, limit: 5, state: "ok" })).toBe("0/5 in use");
  });

  it("says so when the server is unreachable", async () => {
    expect(await fmt({ state: "unreachable" })).toBe(
      "unavailable (cannot reach cloakbrowser.dev)"
    );
  });

  it.each([
    ["license_inactive", "license inactive"],
    ["invalid_key", "invalid key"],
    ["rate_limited", "rate limited"],
  ])("spells out the %s denial", async (code, shown) => {
    // These used to be one string. A dead key and a healthy key behind a
    // degraded backend must not read identically.
    expect(await fmt({ state: "denied", reason: code })).toBe(`unavailable (${shown})`);
  });

  it("passes an unrecognised denial reason through", async () => {
    expect(await fmt({ state: "denied", reason: "some_new_code" })).toBe(
      "unavailable (some_new_code)"
    );
  });

  it("does not make a degraded backend read like a licence problem", async () => {
    // Leaseless mode / seat store down: the key is fine, nothing for them to do.
    expect(await fmt({ state: "unknown" })).toBe(
      "unavailable (server cannot report seats right now)"
    );
  });
});
