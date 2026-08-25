import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";

import {
  resolveLicenseKey,
  validateLicense,
  getProLatestRelease,
  getProLatestVersion,
  getActiveSessionCount,
  getSessionSeats,
  buildLaunchEnv,
  licenseErrorMessage,
  licenseErrorFrom,
  licenseErrorForCode,
  readDenialFile,
  mintDenialFile,
  installLicenseGuard,
  LICENSE_STATUS_FILE_ENV,
  CloakBrowserLicenseError,
} from "../src/license.js";

import * as config from "../src/config.js";

let tmpDir: string;

beforeEach(() => {
  tmpDir = path.join("/tmp", `cloakbrowser-test-${Date.now()}`);
  fs.mkdirSync(tmpDir, { recursive: true });
  vi.spyOn(config, "getCacheDir").mockReturnValue(tmpDir);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  delete process.env.CLOAKBROWSER_RELEASE_CHANNEL;
  try {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  } catch (error) {
    console.error(`Failed to remove test directory ${tmpDir}:`, error);
  }
});

// ── resolveLicenseKey ─────────────────────────────────

describe("resolveLicenseKey", () => {
  it("explicit param wins over env", () => {
    process.env.CLOAKBROWSER_LICENSE_KEY = "env-key";
    expect(resolveLicenseKey("explicit")).toBe("explicit");
    delete process.env.CLOAKBROWSER_LICENSE_KEY;
  });

  it("env var fallback", () => {
    process.env.CLOAKBROWSER_LICENSE_KEY = "env-key";
    expect(resolveLicenseKey()).toBe("env-key");
    delete process.env.CLOAKBROWSER_LICENSE_KEY;
  });

  it("returns undefined when absent", () => {
    delete process.env.CLOAKBROWSER_LICENSE_KEY;
    expect(resolveLicenseKey()).toBeUndefined();
  });

  it("file fallback when no param or env", () => {
    delete process.env.CLOAKBROWSER_LICENSE_KEY;
    const keyFile = path.join(tmpDir, "license.key");
    fs.writeFileSync(keyFile, "file-key-123\n");
    expect(resolveLicenseKey()).toBe("file-key-123");
  });

  it("env takes precedence over file", () => {
    process.env.CLOAKBROWSER_LICENSE_KEY = "env-key";
    const keyFile = path.join(tmpDir, "license.key");
    fs.writeFileSync(keyFile, "file-key");
    expect(resolveLicenseKey()).toBe("env-key");
    delete process.env.CLOAKBROWSER_LICENSE_KEY;
  });

  it("returns undefined when file missing", () => {
    delete process.env.CLOAKBROWSER_LICENSE_KEY;
    expect(resolveLicenseKey()).toBeUndefined();
  });
});

// ── validateLicense ───────────────────────────────────

describe("validateLicense", () => {
  const keySha = crypto.createHash("sha256").update("test-key").digest("hex");

  it("fresh cache skips server call", async () => {
    const cachePath = path.join(tmpDir, ".license_cache");
    fs.writeFileSync(
      cachePath,
      JSON.stringify({
        key_sha256: keySha,
        valid: true,
        plan: "team",
        expires: "2026-12-01",
        validated_at: Date.now() / 1000,
      })
    );

    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const result = await validateLicense("test-key");

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(result).not.toBeNull();
    expect(result!.valid).toBe(true);
    expect(result!.plan).toBe("team");
  });

  it("stale cache triggers server call", async () => {
    const cachePath = path.join(tmpDir, ".license_cache");
    fs.writeFileSync(
      cachePath,
      JSON.stringify({
        key_sha256: keySha,
        valid: true,
        plan: "solo",
        expires: null,
        validated_at: Date.now() / 1000 - 90000, // 25 hours ago
      })
    );

    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ valid: true, plan: "solo", expires: null }),
    } as Response);

    const result = await validateLicense("test-key");
    expect(globalThis.fetch).toHaveBeenCalledOnce();
    expect(result!.valid).toBe(true);
  });

  it("server success returns LicenseInfo", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ valid: true, plan: "business", expires: "2026-07-13" }),
    } as Response);

    const result = await validateLicense("pro-key");
    expect(result).not.toBeNull();
    expect(result!.valid).toBe(true);
    expect(result!.plan).toBe("business");
    expect(result!.expires).toBe("2026-07-13");
  });

  it("server rejection returns invalid", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ valid: false, plan: "solo", expires: null }),
    } as Response);

    const result = await validateLicense("bad-key");
    expect(result).not.toBeNull();
    expect(result!.valid).toBe(false);
  });

  it("server unreachable uses stale cache", async () => {
    const cachePath = path.join(tmpDir, ".license_cache");
    fs.writeFileSync(
      cachePath,
      JSON.stringify({
        key_sha256: keySha,
        valid: true,
        plan: "solo",
        expires: "2026-12-01",
        validated_at: Date.now() / 1000 - 90000,
      })
    );

    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("timeout"));

    const result = await validateLicense("test-key");
    expect(result).not.toBeNull();
    expect(result!.valid).toBe(true);
  });

  it("server unreachable no cache returns null", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("timeout"));

    const result = await validateLicense("test-key");
    expect(result).toBeNull();
  });

  it("cache stores hash not raw key", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ valid: true, plan: "solo", expires: null }),
    } as Response);

    await validateLicense("secret-key-123");

    const cachePath = path.join(tmpDir, ".license_cache");
    const content = fs.readFileSync(cachePath, "utf-8");
    expect(content).not.toContain("secret-key-123");
    const expectedSha = crypto
      .createHash("sha256")
      .update("secret-key-123")
      .digest("hex");
    expect(content).toContain(expectedSha);
  });

  it("wrong key cache ignored", async () => {
    const cachePath = path.join(tmpDir, ".license_cache");
    fs.writeFileSync(
      cachePath,
      JSON.stringify({
        key_sha256: "other-hash",
        valid: true,
        plan: "solo",
        expires: null,
        validated_at: Date.now() / 1000,
      })
    );

    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ valid: true, plan: "solo", expires: null }),
    } as Response);

    await validateLicense("different-key");
    expect(globalThis.fetch).toHaveBeenCalledOnce();
  });

  it("expired license rejected from cache", async () => {
    const cachePath = path.join(tmpDir, ".license_cache");
    const keySha = crypto.createHash("sha256").update("test-key").digest("hex");
    fs.writeFileSync(
      cachePath,
      JSON.stringify({
        key_sha256: keySha,
        valid: true,
        plan: "solo",
        expires: "2020-01-01T00:00:00+00:00",
        validated_at: Date.now() / 1000,
      })
    );

    const result = await validateLicense("test-key");
    expect(result).not.toBeNull();
    expect(result!.valid).toBe(false);
  });

  it("does not cache invalid responses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ valid: false, plan: "solo", expires: null }),
    } as Response);

    await validateLicense("bad-key");

    const cachePath = path.join(tmpDir, ".license_cache");
    expect(fs.existsSync(cachePath)).toBe(false);
  });

  it("corrupted validated_at is treated as absent cache, not trusted", async () => {
    const keySha = crypto.createHash("sha256").update("test-key").digest("hex");
    fs.writeFileSync(
      path.join(tmpDir, ".license_cache"),
      JSON.stringify({
        key_sha256: keySha,
        valid: true,
        plan: "solo",
        expires: null,
        validated_at: "not-a-number",
      })
    );

    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ valid: true, plan: "solo", expires: null }),
    } as Response);

    const result = await validateLicense("test-key");
    expect(globalThis.fetch).toHaveBeenCalledOnce(); // corrupted cache ignored → server hit
    expect(result!.valid).toBe(true);
  });
});

// ── getProLatestVersion ───────────────────────────────

describe("getProLatestVersion", () => {
  it("fetches version from server", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ version: "147.0.1234.5" }),
    } as Response);

    const version = await getProLatestVersion();
    expect(version).toBe("147.0.1234.5");
  });

  it("uses an isolated endpoint and marker for preview", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        version: "150.0.7871.114.3",
        requested_channel: "preview",
        resolved_channel: "stable",
        fallback: true,
      }),
    } as Response);

    const release = await getProLatestRelease("preview");

    expect(release).toEqual({
      version: "150.0.7871.114.3",
      requestedChannel: "preview",
      resolvedChannel: "stable",
      fallback: true,
    });
    expect(fetchSpy.mock.calls[0]![0]).toBe(
      "https://cloakbrowser.dev/api/download/version?channel=preview",
    );
    expect(
      fs.readFileSync(
        path.join(tmpDir, `.last_pro_version_check_preview_${config.getPlatformTag()}`),
        "utf-8",
      ),
    ).toBe("150.0.7871.114.3");
    expect(
      fs.existsSync(path.join(tmpDir, `.last_pro_version_check_${config.getPlatformTag()}`)),
    ).toBe(false);
    const resolution = JSON.parse(fs.readFileSync(
      path.join(tmpDir, `.last_pro_version_resolution_preview_${config.getPlatformTag()}`),
      "utf-8",
    ));
    expect(resolution).toMatchObject({
      requested_channel: "preview",
      resolved_channel: "stable",
      fallback: true,
    });
    expect(resolution.requestedChannel).toBeUndefined();
  });

  it("reports an old server Preview response as Stable fallback", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ version: "150.0.7871.114.3" }),
    } as Response);

    const release = await getProLatestRelease("preview");

    expect(release?.resolvedChannel).toBe("stable");
    expect(release?.fallback).toBe(true);
  });

  it("reads a legacy JavaScript camelCase sidecar", async () => {
    const platform = config.getPlatformTag();
    fs.writeFileSync(
      path.join(tmpDir, `.last_pro_version_check_preview_${platform}`),
      "150.0.7871.114.3",
    );
    fs.writeFileSync(
      path.join(tmpDir, `.last_pro_version_resolution_preview_${platform}`),
      JSON.stringify({
        version: "150.0.7871.114.3",
        requestedChannel: "preview",
        resolvedChannel: "stable",
        fallback: true,
      }),
    );
    const fetchSpy = vi.spyOn(globalThis, "fetch");

    const release = await getProLatestRelease("preview");

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(release?.resolvedChannel).toBe("stable");
    expect(release?.fallback).toBe(true);
  });

  it("reads preview from the environment", async () => {
    process.env.CLOAKBROWSER_RELEASE_CHANNEL = "preview";
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ version: "151.0.1234.5" }),
    } as Response);

    await getProLatestVersion();

    expect(fetchSpy.mock.calls[0]![0]).toBe(
      "https://cloakbrowser.dev/api/download/version?channel=preview",
    );
  });

  it("explicit stable overrides a preview environment", async () => {
    process.env.CLOAKBROWSER_RELEASE_CHANNEL = "preview";
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ version: "150.0.1234.5" }),
    } as Response);

    await getProLatestVersion("stable");

    expect(fetchSpy.mock.calls[0]![0]).toBe(
      "https://cloakbrowser.dev/api/download/version",
    );
  });

  it("sends X-Platform header", async () => {
    vi.spyOn(config, "getPlatformTag").mockReturnValue("darwin-arm64");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ version: "147.0.1234.5" }),
    } as Response);

    await getProLatestVersion();

    const init = fetchSpy.mock.calls[0]![1] as RequestInit;
    expect((init.headers as Record<string, string>)["X-Platform"]).toBe(
      "darwin-arm64",
    );
  });

  it("rate limited by marker file", async () => {
    vi.spyOn(config, "getPlatformTag").mockReturnValue("darwin-arm64");
    const marker = path.join(tmpDir, ".last_pro_version_check_darwin-arm64");
    fs.writeFileSync(marker, "147.0.1234.5");
    fs.writeFileSync(
      path.join(tmpDir, ".last_pro_version_resolution_darwin-arm64"),
      JSON.stringify({
        version: "147.0.1234.5",
        requestedChannel: "stable",
        resolvedChannel: "stable",
        fallback: false,
      }),
    );

    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const version = await getProLatestVersion();

    expect(fetchSpy).not.toHaveBeenCalled();
    expect(version).toBe("147.0.1234.5");
  });

  it("network error returns null", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network"));
    const version = await getProLatestVersion();
    expect(version).toBeNull();
  });

  it("offline preview preserves the sidecar channel", async () => {
    // Stale marker (rate-limit expired) forces the network path; the server is
    // unreachable, so the offline branch must reuse the resolution sidecar
    // instead of mislabeling a genuine preview build as a stable fallback.
    vi.spyOn(config, "getPlatformTag").mockReturnValue("linux-x64");
    const marker = path.join(tmpDir, ".last_pro_version_check_preview_linux-x64");
    fs.writeFileSync(marker, "151.0.7900.10.1");
    fs.writeFileSync(
      path.join(tmpDir, ".last_pro_version_resolution_preview_linux-x64"),
      JSON.stringify({
        version: "151.0.7900.10.1",
        requestedChannel: "preview",
        resolvedChannel: "preview",
        fallback: false,
      }),
    );
    const old = Date.now() / 1000 - 7200; // 2h ago → past the 1h rate-limit window
    fs.utimesSync(marker, old, old);
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network"));

    const release = await getProLatestRelease("preview");

    expect(release?.version).toBe("151.0.7900.10.1");
    expect(release?.resolvedChannel).toBe("preview");
    expect(release?.fallback).toBe(false);
  });

  it("offline preview without a sidecar falls back to stable", async () => {
    vi.spyOn(config, "getPlatformTag").mockReturnValue("linux-x64");
    const marker = path.join(tmpDir, ".last_pro_version_check_preview_linux-x64");
    fs.writeFileSync(marker, "151.0.7900.10.1");
    const old = Date.now() / 1000 - 7200;
    fs.utimesSync(marker, old, old);
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network"));

    const release = await getProLatestRelease("preview");

    expect(release?.resolvedChannel).toBe("stable");
    expect(release?.fallback).toBe(true);
  });
});

// ── Config pro parameter ──────────────────────────────

describe("config pro parameter", () => {
  it("getBinaryDir adds -pro suffix", () => {
    const normal = config.getBinaryDir("147.0.0.0");
    const pro = config.getBinaryDir("147.0.0.0", true);
    expect(normal).toMatch(/chromium-147\.0\.0\.0$/);
    expect(pro).toMatch(/chromium-147\.0\.0\.0-pro$/);
  });

  it("getBinaryDir default has no suffix", () => {
    const normal = config.getBinaryDir("147.0.0.0");
    expect(normal).not.toMatch(/-pro$/);
  });
});

// ── buildLaunchEnv ─────────────────────────────────────

describe("buildLaunchEnv", () => {
  it("returns undefined with no key", () => {
    expect(buildLaunchEnv()).toBeUndefined();
    expect(buildLaunchEnv(undefined, { FOO: "bar" })).toEqual({ FOO: "bar" });
    // undefined values are filtered consistently across all return paths.
    expect(buildLaunchEnv(undefined, { FOO: "bar", BAZ: undefined })).toEqual({ FOO: "bar" });
  });

  it("injects env from explicit param", () => {
    const result = buildLaunchEnv("cb_key");
    expect(result).toBeDefined();
    expect(result!.CLOAKBROWSER_LICENSE_KEY).toBe("cb_key");
    expect(result!.PATH).toBeDefined(); // process.env preserved
  });

  it("returns undefined when key is in env without custom userEnv", () => {
    vi.stubGlobal("process", { env: { ...process.env, CLOAKBROWSER_LICENSE_KEY: "cb_env" } });
    expect(buildLaunchEnv()).toBeUndefined();
  });

  it("preserves key when env source with custom userEnv", () => {
    vi.stubGlobal("process", { env: { ...process.env, CLOAKBROWSER_LICENSE_KEY: "cb_env" } });
    const result = buildLaunchEnv(undefined, { MY_VAR: "1" });
    expect(result).toBeDefined();
    expect(result!.CLOAKBROWSER_LICENSE_KEY).toBe("cb_env");
    expect(result!.MY_VAR).toBe("1");
  });

  it("returns undefined with default file key (binary reads directly)", () => {
    const homeDir = path.join(tmpDir, "home");
    const defaultCache = path.join(homeDir, ".cloakbrowser");
    fs.mkdirSync(defaultCache, { recursive: true });
    fs.writeFileSync(path.join(defaultCache, "license.key"), "cb_file");

    // Both getCacheDir and os.homedir must point to the same place
    vi.spyOn(config, "getCacheDir").mockReturnValue(defaultCache);
    vi.spyOn(os, "homedir").mockReturnValue(homeDir);

    expect(buildLaunchEnv()).toBeUndefined();
    // With a custom userEnv, Playwright replaces the child env (which could
    // drop HOME and hide the file), so the key IS injected.
    expect(buildLaunchEnv(undefined, { KEEP: "me" })).toEqual({
      KEEP: "me",
      CLOAKBROWSER_LICENSE_KEY: "cb_file",
    });
  });

  it("injects env with custom cache dir file", () => {
    const homeDir = path.join(tmpDir, "custom-home");
    const customCache = path.join(tmpDir, "custom-cache");
    fs.mkdirSync(homeDir);
    fs.mkdirSync(customCache);
    fs.writeFileSync(path.join(customCache, "license.key"), "cb_custom");

    vi.stubGlobal("process", { env: {} });
    vi.spyOn(config, "getCacheDir").mockReturnValue(customCache);
    // Mock os.homedir to NOT match cache dir
    vi.spyOn(os, "homedir").mockReturnValue(homeDir);

    const result = buildLaunchEnv();
    expect(result).toBeDefined();
    expect(result!.CLOAKBROWSER_LICENSE_KEY).toBe("cb_custom");
  });

  it("explicit param merges userEnv without os.environ", () => {
    const result = buildLaunchEnv("cb_mine", { PATH: "/custom/bin" });
    expect(result).toBeDefined();
    expect(result!.CLOAKBROWSER_LICENSE_KEY).toBe("cb_mine");
    expect(result!.PATH).toBe("/custom/bin");
    // Should NOT have full process.env
    expect(result!.HOME).toBeUndefined();
  });

  it("empty licenseKey treated as missing", () => {
    expect(buildLaunchEnv("")).toBeUndefined();
    expect(buildLaunchEnv("   ")).toBeUndefined();
  });

  it("statusFile is carried on an inherit-parent-env path", () => {
    const prev = process.env.CLOAKBROWSER_LICENSE_KEY;
    process.env.CLOAKBROWSER_LICENSE_KEY = "cb_env";
    try {
      const result = buildLaunchEnv(undefined, undefined, "/tmp/denials/x.json");
      expect(result).toBeDefined();
      expect(result![LICENSE_STATUS_FILE_ENV]).toBe("/tmp/denials/x.json");
      expect(result!.CLOAKBROWSER_LICENSE_KEY).toBe("cb_env");
    } finally {
      if (prev === undefined) delete process.env.CLOAKBROWSER_LICENSE_KEY;
      else process.env.CLOAKBROWSER_LICENSE_KEY = prev;
    }
  });

  it("omitting statusFile preserves original behavior", () => {
    const prev = process.env.CLOAKBROWSER_LICENSE_KEY;
    process.env.CLOAKBROWSER_LICENSE_KEY = "cb_env";
    try {
      expect(buildLaunchEnv()).toBeUndefined();
    } finally {
      if (prev === undefined) delete process.env.CLOAKBROWSER_LICENSE_KEY;
      else process.env.CLOAKBROWSER_LICENSE_KEY = prev;
    }
  });
});

// ── post-handshake denial: helpers + guard ─────────────
describe("denial file + license guard", () => {
  let tmpDir: string;
  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "cloak-denial-"));
  });
  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it.each([
    [76, "session limit"],
    [77, "invalid, expired, or missing"],
    [78, "couldn't verify"],
    [79, "not writable"],
  ])("licenseErrorForCode maps %i", (code, fragment) => {
    const err = licenseErrorForCode(code as number);
    expect(err).toBeInstanceOf(CloakBrowserLicenseError);
    expect(err!.message).toContain(fragment as string);
  });

  it("licenseErrorForCode returns null for an unknown code", () => {
    expect(licenseErrorForCode(1)).toBeNull();
    expect(licenseErrorForCode(0)).toBeNull();
  });

  it("readDenialFile returns the code and consumes the file", () => {
    const f = path.join(tmpDir, "d.json");
    fs.writeFileSync(f, "76");
    expect(readDenialFile(f)).toBe(76);
    expect(fs.existsSync(f)).toBe(false);
  });

  it("readDenialFile still returns the code on a second read after it was consumed", () => {
    const f = path.join(tmpDir, "d.json");
    fs.writeFileSync(f, "76");
    expect(readDenialFile(f)).toBe(76);
    expect(fs.existsSync(f)).toBe(false);   // consumed
    expect(readDenialFile(f)).toBe(76);     // file gone, cached in-process
  });

  it("readDenialFile returns null for missing/garbage", () => {
    expect(readDenialFile(path.join(tmpDir, "nope.json"))).toBeNull();
    const bad = path.join(tmpDir, "bad.json");
    fs.writeFileSync(bad, "not-json");
    expect(readDenialFile(bad)).toBeNull();
    expect(fs.existsSync(bad)).toBe(false);
  });

  it("mintDenialFile returns a path under a denials dir", () => {
    const spy = vi.spyOn(os, "homedir").mockReturnValue(tmpDir);
    try {
      const p = mintDenialFile();
      expect(p).toBeDefined();
      expect(p!.endsWith(".json")).toBe(true);
      expect(p).toContain("denials");
      expect(fs.existsSync(path.join(tmpDir, ".cloakbrowser", "denials"))).toBe(true);
    } finally {
      spy.mockRestore();
    }
  });

  it("mintDenialFile sweeps stale denial files but keeps fresh ones", () => {
    const spy = vi.spyOn(os, "homedir").mockReturnValue(tmpDir);
    try {
      const denials = path.join(tmpDir, ".cloakbrowser", "denials");
      fs.mkdirSync(denials, { recursive: true });
      const stale = path.join(denials, "stale.json");
      fs.writeFileSync(stale, "76");
      const old = Date.now() / 1000 - 7200; // 2h ago (seconds for utimesSync)
      fs.utimesSync(stale, old, old);
      const fresh = path.join(denials, "fresh.json"); // a concurrent live denial
      fs.writeFileSync(fresh, "76");

      mintDenialFile();

      expect(fs.existsSync(stale)).toBe(false); // orphan swept
      expect(fs.existsSync(fresh)).toBe(true);  // in-flight denial untouched
    } finally {
      spy.mockRestore();
    }
  });

  const NAV_METHODS = ["goto", "reload", "waitForLoadState", "waitForURL", "waitForSelector"];

  it("guard raises CloakBrowserLicenseError when the denial file is present", async () => {
    const f = path.join(tmpDir, "d.json");
    fs.writeFileSync(f, "76");
    const target: any = {
      newPage: async () => { throw new Error("Target page, context or browser has been closed"); },
    };
    installLicenseGuard(target, f);
    await expect(target.newPage()).rejects.toThrow(CloakBrowserLicenseError);
  });

  it("guard passes the original error through when there is no file", async () => {
    const original = new Error("real crash");
    const target: any = { newPage: async () => { throw original; } };
    installLicenseGuard(target, path.join(tmpDir, "absent.json"));
    await expect(target.newPage()).rejects.toBe(original);
  });

  it("guard passes through when the file is garbage", async () => {
    const f = path.join(tmpDir, "bad.json");
    fs.writeFileSync(f, "garbage");
    const original = new Error("real crash");
    const target: any = { newPage: async () => { throw original; } };
    installLicenseGuard(target, f);
    await expect(target.newPage()).rejects.toBe(original);
  });

  // The binary writes the denial file the instant it's over cap but keeps
  // serving (blank) responses for ~1s before it exits, so a fast flow that never
  // throws must still surface it. The guard checks the file after every call.
  it("guard surfaces a denial on a SUCCESSFUL call", async () => {
    const f = path.join(tmpDir, "d.json");
    fs.writeFileSync(f, "76");
    const target: any = { goto: async () => "ok" }; // resolves, never throws
    installLicenseGuard(target, f);
    await expect(target.goto()).rejects.toThrow(CloakBrowserLicenseError);
  });

  // Sync methods (url(), isClosed(), on()) must stay sync — wrapping them in an
  // async function would turn their return value into a Promise and break them.
  it("guard preserves a sync method's return value", () => {
    const target: any = { url: () => "https://example.com" };
    installLicenseGuard(target, path.join(tmpDir, "absent.json"));
    expect(target.url()).toBe("https://example.com"); // not a Promise
  });

  it("guard surfaces a denial from a sync method too", () => {
    const f = path.join(tmpDir, "d.json");
    fs.writeFileSync(f, "76");
    const target: any = { url: () => "https://example.com" };
    installLicenseGuard(target, f);
    expect(() => target.url()).toThrow(CloakBrowserLicenseError);
  });

  // A persistent context arrives with pages()[0] already open, so the user
  // navigates that page directly and never calls newPage. The pre-open page's
  // navigation entry points must surface the denial too.
  it.each([...NAV_METHODS])(
    "guard surfaces the denial on a pre-open page's %s()",
    async (method) => {
      const f = path.join(tmpDir, "d.json");
      fs.writeFileSync(f, "76");
      const page: any = {};
      for (const m of NAV_METHODS) {
        page[m] = async () => { throw new Error("Target page, context or browser has been closed"); };
      }
      installLicenseGuard(page, f);
      await expect(page[method]()).rejects.toThrow(CloakBrowserLicenseError);
    },
  );

  it("pre-open page guard passes a genuine failure through untouched", async () => {
    const original = new Error("real crash");
    const page: any = { goto: async () => { throw original; } };
    installLicenseGuard(page, path.join(tmpDir, "absent.json"));
    await expect(page.goto()).rejects.toBe(original);
  });

  // A denial that lands AFTER launch — once the user already holds a page from
  // newPage() — must surface on that page's first call. newPage/newContext/
  // createBrowserContext deep-guard the object they return.
  it("deep-guards the page a factory hands back", async () => {
    const f = path.join(tmpDir, "d.json");
    const page: any = { goto: async () => { throw new Error("Target page, context or browser has been closed"); } };
    const browser: any = { newPage: async () => page };
    installLicenseGuard(browser, f);
    const created = await browser.newPage();   // succeeds; no denial yet
    fs.writeFileSync(f, "76");                  // denial lands after handover
    await expect(created.goto()).rejects.toThrow(CloakBrowserLicenseError);
  });

  it("deep-guards newPage on a context a factory hands back", async () => {
    const f = path.join(tmpDir, "d.json");
    const ctx: any = {
      newPage: async () => { throw new Error("Target page, context or browser has been closed"); },
    };
    const browser: any = { createBrowserContext: async () => ctx };
    installLicenseGuard(browser, f);
    const created = await browser.createBrowserContext();  // succeeds; no denial yet
    fs.writeFileSync(f, "76");                              // denial lands after handover
    await expect(created.newPage()).rejects.toThrow(CloakBrowserLicenseError);
  });

  it("surfaces a denial thrown during context creation", async () => {
    const f = path.join(tmpDir, "d.json");
    fs.writeFileSync(f, "76");
    const browser: any = {
      createBrowserContext: async () => { throw new Error("Target page, context or browser has been closed"); },
    };
    installLicenseGuard(browser, f);
    await expect(browser.createBrowserContext()).rejects.toThrow(CloakBrowserLicenseError);
  });
});

describe("license exit-code surfacing", () => {
  const playwrightText = (code: number) =>
    "BrowserType.launch: Target page, context or browser has been closed\n" +
    `Browser logs:\n- [pid=123] <process did exit: exitCode=${code}, signal=null>`;
  const puppeteerText = (code: number) =>
    `Failed to launch the browser process!\nBrowser process exited with code ${code}`;

  it.each([
    [76, "session limit"],
    [77, "invalid, expired, or missing"],
    [78, "couldn't verify"],
    [79, "not writable"],
  ])("maps Playwright exitCode=%i", (code, fragment) => {
    const msg = licenseErrorMessage(playwrightText(code as number));
    expect(msg).not.toBeNull();
    expect(msg).toContain(fragment as string);
    expect(msg!.startsWith("CloakBrowser Pro:")).toBe(true);
  });

  it("maps the Puppeteer 'exited with code N' phrasing", () => {
    expect(licenseErrorMessage(puppeteerText(76))).toContain("session limit");
    expect(licenseErrorMessage(puppeteerText(77))).toContain("invalid");
  });

  it("returns null for a non-license exit code (passthrough)", () => {
    expect(licenseErrorMessage(playwrightText(1))).toBeNull();
    expect(licenseErrorMessage(puppeteerText(139))).toBeNull();
    // Large SEH-style code (Windows access violation 0xC0000005) must not
    // false-match or overflow.
    expect(licenseErrorMessage(playwrightText(3221225477))).toBeNull();
  });

  it("returns null when the text has no exit code (bare TargetClosedError)", () => {
    expect(licenseErrorMessage("Target page, context or browser has been closed")).toBeNull();
    expect(licenseErrorMessage("")).toBeNull();
  });

  it("licenseErrorFrom returns a typed error for a license exit, else null", () => {
    const lic = licenseErrorFrom(new Error(playwrightText(77)));
    expect(lic).toBeInstanceOf(CloakBrowserLicenseError);
    expect(lic!.message).toContain("invalid");
    expect(licenseErrorFrom(new Error("some unrelated crash"))).toBeNull();
  });
});

// ── getActiveSessionCount ─────────────────────────────

describe("getActiveSessionCount", () => {
  const ok = (payload: unknown) =>
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => payload,
    } as Response);

  it("returns the live seat count", async () => {
    ok({ valid: true, active: 3 });
    expect(await getActiveSessionCount("cb_key")).toBe(3);
  });

  it("posts the key in the body", async () => {
    // POST, not GET: the key is a live credential and a query string would land
    // in the server's access log.
    ok({ valid: true, active: 0 });
    await getActiveSessionCount("cb_key");

    const [url, init] = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("https://cloakbrowser.dev/api/license/session/count");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual({ license_key: "cb_key" });
  });

  it("distinguishes zero seats from an unknown count", async () => {
    // 0 is a real answer ("nothing running"); null means "couldn't tell". They
    // print differently, so 0 must not collapse to null.
    ok({ valid: true, active: 0 });
    expect(await getActiveSessionCount("cb_key")).toBe(0);
  });

  it("returns null when the server reports the count as unavailable", async () => {
    // Leaseless mode on the server → {"active": null}, never a false 0.
    ok({ valid: true, active: null });
    expect(await getActiveSessionCount("cb_key")).toBeNull();
  });

  it("returns null on a network error rather than throwing", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("timeout"));
    expect(await getActiveSessionCount("cb_key")).toBeNull();
  });

  it("returns null on a denial", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 403,
      statusText: "Forbidden",
      json: async () => ({ valid: false, error: "invalid_key" }),
    } as Response);
    expect(await getActiveSessionCount("cb_bad")).toBeNull();
  });

  it("is never cached", async () => {
    // validateLicense caches 24h; a cached seat count would be a wrong seat
    // count, so every call must hit the network.
    ok({ valid: true, active: 2 });
    await getActiveSessionCount("cb_key");
    await getActiveSessionCount("cb_key");
    expect(globalThis.fetch).toHaveBeenCalledTimes(2);
  });
});

// ── getSessionSeats ───────────────────────────────────

describe("getSessionSeats", () => {
  // The six failure paths that used to collapse into one bare null.
  const ok = (payload: unknown) =>
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => payload,
    } as Response);

  const denied = (status: number, payload: unknown) =>
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status,
      statusText: "Denied",
      json: async () => payload,
    } as Response);

  it("reports the count and the limit", async () => {
    ok({ valid: true, active: 8, limit: 2000 });
    expect(await getSessionSeats("cb_key")).toEqual({
      active: 8, limit: 2000, state: "ok", reason: null,
    });
  });

  it("treats a missing limit as null, not an error", async () => {
    // A server predating the field still yields a usable count.
    ok({ valid: true, active: 8 });
    const seats = await getSessionSeats("cb_key");
    expect(seats.state).toBe("ok");
    expect(seats.active).toBe(8);
    expect(seats.limit).toBeNull();
  });

  it("treats an explicit null limit as null", async () => {
    // Unlimited licence or unrecognised plan — the server says so explicitly.
    ok({ valid: true, active: 3, limit: null });
    expect((await getSessionSeats("cb_key")).limit).toBeNull();
  });

  it("keeps zero seats as a real answer", async () => {
    ok({ valid: true, active: 0, limit: 5 });
    const seats = await getSessionSeats("cb_key");
    expect(seats.state).toBe("ok");
    expect(seats.active).toBe(0);
  });

  it("reports a network failure as unreachable", async () => {
    // info is a diagnostic — it degrades, it never throws out of the command.
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("timeout"));
    const seats = await getSessionSeats("cb_key");
    expect(seats.state).toBe("unreachable");
    expect(seats.active).toBeNull();
  });

  it("carries the server's reason on a denial", async () => {
    denied(403, { valid: false, error: "license_inactive" });
    const seats = await getSessionSeats("cb_key");
    expect(seats.state).toBe("denied");
    expect(seats.reason).toBe("license_inactive");
  });

  it("treats a rate limit as a denial", async () => {
    denied(429, { valid: false, error: "rate_limited" });
    expect((await getSessionSeats("cb_key")).reason).toBe("rate_limited");
  });

  it("falls back to the status when a denial has no body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 500,
      statusText: "Server Error",
      json: async () => {
        throw new Error("not json");
      },
    } as unknown as Response);
    expect((await getSessionSeats("cb_key")).reason).toBe("HTTP 500");
  });

  it("reports a server-side unknown as unknown, not denied", async () => {
    // Leaseless mode: 200, key is fine, the server just cannot count. This is the
    // distinction the old single null destroyed.
    ok({ valid: true, active: null, limit: null });
    const seats = await getSessionSeats("cb_key");
    expect(seats.state).toBe("unknown");
    expect(seats.active).toBeNull();
  });

  it("reports an unparseable body as unknown", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => {
        throw new Error("not json");
      },
    } as unknown as Response);
    expect((await getSessionSeats("cb_key")).state).toBe("unknown");
  });

  it("keeps getActiveSessionCount returning the bare count", async () => {
    // It is shipped public API — it must keep behaving.
    ok({ valid: true, active: 4, limit: 20 });
    expect(await getActiveSessionCount("cb_key")).toBe(4);
  });
});
