import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import {
  CHROMIUM_VERSION,
  getChromiumVersion,
  getDownloadUrl,
  getEffectiveVersion,
  getPlatformTag,
  parseVersion,
  versionNewer,
} from "../src/config.js";
import {
  binaryInfo,
  checkForUpdate,
  checkWrapperUpdate,
  clearCache,
  ensureBinary,
  fetchChecksums,
  getLatestChromiumVersion,
  parseChecksums,
  resetWrapperUpdateChecked,
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
  const platformTarball = `cloakbrowser-${getPlatformTag()}.tar.gz`;

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
    const spy = mockFetch([
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
    // Default behavior — no marker file in test environment
    expect(getEffectiveVersion()).toBe(getChromiumVersion());
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
