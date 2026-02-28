import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  getPlatformTag,
  getBinaryPath,
  getDefaultStealthArgs,
} from "../src/config.js";

describe("platform detection - Windows", () => {
  const originalPlatform = process.platform;
  const originalArch = process.arch;

  afterEach(() => {
    // Restore original process values
    Object.defineProperty(process, "platform", { value: originalPlatform });
    Object.defineProperty(process, "arch", { value: originalArch });
  });

  describe("getPlatformTag", () => {
    it("returns win32-x64 for Windows x64", () => {
      Object.defineProperty(process, "platform", { value: "win32" });
      Object.defineProperty(process, "arch", { value: "x64" });

      const tag = getPlatformTag();
      expect(tag).toBe("win32-x64");
    });

    it("throws for unsupported Windows architecture", () => {
      Object.defineProperty(process, "platform", { value: "win32" });
      Object.defineProperty(process, "arch", { value: "ia32" });

      expect(() => getPlatformTag()).toThrow("Unsupported platform");
    });
  });

  describe("getBinaryPath", () => {
    it("returns chrome.exe path on Windows", () => {
      Object.defineProperty(process, "platform", { value: "win32" });
      Object.defineProperty(process, "arch", { value: "x64" });

      const binaryPath = getBinaryPath();
      expect(binaryPath).toContain("chrome.exe");
    });

    it("returns chrome.exe path with version on Windows", () => {
      Object.defineProperty(process, "platform", { value: "win32" });
      Object.defineProperty(process, "arch", { value: "x64" });

      const binaryPath = getBinaryPath("142.0.7444.175");
      expect(binaryPath).toContain("chrome.exe");
      expect(binaryPath).toContain("chromium-142.0.7444.175");
    });
  });

  describe("getDefaultStealthArgs on Windows", () => {
    it("includes windows platform flag on Windows", () => {
      Object.defineProperty(process, "platform", { value: "win32" });
      Object.defineProperty(process, "arch", { value: "x64" });

      const args = getDefaultStealthArgs();

      expect(args).toContain("--fingerprint-platform=windows");
    });
  });
});
