import { describe, it, expect } from "vitest";
import {
  CHROMIUM_VERSION,
  getDownloadUrl,
  getEffectiveVersion,
  parseVersion,
  versionNewer,
} from "../src/config.js";

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
});

describe("download URL", () => {
  it("uses chromium-v prefix and cloakbrowser repo", () => {
    const url = getDownloadUrl();
    expect(url).toContain("github.com/CloakHQ/cloakbrowser/releases/download");
    expect(url).toContain(`chromium-v${CHROMIUM_VERSION}`);
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

describe("effective version", () => {
  it("returns CHROMIUM_VERSION when no marker exists", () => {
    // Default behavior — no marker file in test environment
    expect(getEffectiveVersion()).toBe(CHROMIUM_VERSION);
  });
});
