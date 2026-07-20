import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import crypto from "node:crypto";

import {
  resolveLicenseKey,
  validateLicense,
  getProLatestVersion,
  getActiveSessionCount,
  buildLaunchEnv,
  licenseErrorMessage,
  licenseErrorFrom,
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
  try {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  } catch {}
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
