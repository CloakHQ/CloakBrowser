import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import {
  binarySupportsHeadlessNoViewport,
  binarySupportsHttpProxyInlineAuth,
  binarySupportsMaximizedWindow,
  getChromiumVersion,
  getBinaryPath,
  getDownloadUrl,
  getEffectiveVersion,
  getPlatformTag,
  parseVersion,
  versionNewer,
} from "../src/config.js";
import {
  checkForProUpdate,
  checkForUpdate,
  checkWrapperUpdate,
  clearCache,
  ensureBinary,
  fetchChecksums,
  getLatestChromiumVersion,
  parseChecksums,
  resetWrapperUpdateChecked,
  resetPreviewFallbackWarned,
} from "../src/download.js";

describe("version comparison", () => {
  it("parseVersion handles 4-part versions", () => {
    expect(parseVersion("145.0.7718.0")).toEqual([145, 0, 7718, 0]);
    expect(parseVersion("142.0.7444.175")).toEqual([142, 0, 7444, 175]);
  });

  it("detects newer version", () => {
    expect(versionNewer("145.0.7718.0", "142.0.7444.175")).toBe(true);
  });

  it("detects older version", () => {
    expect(versionNewer("142.0.7444.175", "145.0.7718.0")).toBe(false);
  });

  it("same version is not newer", () => {
    expect(versionNewer("142.0.7444.175", "142.0.7444.175")).toBe(false);
  });

  it("patch bump detected", () => {
    expect(versionNewer("142.0.7444.176", "142.0.7444.175")).toBe(true);
  });

  it("major bump wins over minor", () => {
    expect(versionNewer("143.0.0.0", "142.9.9999.999")).toBe(true);
  });

  it("parseVersion handles 5-part build numbers", () => {
    expect(parseVersion("145.0.7632.109.2")).toEqual([145, 0, 7632, 109, 2]);
  });

  it("build bump detected", () => {
    expect(versionNewer("145.0.7632.109.3", "145.0.7632.109.2")).toBe(true);
  });

  it("build suffix newer than no suffix", () => {
    expect(versionNewer("145.0.7632.109.2", "145.0.7632.109")).toBe(true);
  });

  it("no suffix older than build suffix", () => {
    expect(versionNewer("145.0.7632.109", "145.0.7632.109.2")).toBe(false);
  });
});

describe("download URL", () => {
  it("uses chromium-v prefix and cloakbrowser repo", () => {
    const url = getDownloadUrl();
    expect(url).toContain("cloakbrowser.dev");
    expect(url).toContain(`chromium-v${getChromiumVersion()}`);
    expect(url.endsWith(".tar.gz")).toBe(true);
  });

  it("accepts custom version", () => {
    const url = getDownloadUrl("145.0.7718.0");
    expect(url).toContain("chromium-v145.0.7718.0");
  });

  it("does not reference old repo", () => {
    const url = getDownloadUrl();
    expect(url).not.toContain("chromium-stealth-builds");
  });
});

describe("latest version (platform-aware)", () => {
  function makeAssets(platforms: string[]) {
    return platforms.map((p) => ({ name: `cloakbrowser-${p}.tar.gz` }));
  }

  function mockFetch(releases: Array<Record<string, unknown>>) {
    return vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => releases,
    } as Response);
  }

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns version when release has platform asset", async () => {
    mockFetch([
      {
        tag_name: "chromium-v145.0.7718.0",
        draft: false,
        assets: makeAssets(["linux-x64", "darwin-arm64", "darwin-x64", "windows-x64"]),
      },
    ]);
    expect(await getLatestChromiumVersion()).toBe("145.0.7718.0");
  });

  it("skips release without platform asset", async () => {
    mockFetch([
      {
        tag_name: "chromium-v145.0.7718.0",
        draft: false,
        assets: makeAssets(["linux-x64"]), // Linux only
      },
      {
        tag_name: "chromium-v142.0.7444.175",
        draft: false,
        assets: makeAssets(["linux-x64", "darwin-arm64", "darwin-x64", "windows-x64"]),
      },
    ]);
    const result = await getLatestChromiumVersion();
    const tag = getPlatformTag();
    if (tag === "linux-x64") {
      expect(result).toBe("145.0.7718.0");
    } else {
      expect(result).toBe("142.0.7444.175");
    }
  });

  it("returns null when no release has platform asset", async () => {
    mockFetch([
      {
        tag_name: "chromium-v145.0.7718.0",
        draft: false,
        assets: [{ name: "cloakbrowser-freebsd-x64.tar.gz" }],
      },
    ]);
    expect(await getLatestChromiumVersion()).toBeNull();
  });

  it("skips draft releases", async () => {
    const all = ["linux-x64", "darwin-arm64", "darwin-x64", "windows-x64"];
    mockFetch([
      { tag_name: "chromium-v999.0.0.0", draft: true, assets: makeAssets(all) },
      { tag_name: "chromium-v145.0.7718.0", draft: false, assets: makeAssets(all) },
    ]);
    expect(await getLatestChromiumVersion()).toBe("145.0.7718.0");
  });

  it("returns null on network error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("timeout"));
    expect(await getLatestChromiumVersion()).toBeNull();
  });
});

describe("wrapper update check", () => {
  beforeEach(() => {
    resetWrapperUpdateChecked();
    delete process.env.CLOAKBROWSER_AUTO_UPDATE;
    delete process.env.CLOAKBROWSER_DOWNLOAD_URL;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env.CLOAKBROWSER_AUTO_UPDATE;
    delete process.env.CLOAKBROWSER_DOWNLOAD_URL;
  });

  it("warns when newer version available", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ version: "99.0.0" }),
    } as Response);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    await checkWrapperUpdate();

    expect(spy).toHaveBeenCalledOnce();
    expect(warnSpy).toHaveBeenCalledWith(expect.stringContaining("Update available"));
  });

  it("silent when current version", async () => {
    const { WRAPPER_VERSION } = await import("../src/config.js");
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ version: WRAPPER_VERSION }),
    } as Response);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    await checkWrapperUpdate();

    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("disabled by CLOAKBROWSER_AUTO_UPDATE=false", async () => {
    process.env.CLOAKBROWSER_AUTO_UPDATE = "false";
    const spy = vi.spyOn(globalThis, "fetch");

    await checkWrapperUpdate();

    expect(spy).not.toHaveBeenCalled();
  });

  it("disabled by CLOAKBROWSER_DOWNLOAD_URL", async () => {
    process.env.CLOAKBROWSER_DOWNLOAD_URL = "https://mirror.example.com";
    const spy = vi.spyOn(globalThis, "fetch");

    await checkWrapperUpdate();

    expect(spy).not.toHaveBeenCalled();
  });

  it("silent on network error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("timeout"));
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    await checkWrapperUpdate();

    expect(warnSpy).not.toHaveBeenCalled();
  });

  it("runs only once per process", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ version: "0.0.1" }),
    } as Response);

    await checkWrapperUpdate();
    await checkWrapperUpdate();

    expect(spy).toHaveBeenCalledOnce();
  });
});

describe("parseChecksums", () => {
  // Valid 64-char hex strings for testing
  const HASH_A = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
  const HASH_B = "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2";

  it("parses standard SHA256SUMS format", () => {
    const text = [
      `${HASH_A}  cloakbrowser-linux-x64.tar.gz`,
      `${HASH_B}  cloakbrowser-darwin-arm64.tar.gz`,
    ].join("\n");
    const result = parseChecksums(text);
    expect(result.get("cloakbrowser-linux-x64.tar.gz")).toBe(HASH_A);
    expect(result.get("cloakbrowser-darwin-arm64.tar.gz")).toBe(HASH_B);
  });

  it("handles binary-mode asterisk prefix", () => {
    const text = `${HASH_A} *cloakbrowser-linux-x64.tar.gz`;
    const result = parseChecksums(text);
    expect(result.has("cloakbrowser-linux-x64.tar.gz")).toBe(true);
  });

  it("skips empty lines", () => {
    const text = `\n\n${HASH_A}  file.tar.gz\n\n`;
    expect(parseChecksums(text).size).toBe(1);
  });

  it("returns empty map for empty input", () => {
    expect(parseChecksums("").size).toBe(0);
    expect(parseChecksums("   \n  \n").size).toBe(0);
  });
});

describe("download fallback", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env.CLOAKBROWSER_DOWNLOAD_URL;
  });

  it("checksum fetch falls back to GitHub on primary 429", async () => {
    const HASH =
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
    const checksumText = `${HASH}  cloakbrowser-${getPlatformTag()}.tar.gz`;

    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : (input as Request).url;
      if (url.includes("cloakbrowser.dev")) {
        return {
          ok: false,
          status: 429,
          statusText: "Too Many Requests",
        } as Response;
      }
      // GitHub fallback
      return { ok: true, text: async () => checksumText } as Response;
    });

    const result = await fetchChecksums();
    expect(result).not.toBeNull();
    expect(
      result!.has(`cloakbrowser-${getPlatformTag()}.tar.gz`)
    ).toBe(true);
  });

  it("checksum fetch returns null when both sources fail", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 429,
      statusText: "Too Many Requests",
    } as Response);

    const result = await fetchChecksums();
    expect(result).toBeNull();
  });
});

describe("effective version", () => {
  it("returns platform version when no marker exists", () => {
    const orig = process.env.CLOAKBROWSER_CACHE_DIR;
    process.env.CLOAKBROWSER_CACHE_DIR = `/tmp/cloakbrowser-test-${Date.now()}`;
    try {
      expect(getEffectiveVersion()).toBe(getChromiumVersion());
    } finally {
      if (orig) process.env.CLOAKBROWSER_CACHE_DIR = orig;
      else delete process.env.CLOAKBROWSER_CACHE_DIR;
    }
  });

  // Ticket 431 Fix 4: a valid Pro license must NEVER fall back to the free binary.
  it("returns null for Pro when nothing is cached (never the free base)", () => {
    const orig = process.env.CLOAKBROWSER_CACHE_DIR;
    process.env.CLOAKBROWSER_CACHE_DIR = `/tmp/cloakbrowser-test-${Date.now()}-pro`;
    try {
      expect(getEffectiveVersion(true)).toBeNull();
      // Free tier still resolves to a concrete version.
      expect(getEffectiveVersion(false)).toBe(getChromiumVersion());
    } finally {
      if (orig) process.env.CLOAKBROWSER_CACHE_DIR = orig;
      else delete process.env.CLOAKBROWSER_CACHE_DIR;
    }
  });

  it("returns null for Pro when the marker's binary is missing", () => {
    const orig = process.env.CLOAKBROWSER_CACHE_DIR;
    const dir = `/tmp/cloakbrowser-test-${Date.now()}-promarker`;
    process.env.CLOAKBROWSER_CACHE_DIR = dir;
    try {
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(
        path.join(dir, `latest_pro_version_${getPlatformTag()}`),
        "148.0.7778.215.5"
      );
      // Marker present, but no binary on disk → null, not the free base.
      expect(getEffectiveVersion(true)).toBeNull();
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
      if (orig) process.env.CLOAKBROWSER_CACHE_DIR = orig;
      else delete process.env.CLOAKBROWSER_CACHE_DIR;
    }
  });
});

describe("preview Pro selection", () => {
  let cacheDir: string;
  let originalCacheDir: string | undefined;

  function createProBinary(version: string): string {
    const binaryPath = getBinaryPath(version, true);
    fs.mkdirSync(path.dirname(binaryPath), { recursive: true });
    fs.writeFileSync(binaryPath, "fake");
    fs.chmodSync(binaryPath, 0o755);
    return binaryPath;
  }

  beforeEach(() => {
    originalCacheDir = process.env.CLOAKBROWSER_CACHE_DIR;
    cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), "cloakbrowser-preview-"));
    process.env.CLOAKBROWSER_CACHE_DIR = cacheDir;
    delete process.env.CLOAKBROWSER_BINARY_PATH;
    delete process.env.CLOAKBROWSER_RELEASE_CHANNEL;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    fs.rmSync(cacheDir, { recursive: true, force: true });
    if (originalCacheDir === undefined) delete process.env.CLOAKBROWSER_CACHE_DIR;
    else process.env.CLOAKBROWSER_CACHE_DIR = originalCacheDir;
    delete process.env.CLOAKBROWSER_RELEASE_CHANNEL;
  });

  it("uses the selected channel for binary capability gates", () => {
    const stable = "145.0.1000.1";
    const preview = "148.0.7778.215.4";
    createProBinary(stable);
    createProBinary(preview);
    fs.writeFileSync(
      path.join(cacheDir, `latest_pro_version_${getPlatformTag()}`),
      stable,
    );
    fs.writeFileSync(
      path.join(cacheDir, `latest_pro_version_preview_${getPlatformTag()}`),
      preview,
    );

    expect(binarySupportsHeadlessNoViewport("cb_test", undefined, "stable")).toBe(false);
    expect(binarySupportsHeadlessNoViewport("cb_test", undefined, "preview")).toBe(true);
    expect(binarySupportsMaximizedWindow("cb_test", undefined, "preview")).toBe(true);
    expect(binarySupportsHttpProxyInlineAuth("cb_test", undefined, "stable")).toBe(false);
    expect(binarySupportsHttpProxyInlineAuth("cb_test", undefined, "preview")).toBe(true);
  });

  it("keeps a pinned preview launch isolated from latest markers", async () => {
    const pinned = "151.0.1000.1";
    const binaryPath = createProBinary(pinned);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ valid: true, plan: "solo", expires: null }),
    } as Response);

    await expect(ensureBinary("cb_test", pinned, "preview")).resolves.toBe(binaryPath);

    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(String(fetchSpy.mock.calls[0]![0])).toContain("/api/license/validate");
    expect(
      fs.existsSync(path.join(cacheDir, `latest_pro_version_preview_${getPlatformTag()}`)),
    ).toBe(false);
    expect(
      fs.existsSync(path.join(cacheDir, `latest_pro_version_${getPlatformTag()}`)),
    ).toBe(false);
  });

  it("uses preview latest without changing the stable marker", async () => {
    const stable = "150.0.1000.1";
    const preview = "151.0.1000.1";
    createProBinary(stable);
    const previewPath = createProBinary(preview);
    const stableMarker = path.join(cacheDir, `latest_pro_version_${getPlatformTag()}`);
    fs.writeFileSync(stableMarker, stable);
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/api/license/validate")) {
        return {
          ok: true,
          json: async () => ({ valid: true, plan: "solo", expires: null }),
        } as Response;
      }
      return {
        ok: true,
        json: async () => ({ version: preview }),
      } as Response;
    });

    await expect(ensureBinary("cb_test", undefined, "preview")).resolves.toBe(previewPath);

    expect(fetchSpy.mock.calls.some(([url]) => String(url).endsWith("?channel=preview"))).toBe(true);
    expect(fs.readFileSync(stableMarker, "utf-8")).toBe(stable);
    expect(
      fs.readFileSync(
        path.join(cacheDir, `latest_pro_version_preview_${getPlatformTag()}`),
        "utf-8",
      ),
    ).toBe(preview);
  });

  it("manual preview update advances only the preview marker", async () => {
    const stable = "150.0.1000.1";
    const preview = "151.0.1000.1";
    createProBinary(stable);
    createProBinary(preview);
    const stableMarker = path.join(cacheDir, `latest_pro_version_${getPlatformTag()}`);
    fs.writeFileSync(stableMarker, stable);
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ version: preview }),
    } as Response);

    await expect(checkForProUpdate("cb_test", "preview")).resolves.toBe(preview);

    expect(fs.readFileSync(stableMarker, "utf-8")).toBe(stable);
    expect(
      fs.readFileSync(
        path.join(cacheDir, `latest_pro_version_preview_${getPlatformTag()}`),
        "utf-8",
      ),
    ).toBe(preview);
  });

  it("warns when preview falls back to stable (no preview build for platform)", async () => {
    resetPreviewFallbackWarned();
    const stable = "150.0.1000.1";
    createProBinary(stable); // stable-fallback build already cached → no download
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).includes("/api/license/validate")) {
        return { ok: true, json: async () => ({ valid: true, plan: "solo", expires: null }) } as Response;
      }
      return {
        ok: true,
        json: async () => ({
          version: stable,
          requested_channel: "preview",
          resolved_channel: "stable",
          fallback: true,
        }),
      } as Response;
    });

    await ensureBinary("cb_test", undefined, "preview");

    expect(
      errSpy.mock.calls.some((c) => String(c[0]).includes("no preview build is available")),
    ).toBe(true);
  });

  it("does not warn for a genuine preview build", async () => {
    resetPreviewFallbackWarned();
    const preview = "151.0.1000.1";
    createProBinary(preview);
    const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      if (String(input).includes("/api/license/validate")) {
        return { ok: true, json: async () => ({ valid: true, plan: "solo", expires: null }) } as Response;
      }
      return {
        ok: true,
        json: async () => ({
          version: preview,
          requested_channel: "preview",
          resolved_channel: "preview",
          fallback: false,
        }),
      } as Response;
    });

    await ensureBinary("cb_test", undefined, "preview");

    expect(
      errSpy.mock.calls.some((c) => String(c[0]).includes("no preview build is available")),
    ).toBe(false);
  });

  it("aborts (never free) when the server rejects the key", async () => {
    delete process.env.CLOAKBROWSER_DOWNLOAD_URL;
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ valid: false, plan: "solo", expires: null }),
    } as Response);

    await expect(ensureBinary("cb_bad")).rejects.toThrow(/invalid or expired/);
  });

  it("aborts (never free) when the key cannot be validated (server down, no cache)", async () => {
    delete process.env.CLOAKBROWSER_DOWNLOAD_URL;
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("network down"));

    await expect(ensureBinary("cb_test")).rejects.toThrow(/could not be validated/);
  });
});

describe("ensureBinary", () => {
  afterEach(() => {
    delete process.env.CLOAKBROWSER_BINARY_PATH;
  });

  it("returns local override when set", async () => {
    // Use this test file as a "binary" that exists
    process.env.CLOAKBROWSER_BINARY_PATH = __filename;
    const result = await ensureBinary();
    expect(result).toBe(__filename);
  });

  it("throws when local override path missing", async () => {
    process.env.CLOAKBROWSER_BINARY_PATH = "/nonexistent/chrome";
    await expect(ensureBinary()).rejects.toThrow("does not exist");
  });
});

describe("clearCache", () => {
  it("does not throw when cache dir missing", () => {
    const orig = process.env.CLOAKBROWSER_CACHE_DIR;
    process.env.CLOAKBROWSER_CACHE_DIR = "/tmp/cloakbrowser-test-nonexistent";
    expect(() => clearCache()).not.toThrow();
    if (orig) {
      process.env.CLOAKBROWSER_CACHE_DIR = orig;
    } else {
      delete process.env.CLOAKBROWSER_CACHE_DIR;
    }
  });
});

describe("checkForUpdate", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("returns null when no newer version", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => [],
    } as Response);
    expect(await checkForUpdate()).toBeNull();
  });

  it("returns null on network error", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new Error("timeout"));
    expect(await checkForUpdate()).toBeNull();
  });
});

describe("welcome banner cadence", () => {
  let tmpDir: string;

  beforeEach(async () => {
    const os = (await import("node:os")).default;
    const fs = (await import("node:fs")).default;
    const path = (await import("node:path")).default;
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "cb-welcome-"));
  });

  it("Pro shows once then never", async () => {
    const fs = (await import("node:fs")).default;
    const path = (await import("node:path")).default;
    const { welcomeDue } = await import("../src/download.js");
    const marker = path.join(tmpDir, ".welcome_shown");
    expect(welcomeDue(marker, true)).toBe(true); // absent -> show
    fs.writeFileSync(marker, String(Math.floor(Date.now() / 1000)));
    expect(welcomeDue(marker, true)).toBe(false); // exists -> never again
  });

  it("free re-shows after the interval", async () => {
    const fs = (await import("node:fs")).default;
    const path = (await import("node:path")).default;
    const { welcomeDue, WELCOME_FREE_INTERVAL_SEC } = await import("../src/download.js");
    const marker = path.join(tmpDir, ".welcome_shown");
    const nowSec = Math.floor(Date.now() / 1000);
    expect(welcomeDue(marker, false)).toBe(true); // absent -> show
    fs.writeFileSync(marker, String(nowSec));
    expect(welcomeDue(marker, false)).toBe(false); // fresh -> skip
    fs.writeFileSync(marker, String(nowSec - WELCOME_FREE_INTERVAL_SEC - 10));
    expect(welcomeDue(marker, false)).toBe(true); // stale -> show again
  });

  it("legacy empty marker: free re-shows, Pro stays silent", async () => {
    const fs = (await import("node:fs")).default;
    const path = (await import("node:path")).default;
    const { welcomeDue } = await import("../src/download.js");
    const marker = path.join(tmpDir, ".welcome_shown");
    fs.writeFileSync(marker, ""); // pre-cadence empty marker
    expect(welcomeDue(marker, false)).toBe(true); // unparseable -> free re-shows
    expect(welcomeDue(marker, true)).toBe(false); // pro: existence = already shown
  });
});
