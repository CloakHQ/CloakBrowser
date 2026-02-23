import { describe, it, expect } from "vitest";
import {
  CHROMIUM_VERSION,
  getDefaultStealthArgs,
  getCacheDir,
  getBinaryDir,
  getDownloadUrl,
} from "../src/config.js";

describe("config", () => {
  it("CHROMIUM_VERSION matches expected format", () => {
    expect(CHROMIUM_VERSION).toMatch(/^\d+\.\d+\.\d+\.\d+$/);
  });

  it("getDefaultStealthArgs returns expected flags", () => {
    const args = getDefaultStealthArgs();

    expect(args).toContain("--no-sandbox");
    expect(args).toContain("--disable-blink-features=AutomationControlled");
    expect(args).toContain("--fingerprint-platform=windows");
    expect(args).toContain("--fingerprint-hardware-concurrency=8");

    // Should have a random fingerprint seed
    const fingerprintArg = args.find((a) => a.startsWith("--fingerprint="));
    expect(fingerprintArg).toBeDefined();
    const seed = Number(fingerprintArg!.split("=")[1]);
    expect(seed).toBeGreaterThanOrEqual(10000);
    expect(seed).toBeLessThanOrEqual(99999);
  });

  it("getDefaultStealthArgs generates different seeds", () => {
    const seeds = new Set<string>();
    for (let i = 0; i < 10; i++) {
      const args = getDefaultStealthArgs();
      const fp = args.find((a) => a.startsWith("--fingerprint="))!;
      seeds.add(fp);
    }
    // With 90k possible seeds, 10 calls should produce at least 2 unique
    expect(seeds.size).toBeGreaterThan(1);
  });

  it("getCacheDir returns ~/.cloakbrowser by default", () => {
    const dir = getCacheDir();
    expect(dir).toContain(".cloakbrowser");
  });

  it("getBinaryDir includes version", () => {
    const dir = getBinaryDir();
    expect(dir).toContain(`chromium-${CHROMIUM_VERSION}`);
  });

  it("getDownloadUrl contains version and platform tag", () => {
    const url = getDownloadUrl();
    expect(url).toContain(CHROMIUM_VERSION);
    expect(url).toContain("cloakbrowser-");
    expect(url).toContain(".tar.gz");
    expect(url).toContain("github.com/CloakHQ/");
  });
});
