import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { showWelcome } from "../src/download.js";

// The welcome banner runs on the binary-download path. On a legacy Windows
// console a non-ASCII glyph can crash or mojibake the write (ticket 2354), so
// the banner must be pure ASCII. Mirrors the Python test_welcome_banner suite.
describe("welcome banner", () => {
  let cacheDir: string;
  let prevCache: string | undefined;
  let errSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), "cb-welcome-"));
    prevCache = process.env.CLOAKBROWSER_CACHE_DIR;
    process.env.CLOAKBROWSER_CACHE_DIR = cacheDir;
    errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  });

  afterEach(() => {
    errSpy.mockRestore();
    if (prevCache === undefined) delete process.env.CLOAKBROWSER_CACHE_DIR;
    else process.env.CLOAKBROWSER_CACHE_DIR = prevCache;
    fs.rmSync(cacheDir, { recursive: true, force: true });
  });

  for (const tier of ["keyless", "free", "pro"]) {
    it(`${tier} banner is ASCII-only`, () => {
      showWelcome(tier);
      const out = errSpy.mock.calls.map((c) => String(c[0] ?? "")).join("\n");
      expect(out).not.toBe("");
      // eslint-disable-next-line no-control-regex
      expect(out).toMatch(/^[\x00-\x7F]*$/);
    });
  }
});
