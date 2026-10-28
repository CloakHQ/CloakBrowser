import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { execFile } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";

import { PROFILE_SEED_FILE, persistentSeedArgs } from "../src/profile-seed.js";

// macOS adds ._ AppleDouble files on FAT volumes, where these tests also run.
const listing = (d: string) => fs.readdirSync(d).filter((n) => !n.startsWith("._"));
const seedOf = (args: string[]) => args.filter((a) => a.startsWith("--fingerprint="));

let dir: string;
beforeEach(() => {
  dir = fs.mkdtempSync(path.join(os.tmpdir(), "cb-seed-"));
});
afterEach(() => {
  fs.rmSync(dir, { recursive: true, force: true });
  vi.restoreAllMocks();
});

describe("persistentSeedArgs", () => {
  it("writes the seed on first call and reuses it", () => {
    const profile = path.join(dir, "missing", "profile"); // created on demand
    const first = persistentSeedArgs(profile, undefined, ["--x"])!;
    const stored = fs.readFileSync(path.join(profile, PROFILE_SEED_FILE), "utf8");
    expect(stored).toMatch(/^\d{5}\n$/);
    expect(first).toEqual([`--fingerprint=${stored.trim()}`, "--x"]);
    expect(persistentSeedArgs(profile, true, ["--x"])).toEqual(first);
  });

  it("reads a Python-written seed file", () => {
    fs.writeFileSync(path.join(dir, PROFILE_SEED_FILE), "12345\n"); // exact Python output
    expect(persistentSeedArgs(dir, true, undefined)).toEqual(["--fingerprint=12345"]);
  });

  it.each(["--fingerprint=4242", "--fingerprint=off"])("explicit %s wins, file untouched", (flag) => {
    expect(persistentSeedArgs(dir, true, [flag])).toEqual([flag]);
    expect(fs.existsSync(path.join(dir, PROFILE_SEED_FILE))).toBe(false);
    fs.writeFileSync(path.join(dir, PROFILE_SEED_FILE), "12345\n");
    expect(persistentSeedArgs(dir, true, [flag])).toEqual([flag]);
    expect(fs.readFileSync(path.join(dir, PROFILE_SEED_FILE), "utf8")).toBe("12345\n");
  });

  it("stealthArgs false writes nothing", () => {
    expect(persistentSeedArgs(dir, false, ["--x"])).toEqual(["--x"]);
    expect(fs.readdirSync(dir)).toEqual([]);
  });

  it("empty userDataDir is ignored", () => {
    expect(persistentSeedArgs("", true, ["--x"])).toEqual(["--x"]);
  });

  it.each(["", "abc\n", "5\n", "123456\n", "-12345\n"])("corrupt %j logs and regenerates", (content) => {
    const file = path.join(dir, PROFILE_SEED_FILE);
    fs.writeFileSync(file, content);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const args = persistentSeedArgs(dir, true, undefined)!;
    expect(warn.mock.calls[0][0]).toContain(file);
    const stored = fs.readFileSync(file, "utf8");
    expect(stored).toMatch(/^\d{5}\n$/);
    expect(args).toEqual([`--fingerprint=${stored.trim()}`]);
  });

  it("falls back to exclusive create when hard links are unsupported", () => {
    // FAT/exFAT and some network mounts reject link() with ENOTSUP/EPERM.
    const link = vi.spyOn(fs, "linkSync").mockImplementation(() => {
      throw Object.assign(new Error("operation not supported"), { code: "ENOTSUP" });
    });
    const first = persistentSeedArgs(dir, true, undefined)!;
    expect(persistentSeedArgs(dir, true, undefined)).toEqual(first);
    const stored = fs.readFileSync(path.join(dir, PROFILE_SEED_FILE), "utf8");
    expect(first).toEqual([`--fingerprint=${stored.trim()}`]);
    expect(listing(dir)).toEqual([PROFILE_SEED_FILE]);
    expect(link).toHaveBeenCalledTimes(1); // the mock really intercepted the publish
  });

  it("concurrent first launches in separate processes agree", async () => {
    // Runs the built dist/ (npm run build first, as CI does).
    const moduleUrl = new URL("../dist/profile-seed.js", import.meta.url).href;
    const script =
      `const { persistentSeedArgs } = await import(${JSON.stringify(moduleUrl)});` +
      `console.log(persistentSeedArgs(${JSON.stringify(dir)}, true, [])[0]);`;
    const outs = await Promise.all(
      Array.from({ length: 8 }, () =>
        promisify(execFile)(process.execPath, ["--input-type=module", "-e", script]),
      ),
    );
    const seeds = new Set(outs.map((o) => o.stdout.trim()));
    expect(seeds.size).toBe(1);
    expect(listing(dir)).toEqual([PROFILE_SEED_FILE]);
  });
});

describe("launchers use the stored seed", () => {
  const origEnv = process.env.CLOAKBROWSER_BINARY_PATH;
  beforeEach(() => {
    process.env.CLOAKBROWSER_BINARY_PATH = "/fake/chrome";
  });
  afterEach(() => {
    vi.resetModules();
    if (origEnv) process.env.CLOAKBROWSER_BINARY_PATH = origEnv;
    else delete process.env.CLOAKBROWSER_BINARY_PATH;
  });

  it("playwright launchPersistentContext reuses the seed, launch() stays random", async () => {
    const chromium = {
      launchPersistentContext: vi.fn().mockResolvedValue({ close: vi.fn(), pages: () => [] }),
      launch: vi.fn().mockResolvedValue({ close: vi.fn(), on: vi.fn(), contexts: () => [] }),
    };
    vi.doMock("playwright-core", () => ({ chromium }));
    const { launchPersistentContext, launch } = await import("../src/playwright.js");

    await launchPersistentContext({ userDataDir: dir });
    await launchPersistentContext({ userDataDir: dir });
    const [a, b] = chromium.launchPersistentContext.mock.calls.map((c: any) => seedOf(c[1].args));
    const stored = fs.readFileSync(path.join(dir, PROFILE_SEED_FILE), "utf8").trim();
    expect(a).toEqual([`--fingerprint=${stored}`]);
    expect(b).toEqual(a);

    for (let i = 0; i < 5; i++) await launch();
    const plain = new Set(chromium.launch.mock.calls.map((c: any) => seedOf(c[0].args)[0]));
    expect(plain.size).toBeGreaterThan(1);
  });

  it("puppeteer launchPersistentContext uses the stored seed", async () => {
    const launch = vi.fn().mockResolvedValue({ pages: vi.fn().mockResolvedValue([]), close: vi.fn(), on: vi.fn() });
    vi.doMock("puppeteer-core", () => ({ default: { launch } }));
    fs.writeFileSync(path.join(dir, PROFILE_SEED_FILE), "12345\n");
    const { launchPersistentContext } = await import("../src/puppeteer.js");

    await launchPersistentContext({ userDataDir: dir });
    expect(seedOf(launch.mock.calls[0][0].args)).toEqual(["--fingerprint=12345"]);
  });

  it("puppeteer launch() shares resolveArgs but stays random and writes nothing", async () => {
    const launch = vi.fn().mockResolvedValue({ pages: vi.fn().mockResolvedValue([]), close: vi.fn(), on: vi.fn() });
    vi.doMock("puppeteer-core", () => ({ default: { launch } }));
    const cwd = process.cwd();
    process.chdir(dir); // a stray relative seed file would land here
    try {
      const pptr = await import("../src/puppeteer.js");
      for (let i = 0; i < 5; i++) await pptr.launch();
    } finally {
      process.chdir(cwd);
    }
    const seeds = new Set(launch.mock.calls.map((c: any) => seedOf(c[0].args)[0]));
    expect(seeds.size).toBeGreaterThan(1);
    expect(listing(dir)).toEqual([]);
  });

  it("playwright launchContext stays random and writes nothing", async () => {
    const context = { close: vi.fn(), pages: () => [], on: vi.fn() };
    const chromium = {
      launch: vi.fn().mockResolvedValue({ close: vi.fn(), on: vi.fn(), contexts: () => [], newContext: vi.fn().mockResolvedValue(context) }),
    };
    vi.doMock("playwright-core", () => ({ chromium }));
    const cwd = process.cwd();
    process.chdir(dir);
    try {
      const { launchContext } = await import("../src/playwright.js");
      for (let i = 0; i < 5; i++) await launchContext();
    } finally {
      process.chdir(cwd);
    }
    const seeds = new Set(chromium.launch.mock.calls.map((c: any) => seedOf(c[0].args)[0]));
    expect(seeds.size).toBeGreaterThan(1);
    expect(listing(dir)).toEqual([]);
  });
});
