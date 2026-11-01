import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { execFile } from "node:child_process";
import * as fs from "node:fs";
import * as http from "node:http";
import type { AddressInfo } from "node:net";
import * as os from "node:os";
import * as path from "node:path";
import { promisify } from "node:util";
import { createHash, generateKeyPairSync, sign as cryptoSign } from "node:crypto";
import {
  BINARY_SIGNING_PUBKEYS,
  getArchiveName,
  getBinaryDir,
  getBinaryPath,
  getEffectiveVersion,
  getPlatformTag,
  parseVersion,
  versionNewer,
} from "../src/config.js";
import {
  checkForProUpdate,
  checkWrapperUpdate,
  clearCache,
  ensureBinary,
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

describe("wrapper update check", () => {
  beforeEach(() => {
    resetWrapperUpdateChecked();
    delete process.env.CLOAKBROWSER_AUTO_UPDATE;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    delete process.env.CLOAKBROWSER_AUTO_UPDATE;
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

describe("effective version", () => {
  it("returns null when nothing is cached", () => {
    const orig = process.env.CLOAKBROWSER_CACHE_DIR;
    process.env.CLOAKBROWSER_CACHE_DIR = `/tmp/cloakbrowser-test-${Date.now()}-pro`;
    try {
      expect(getEffectiveVersion()).toBeNull();
    } finally {
      if (orig) process.env.CLOAKBROWSER_CACHE_DIR = orig;
      else delete process.env.CLOAKBROWSER_CACHE_DIR;
    }
  });

  it("returns null when the marker's binary is missing", () => {
    const orig = process.env.CLOAKBROWSER_CACHE_DIR;
    const dir = `/tmp/cloakbrowser-test-${Date.now()}-promarker`;
    process.env.CLOAKBROWSER_CACHE_DIR = dir;
    try {
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(
        path.join(dir, `latest_pro_version_${getPlatformTag()}`),
        "148.0.7778.215.5"
      );
      // Marker present, but no binary on disk → null.
      expect(getEffectiveVersion()).toBeNull();
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
    const binaryPath = getBinaryPath(version);
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

  it("aborts when the server rejects the key", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ valid: false, plan: "solo", expires: null }),
    } as Response);

    await expect(ensureBinary("cb_bad")).rejects.toThrow(/invalid or expired/);
  });

  it("aborts when the key cannot be validated (server down, no cache)", async () => {
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

describe("concurrent first-run download", () => {
  const CALLERS = 4;
  const FILLER_FILES = 300;
  const PARTIAL_INSTALL_FILES = 2000;
  const VERSION = "155.0.8059.39.2";
  const binaryBytes = Buffer.from("#!/bin/sh\necho fake-chrome\n");
  // A throwaway signing key, pinned for these tests: the keyed download path
  // always verifies the signed manifest (nothing can skip it).
  const { publicKey, privateKey } = generateKeyPairSync("ed25519");
  const testPubB64 = Buffer.from(publicKey.export({ format: "jwk" }).x!, "base64url").toString("base64");
  let cacheDir: string;
  let archiveBytes: Buffer;
  let manifest: Buffer;
  let manifestSig: Buffer;
  let originalCacheDir: string | undefined;

  beforeEach(async () => {
    const { create: tarCreate } = await import("tar");
    originalCacheDir = process.env.CLOAKBROWSER_CACHE_DIR;
    cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), "cloakbrowser-concurrent-"));
    process.env.CLOAKBROWSER_CACHE_DIR = cacheDir;
    delete process.env.CLOAKBROWSER_BINARY_PATH;
    delete process.env.CLOAKBROWSER_VERSION;
    BINARY_SIGNING_PUBKEYS.push(testPubB64);

    // A small archive with the platform's binary layout plus enough filler
    // files that concurrent extractions overlap in time.
    const staging = fs.mkdtempSync(path.join(os.tmpdir(), "cloakbrowser-archive-"));
    const binaryRelPath = path.relative(getBinaryDir(VERSION), getBinaryPath(VERSION));
    fs.mkdirSync(path.join(staging, path.dirname(binaryRelPath)), { recursive: true });
    fs.writeFileSync(path.join(staging, binaryRelPath), binaryBytes, { mode: 0o755 });
    fs.mkdirSync(path.join(staging, "lib"));
    for (let i = 0; i < FILLER_FILES; i++) {
      fs.writeFileSync(path.join(staging, "lib", `part-${i}.bin`), Buffer.alloc(16 * 1024, i));
    }
    const archivePath = path.join(staging, "..", `${path.basename(staging)}.tar.gz`);
    await tarCreate({ gzip: true, file: archivePath, cwd: staging }, fs.readdirSync(staging));
    archiveBytes = fs.readFileSync(archivePath);
    fs.rmSync(staging, { recursive: true, force: true });
    fs.rmSync(archivePath, { force: true });
    const hash = createHash("sha256").update(archiveBytes).digest("hex");
    manifest = Buffer.from(`version=${VERSION}\n${hash}  ${getArchiveName()}\n`);
    manifestSig = Buffer.from(cryptoSign(null, manifest, privateKey).toString("base64"));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    BINARY_SIGNING_PUBKEYS.splice(BINARY_SIGNING_PUBKEYS.indexOf(testPubB64), 1);
    fs.rmSync(cacheDir, { recursive: true, force: true });
    if (originalCacheDir === undefined) delete process.env.CLOAKBROWSER_CACHE_DIR;
    else process.env.CLOAKBROWSER_CACHE_DIR = originalCacheDir;
  });

  /** The server, by path: license check, latest version, signed manifest, archive. */
  async function serve(pathname: string, downloadHold?: () => Promise<void>): Promise<Response> {
    if (pathname.endsWith("/api/license/validate")) {
      return Response.json({ valid: true, plan: "business", expires: null });
    }
    if (pathname.endsWith("/api/download/version")) return Response.json({ version: VERSION });
    if (pathname.endsWith("/SHA256SUMS")) return new Response(manifest);
    if (pathname.endsWith("/SHA256SUMS.sig")) return new Response(manifestSig);
    if (pathname.endsWith(`/api/download/${VERSION}`)) {
      await downloadHold?.();
      return new Response(archiveBytes);
    }
    return new Response("not found", { status: 404 }); // e.g. the npm update check
  }

  const urlPath = (input: unknown) =>
    new URL(input instanceof Request ? input.url : String(input)).pathname;

  // Reads the install the way a launch would. Returns what is wrong with it, or "complete".
  function inspectInstall(): string {
    try {
      const binaryPath = getBinaryPath(VERSION);
      if (!fs.readFileSync(binaryPath).equals(binaryBytes)) return "binary content differs";
      if ((fs.statSync(binaryPath).mode & 0o111) === 0) return "binary not executable";
      const fillerCount = fs.readdirSync(path.join(getBinaryDir(VERSION), "lib")).length;
      return fillerCount === FILLER_FILES ? "complete" : `lib has ${fillerCount} files`;
    } catch (err) {
      return (err as NodeJS.ErrnoException).code ?? String(err);
    }
  }

  const cacheEntries = () =>
    fs.readdirSync(cacheDir).filter((name) => !name.startsWith(".")).sort();
  const expectedEntries = () =>
    [path.basename(getBinaryDir(VERSION)), `latest_pro_version_${getPlatformTag()}`].sort();

  it.skipIf(process.platform === "win32")(
    "an install stays complete while other first-run callers finish",
    async () => {
      // Caller 0 downloads at once. The others have already seen an empty
      // cache but their downloads are held until caller 0 has returned, which
      // is the state a batch of simultaneous cold launches ends up in.
      let releaseHeldDownloads!: () => void;
      const heldDownloads = new Promise<void>((resolve) => (releaseHeldDownloads = resolve));
      let downloadCount = 0;
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) =>
        serve(urlPath(input), async () => {
          if (downloadCount++ > 0) await heldDownloads;
        }),
      );
      vi.spyOn(console, "log").mockImplementation(() => {});
      vi.spyOn(console, "error").mockImplementation(() => {});

      const callers = Array.from({ length: CALLERS }, () => ensureBinary("cb_test"));
      const firstBinaryPath = await callers[0];
      expect(firstBinaryPath).toBe(getBinaryPath(VERSION));

      // Caller 0 would now exec its binary. Keep reading the install while
      // the held callers download and extract.
      releaseHeldDownloads();
      const observedStates = new Set<string>([inspectInstall()]);
      const otherCallers = Promise.allSettled(callers.slice(1));
      let otherCallersDone = false;
      otherCallers.then(() => (otherCallersDone = true));
      while (!otherCallersDone) {
        observedStates.add(inspectInstall());
        await new Promise((resolve) => setImmediate(resolve));
      }
      observedStates.add(inspectInstall());

      for (const outcome of await otherCallers) {
        expect(outcome).toEqual({ status: "fulfilled", value: getBinaryPath(VERSION) });
      }
      expect([...observedStates]).toEqual(["complete"]);
      expect(cacheEntries()).toEqual(expectedEntries());
    },
  );

  it.skipIf(process.platform === "win32")(
    "replaces a partial install left by an interrupted extraction",
    async () => {
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => serve(urlPath(input)));
      vi.spyOn(console, "error").mockImplementation(() => {});
      fs.mkdirSync(path.join(getBinaryDir(VERSION), "lib"), { recursive: true });
      fs.writeFileSync(path.join(getBinaryDir(VERSION), "lib", "part-0.bin"), "truncated");

      expect(await ensureBinary("cb_test")).toBe(getBinaryPath(VERSION));
      expect(inspectInstall()).toBe("complete");
    },
  );

  // MCP stdio servers use stdout as their JSON-RPC channel; status lines there break them.
  it.skipIf(process.platform === "win32")(
    "first-run download writes nothing to stdout",
    async () => {
      vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => serve(urlPath(input)));
      vi.spyOn(console, "error").mockImplementation(() => {});
      const consoleLog = vi.spyOn(console, "log").mockImplementation(() => {});
      const stdoutWrite = vi.spyOn(process.stdout, "write");

      expect(await ensureBinary("cb_test")).toBe(getBinaryPath(VERSION));
      expect(inspectInstall()).toBe("complete");
      expect(consoleLog).not.toHaveBeenCalled();
      expect(stdoutWrite).not.toHaveBeenCalled();
    },
  );

  it.skipIf(process.platform === "win32")(
    "concurrent processes replace a partial install left by an interrupted extraction",
    async () => {
      // Enough files that deleting the partial install overlaps other callers.
      fs.mkdirSync(path.join(getBinaryDir(VERSION), "lib"), { recursive: true });
      for (let i = 0; i < PARTIAL_INSTALL_FILES; i++) {
        fs.writeFileSync(path.join(getBinaryDir(VERSION), "lib", `part-${i}.bin`), "truncated");
      }

      // A local stand-in for the server. The archive is answered only once every
      // caller is downloading, so all of them find the partial install in the
      // way when they move their extraction into place.
      const heldDownloads: Array<() => void> = [];
      const mirror = http.createServer(async (request, response) => {
        const reply = await serve(new URL(request.url!, "http://x").pathname, () =>
          new Promise<void>((resolve) => {
            heldDownloads.push(resolve);
            if (heldDownloads.length === CALLERS) heldDownloads.forEach((release) => release());
          }),
        );
        response.writeHead(reply.status, { "content-type": reply.headers.get("content-type") ?? "" });
        response.end(Buffer.from(await reply.arrayBuffer()));
      });
      await new Promise<void>((resolve) => mirror.listen(0, "127.0.0.1", resolve));
      const mirrorUrl = `http://127.0.0.1:${(mirror.address() as AddressInfo).port}`;

      // Callers in one process cannot interleave inside extractArchive's
      // synchronous rename and cleanup, so each caller is a separate process
      // running the built dist/ (npm run build first, as CI does). Each pins
      // the test key and sends every request to the local server.
      const distUrl = (name: string) => new URL(`../dist/${name}`, import.meta.url).href;
      const callerScript =
        `const cfg = await import(${JSON.stringify(distUrl("config.js"))});` +
        `cfg.BINARY_SIGNING_PUBKEYS.push(${JSON.stringify(testPubB64)});` +
        `const realFetch = globalThis.fetch;` +
        `globalThis.fetch = (input, init) => { const u = new URL(String(input));` +
        ` return realFetch(${JSON.stringify(mirrorUrl)} + u.pathname + u.search, init); };` +
        `const { ensureBinary } = await import(${JSON.stringify(distUrl("download.js"))});` +
        `console.log("BINARY_PATH=" + (await ensureBinary("cb_test")));`;
      try {
        const callers = await Promise.allSettled(
          Array.from({ length: CALLERS }, () =>
            promisify(execFile)(process.execPath, ["--input-type=module", "-e", callerScript], {
              env: process.env,
            }),
          ),
        );
        const outcomes = callers.map((caller) =>
          caller.status === "fulfilled"
            ? caller.value.stdout.trim().split("\n").at(-1)
            : String(caller.reason),
        );
        expect(outcomes).toEqual(Array(CALLERS).fill(`BINARY_PATH=${getBinaryPath(VERSION)}`));
      } finally {
        mirror.close();
      }
      expect(inspectInstall()).toBe("complete");
      expect(cacheEntries()).toEqual(expectedEntries());
    },
  );
});
