import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import os from "node:os";
import fs from "node:fs";
import path from "node:path";

// The Linux Windows-font mismatch warning. fonts.ts holds a once-per-process
// flag, so each test re-imports the module fresh via vi.resetModules(). fc-match
// is mocked (named export from a CJS builtin can't be spied, so vi.mock it),
// and the cache dir is steered with CLOAKBROWSER_CACHE_DIR (read by getCacheDir)
// so no config spy is needed across the module reset.

vi.mock("node:child_process", () => ({ execFileSync: vi.fn() }));

const WIN_ARGS = ["--fingerprint-platform=windows", "--no-sandbox"];
const MSG = "Incomplete Windows font set";

// What fontconfig answers when it cannot match: a real family, which is exactly
// why the probe has to compare the answer against the request.
const FALLBACK_FAMILY = "Nimbus Sans";

/**
 * `fc-match --format=%{family} <family>` answers per family, so the mock has to
 * key off the requested one rather than return a single listing for everything.
 */
function fcMatch(present: Iterable<string> = []) {
  const set = new Set(present);
  return (_cmd: string, args: string[]) =>
    (set.has(args[1]) ? args[1] : FALLBACK_FAMILY) as never;
}

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
  const mod = await import("../src/fonts.js");
  return {
    maybeWarn: mod.maybeWarnWindowsFonts,
    tells: mod.WINDOWS_FONT_TELLS,
    countFontsPresent: mod.countFontsPresent,
    fontFamilyResolves: mod.fontFamilyResolves,
    execFileSync: vi.mocked(cp.execFileSync),
  };
}

function marker() {
  return path.join(cacheDir, ".font_warning_shown");
}

describe("maybeWarnWindowsFonts", () => {
  it("warns and writes a marker when no Windows fonts on Linux", async () => {
    vi.spyOn(os, "platform").mockReturnValue("linux");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { maybeWarn, execFileSync } = await load();
    execFileSync.mockImplementation(fcMatch());
    maybeWarn(WIN_ARGS);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain(MSG);
    expect(fs.existsSync(marker())).toBe(true);
  });

  it("probes fc-match only once per process", async () => {
    vi.spyOn(os, "platform").mockReturnValue("linux");
    vi.spyOn(console, "warn").mockImplementation(() => {});
    const { maybeWarn, tells, execFileSync } = await load();
    execFileSync.mockImplementation(fcMatch());
    maybeWarn(WIN_ARGS);
    const afterFirst = execFileSync.mock.calls.length;
    maybeWarn(WIN_ARGS);
    // One fc-match per family, so count the probe rather than the invocations:
    // the second call must add none.
    expect(afterFirst).toBe(tells.length);
    expect(execFileSync).toHaveBeenCalledTimes(afterFirst);
  });

  it("an existing marker suppresses the warning", async () => {
    fs.writeFileSync(marker(), "");
    vi.spyOn(os, "platform").mockReturnValue("linux");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { maybeWarn, execFileSync } = await load();
    execFileSync.mockImplementation(fcMatch());
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

  it("does not warn or crash when fc-match is absent", async () => {
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
    const { maybeWarn, tells, execFileSync } = await load();
    execFileSync.mockImplementation(fcMatch(tells));
    maybeWarn(WIN_ARGS);
    expect(warn).not.toHaveBeenCalled();
  });

  it("warns on a partial Windows set (strict — all 8 required)", async () => {
    vi.spyOn(os, "platform").mockReturnValue("linux");
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { maybeWarn, execFileSync } = await load();
    // Only 1 of the 8 tells resolves.
    execFileSync.mockImplementation(fcMatch(["Segoe UI"]));
    maybeWarn(WIN_ARGS);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toContain(MSG);
  });
});

// The probe verifies *resolution* (fc-match), not presence in an fc-list dump.
// The old substring check over-counted two ways and reported a complete font set
// on an image where one family did not resolve at all — an `ok (8/8)` that hid a
// real gap.
describe("fontFamilyResolves / countFontsPresent", () => {
  it("counts an exact family match, ignoring case and whitespace", async () => {
    const { fontFamilyResolves, execFileSync } = await load();
    execFileSync.mockReturnValue("  consolas  " as never);
    expect(fontFamilyResolves("Consolas")).toBe(true);
  });

  it("accepts a comma-separated alias list", async () => {
    const { fontFamilyResolves, execFileSync } = await load();
    execFileSync.mockReturnValue("Segoe UI,Segoe UI Light" as never);
    expect(fontFamilyResolves("Segoe UI Light")).toBe(true);
  });

  it("does not count a fallback font", async () => {
    // fc-match always answers something — the default when it cannot match.
    // Asking for Franklin Gothic on an image that lacks it returns NimbusSans,
    // and the family is undetectable by any font-fingerprinting script.
    const { fontFamilyResolves, execFileSync } = await load();
    execFileSync.mockReturnValue(FALLBACK_FAMILY as never);
    expect(fontFamilyResolves("Franklin Gothic")).toBe(false);
  });

  it("does not let a longer family satisfy a shorter request", async () => {
    // "Segoe UI" must not be satisfied by "Segoe UI Emoji" — a different family
    // with different metrics, commonly present on its own. The old substring
    // check scored it as a hit.
    const { fontFamilyResolves, execFileSync } = await load();
    execFileSync.mockReturnValue("Segoe UI Emoji" as never);
    expect(fontFamilyResolves("Segoe UI")).toBe(false);
  });

  it("reports unknown, not absent, when fc-match is missing", async () => {
    const { fontFamilyResolves, countFontsPresent, tells, execFileSync } = await load();
    execFileSync.mockImplementation(() => {
      throw new Error("ENOENT");
    });
    expect(fontFamilyResolves("Consolas")).toBeNull();
    expect(countFontsPresent(tells)).toBeNull();
  });

  it("counts the whole set when every family resolves", async () => {
    const { countFontsPresent, tells, execFileSync } = await load();
    execFileSync.mockImplementation(fcMatch(tells));
    expect(countFontsPresent(tells)).toBe(tells.length);
  });

  it("reports a partial set rather than a false complete", async () => {
    // The reported case: one family of eight fails to resolve. The old check
    // said ok (8/8); the fix must say 7/8.
    const { countFontsPresent, tells, execFileSync } = await load();
    const present = tells.filter((f) => f !== "Franklin Gothic");
    execFileSync.mockImplementation(fcMatch(present));
    expect(countFontsPresent(tells)).toBe(tells.length - 1);
  });

  it("returns a real zero when fc-match works but nothing matches", async () => {
    const { countFontsPresent, tells, execFileSync } = await load();
    execFileSync.mockImplementation(fcMatch());
    expect(countFontsPresent(tells)).toBe(0);
  });
});
