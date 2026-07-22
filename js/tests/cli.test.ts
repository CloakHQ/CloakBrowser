import { describe, it, expect, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

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
});

afterEach(() => {
  if (prevCache === undefined) delete process.env.CLOAKBROWSER_CACHE_DIR;
  else process.env.CLOAKBROWSER_CACHE_DIR = prevCache;
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
});

describe("isCliEntry", () => {
  const realCli = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../dist/cli.js");

  it("returns false when no invoked path is provided", async () => {
    const { isCliEntry } = await import("../src/cli.js");
    expect(isCliEntry(undefined, import.meta.url)).toBe(false);
  });

  it("returns false for an unrelated invoked path", async () => {
    const { isCliEntry } = await import("../src/cli.js");
    // A different source file must not be treated as the cli.js entry.
    const other = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../dist/config.js");
    expect(fs.existsSync(other)).toBe(true);
    expect(isCliEntry(other, import.meta.url)).toBe(false);
  });

  it("resolves symlinks on both sides before comparing (#427)", async () => {
    const { isCliEntry } = await import("../src/cli.js");
    // A bin shim (npm/pnpm/npx) is a symlink to the real cli.js; realpath both
    // sides so the comparison still matches.
    const linkDir = fs.mkdtempSync(path.join(os.tmpdir(), "cloak-entry-"));
    const link = path.join(linkDir, "cloakbrowser");
    fs.symlinkSync(realCli, link);
    try {
      expect(isCliEntry(link, `file://${realCli}`)).toBe(true);
    } finally {
      fs.rmSync(linkDir, { recursive: true, force: true });
    }
  });

  it("returns false for a non-existent invoked path", async () => {
    const { isCliEntry } = await import("../src/cli.js");
    expect(isCliEntry("/nonexistent/path/cli.js", import.meta.url)).toBe(false);
  });
});
