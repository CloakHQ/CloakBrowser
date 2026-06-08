import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { resolveWidevineCdmDir, seedWidevineHint } from "../src/widevine.js";

const HINT = "WidevineCdm/latest-component-updated-widevine-cdm";
const tempDirs: string[] = [];
const origPlatform = process.platform;

function tmpDir(prefix: string): string {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  tempDirs.push(d);
  return d;
}

function makeCdm(dir: string): string {
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "manifest.json"), '{"version":"4.10.3050.0"}');
  return dir;
}

/** A fake chrome binary path inside its own dir. */
function fakeBinary(): string {
  const bdir = path.join(tmpDir("cloak-bin-"), "bin");
  fs.mkdirSync(bdir, { recursive: true });
  return path.join(bdir, "chrome");
}

function setPlatform(value: string) {
  Object.defineProperty(process, "platform", { value, configurable: true });
}

beforeEach(() => {
  setPlatform("linux"); // seeding is Linux-only; default to Linux in tests
  delete process.env.CLOAKBROWSER_WIDEVINE;
  delete process.env.CLOAKBROWSER_WIDEVINE_CDM;
});

afterEach(() => {
  vi.restoreAllMocks();
  Object.defineProperty(process, "platform", { value: origPlatform, configurable: true });
  delete process.env.CLOAKBROWSER_WIDEVINE;
  delete process.env.CLOAKBROWSER_WIDEVINE_CDM;
  for (const dir of tempDirs.splice(0)) fs.rmSync(dir, { recursive: true, force: true });
});

describe("resolveWidevineCdmDir", () => {
  it("returns env-var dir when it has manifest.json", () => {
    const cdm = makeCdm(path.join(tmpDir("cloak-wv-"), "WidevineCdm"));
    process.env.CLOAKBROWSER_WIDEVINE_CDM = cdm;
    expect(resolveWidevineCdmDir(fakeBinary())).toBe(fs.realpathSync(cdm));
  });

  it("returns null when dir lacks manifest.json", () => {
    const bogus = path.join(tmpDir("cloak-wv-"), "WidevineCdm");
    fs.mkdirSync(bogus, { recursive: true });
    process.env.CLOAKBROWSER_WIDEVINE_CDM = bogus;
    expect(resolveWidevineCdmDir(fakeBinary())).toBeNull();
  });

  it("falls back to <binary dir>/WidevineCdm", () => {
    const binary = fakeBinary();
    expect(resolveWidevineCdmDir(binary)).toBeNull(); // no CDM yet
    const cdm = makeCdm(path.join(path.dirname(binary), "WidevineCdm"));
    expect(resolveWidevineCdmDir(binary)).toBe(fs.realpathSync(cdm));
  });

  it("env var is exclusive — invalid env skips, no fallback to binary dir", () => {
    const binary = fakeBinary();
    makeCdm(path.join(path.dirname(binary), "WidevineCdm")); // valid CDM next to binary
    const bogus = path.join(tmpDir("cloak-wv-"), "bogus");
    fs.mkdirSync(bogus, { recursive: true }); // set but no manifest.json
    process.env.CLOAKBROWSER_WIDEVINE_CDM = bogus;
    expect(resolveWidevineCdmDir(binary)).toBeNull();
  });

  it("empty env var is exclusive — no fallback to binary dir", () => {
    const binary = fakeBinary();
    makeCdm(path.join(path.dirname(binary), "WidevineCdm")); // valid CDM next to binary
    process.env.CLOAKBROWSER_WIDEVINE_CDM = ""; // set but empty
    expect(resolveWidevineCdmDir(binary)).toBeNull();
  });
});

describe("seedWidevineHint", () => {
  it("writes the hint file with the absolute CDM path", () => {
    const cdm = makeCdm(path.join(tmpDir("cloak-wv-"), "WidevineCdm"));
    process.env.CLOAKBROWSER_WIDEVINE_CDM = cdm;
    const profile = tmpDir("cloak-prof-");

    seedWidevineHint(profile, fakeBinary());

    const hint = path.join(profile, HINT);
    expect(fs.existsSync(hint)).toBe(true);
    expect(JSON.parse(fs.readFileSync(hint, "utf-8")).Path).toBe(fs.realpathSync(cdm));
  });

  it("no-ops when no CDM present", () => {
    const profile = tmpDir("cloak-prof-");
    seedWidevineHint(profile, fakeBinary());
    expect(fs.existsSync(path.join(profile, HINT))).toBe(false);
  });

  it("kill switch CLOAKBROWSER_WIDEVINE=0 disables seeding", () => {
    const cdm = makeCdm(path.join(tmpDir("cloak-wv-"), "WidevineCdm"));
    process.env.CLOAKBROWSER_WIDEVINE_CDM = cdm;
    process.env.CLOAKBROWSER_WIDEVINE = "0";
    const profile = tmpDir("cloak-prof-");
    seedWidevineHint(profile, fakeBinary());
    expect(fs.existsSync(path.join(profile, HINT))).toBe(false);
  });

  it("is idempotent", () => {
    const cdm = makeCdm(path.join(tmpDir("cloak-wv-"), "WidevineCdm"));
    process.env.CLOAKBROWSER_WIDEVINE_CDM = cdm;
    const profile = tmpDir("cloak-prof-");
    seedWidevineHint(profile, fakeBinary());
    seedWidevineHint(profile, fakeBinary());
    expect(JSON.parse(fs.readFileSync(path.join(profile, HINT), "utf-8")).Path).toBe(
      fs.realpathSync(cdm),
    );
  });

  it("no-ops on non-Linux", () => {
    setPlatform("win32");
    const cdm = makeCdm(path.join(tmpDir("cloak-wv-"), "WidevineCdm"));
    process.env.CLOAKBROWSER_WIDEVINE_CDM = cdm;
    const profile = tmpDir("cloak-prof-");
    seedWidevineHint(profile, fakeBinary());
    expect(fs.existsSync(path.join(profile, HINT))).toBe(false);
  });

  it("skips empty userDataDir (no CWD pollution)", () => {
    const cdm = makeCdm(path.join(tmpDir("cloak-wv-"), "WidevineCdm"));
    process.env.CLOAKBROWSER_WIDEVINE_CDM = cdm;
    seedWidevineHint("", fakeBinary());
    expect(fs.existsSync(path.join(process.cwd(), "WidevineCdm"))).toBe(false);
  });

  it("never throws on write failure", () => {
    const cdm = makeCdm(path.join(tmpDir("cloak-wv-"), "WidevineCdm"));
    process.env.CLOAKBROWSER_WIDEVINE_CDM = cdm;
    const profile = tmpDir("cloak-prof-");
    // Block mkdir of <profile>/WidevineCdm by occupying that path with a file.
    fs.writeFileSync(path.join(profile, "WidevineCdm"), "not a dir");
    expect(() => seedWidevineHint(profile, fakeBinary())).not.toThrow();
  });

  it("rewrites a mismatched existing hint", () => {
    const cdm = makeCdm(path.join(tmpDir("cloak-wv-"), "WidevineCdm"));
    process.env.CLOAKBROWSER_WIDEVINE_CDM = cdm;
    const profile = tmpDir("cloak-prof-");
    const hint = path.join(profile, HINT);
    fs.mkdirSync(path.dirname(hint), { recursive: true });
    fs.writeFileSync(hint, '{"Path":"/stale/path"}');
    seedWidevineHint(profile, fakeBinary());
    expect(JSON.parse(fs.readFileSync(hint, "utf-8")).Path).toBe(fs.realpathSync(cdm));
  });
});
