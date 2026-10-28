import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import os from "node:os";
import fs from "node:fs";
import path from "node:path";

// The Linux Windows-font mismatch warning. fonts.ts holds a once-per-process
// flag, so each test re-imports the module fresh via vi.resetModules(). fc-list
// is mocked (named export from a CJS builtin can't be spied, so vi.mock it),
// and the cache dir is steered with CLOAKBROWSER_CACHE_DIR (read by getCacheDir)
// so no config spy is needed across the module reset.

vi.mock("node:child_process", () => ({ execFileSync: vi.fn() }));

const WIN_ARGS = ["--fingerprint-platform=windows", "--no-sandbox"];
const MSG = "Incomplete Windows font set";

// fc-list output containing all 8 Windows tell fonts (the complete set).
const ALL_WIN_FONTS =
  "Segoe UI:style=Regular\nSegoe UI Light:style=Light\nCalibri:style=Regular\n" +
  "Marlett:style=Regular\nMS UI Gothic:style=Regular\n" +
  "Franklin Gothic Medium:style=Regular\nConsolas:style=Regular\n" +
  "Courier New:style=Regular";

let cacheDir: string;

beforeEach(() => {
  vi.resetModules();
  vi.restoreAllMocks();
  cacheDir = fs.mkdtempSync(path.join(os.tmpdir(), "cb-font-"));
  process.env.CLOAKBROWSER_CACHE_DIR = cacheDir;
  delete process.env.CLOAKBROWSER_SUPPRESS_FONT_WARNING;
});

afterEach(() => {
  delete process.env.CLOAKBROWSER_CACHE_DIR;
  vi.restoreAllMocks();
});

// Re-import fonts + the (same, mocked) child_process after a module reset so the
// returned execFileSync is exactly the one fonts.ts will call.
async function load() {
  const cp = await import("node:child_process");
  const { maybeWarnWindowsFonts } = await import("../src/fonts.js");
  return { maybeWarn: maybeWarnWindowsFonts, execFileSync: vi.mocked(cp.execFileSync) };
}

function marker() {
  return path.join(cacheDir, ".font_warning_shown");
}

describe("maybeWarnWindowsFonts", () => {
  it("warns and writes a marker when no Windows fonts on Linux", async () => {
    vi.spyOn(os, "platform").mockReturnValue("linux");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { maybeWarn, execFileSync } = await load();
    execFileSync.mockReturnValue("DejaVu Sans:style=Book" as any);
    maybeWarn(WIN_ARGS);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain(MSG);
    expect(fs.existsSync(marker())).toBe(true);
  });

  it("probes fc-list only once per process", async () => {
    vi.spyOn(os, "platform").mockReturnValue("linux");
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const { maybeWarn, execFileSync } = await load();
    execFileSync.mockReturnValue("DejaVu" as any);
    maybeWarn(WIN_ARGS);
    maybeWarn(WIN_ARGS);
    expect(execFileSync).toHaveBeenCalledTimes(1);
  });

  it("an existing marker suppresses the warning", async () => {
    fs.writeFileSync(marker(), "");
    vi.spyOn(os, "platform").mockReturnValue("linux");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { maybeWarn, execFileSync } = await load();
    execFileSync.mockReturnValue("DejaVu" as any);
    maybeWarn(WIN_ARGS);
    expect(warn).not.toHaveBeenCalled();
  });

  it("env var suppresses entirely and writes no marker", async () => {
    process.env.CLOAKBROWSER_SUPPRESS_FONT_WARNING = "1";
    vi.spyOn(os, "platform").mockReturnValue("linux");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { maybeWarn } = await load();
    maybeWarn(WIN_ARGS);
    expect(warn).not.toHaveBeenCalled();
    expect(fs.existsSync(marker())).toBe(false);
  });

  it("does not warn on non-Linux", async () => {
    vi.spyOn(os, "platform").mockReturnValue("darwin");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { maybeWarn } = await load();
    maybeWarn(WIN_ARGS);
    expect(warn).not.toHaveBeenCalled();
  });

  it("does not warn when platform overridden to non-windows", async () => {
    vi.spyOn(os, "platform").mockReturnValue("linux");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { maybeWarn } = await load();
    maybeWarn(["--fingerprint-platform=linux"]);
    expect(warn).not.toHaveBeenCalled();
  });

  it("does not warn or crash when fc-list is absent", async () => {
    vi.spyOn(os, "platform").mockReturnValue("linux");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { maybeWarn, execFileSync } = await load();
    execFileSync.mockImplementation(() => {
      throw new Error("ENOENT");
    });
    expect(() => maybeWarn(WIN_ARGS)).not.toThrow();
    expect(warn).not.toHaveBeenCalled();
    expect(fs.existsSync(marker())).toBe(false);
  });

  it("does not warn when the full Windows set is present", async () => {
    vi.spyOn(os, "platform").mockReturnValue("linux");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { maybeWarn, execFileSync } = await load();
    execFileSync.mockReturnValue(ALL_WIN_FONTS as any);
    maybeWarn(WIN_ARGS);
    expect(warn).not.toHaveBeenCalled();
  });

  it("warns on a partial Windows set (strict — all 8 required)", async () => {
    vi.spyOn(os, "platform").mockReturnValue("linux");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { maybeWarn, execFileSync } = await load();
    // Only 1 of the 8 tells present.
    execFileSync.mockReturnValue("/x/segoeui.ttf: Segoe UI:style=Regular" as any);
    maybeWarn(WIN_ARGS);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain(MSG);
  });
});

describe("MACOS_FONT_TELLS", () => {
  it("holds the 20-font mac core set and counts via fc-list", async () => {
    const { MACOS_FONT_TELLS, countFontsPresent } = await import("../src/fonts.js");
    expect(MACOS_FONT_TELLS.length).toBe(20);
    expect(MACOS_FONT_TELLS).toContain("Helvetica Neue");
    const cp = await import("node:child_process");
    // fc-list listing with only 2 of the mac tells present.
    vi.mocked(cp.execFileSync).mockReturnValue(
      "/x/Menlo.ttc: Menlo:style=Regular\n/x/Monaco.ttf: Monaco:style=Regular" as any,
    );
    expect(countFontsPresent(MACOS_FONT_TELLS as string[])).toBe(2);
  });
});
