import { describe, it, expect } from "vitest";
import { binaryInfo } from "../src/download.js";
import { CHROMIUM_VERSION } from "../src/config.js";

describe("binaryInfo", () => {
  it("returns correct structure", () => {
    const info = binaryInfo();

    expect(info.version).toBe(CHROMIUM_VERSION);
    expect(info.platform).toMatch(/^(linux|darwin)-(x64|arm64)$/);
    expect(info.binaryPath).toBeTruthy();
    expect(typeof info.installed).toBe("boolean");
    expect(info.cacheDir).toContain("cloakbrowser");
    expect(info.downloadUrl).toContain(".tar.gz");
  });
});

// Integration tests require the binary — run with:
//   CLOAKBROWSER_BINARY_PATH=/path/to/chrome npm test
describe.skipIf(!process.env.CLOAKBROWSER_BINARY_PATH)(
  "launch (integration)",
  () => {
    it("launches browser and checks stealth", async () => {
      const { launch } = await import("../src/playwright.js");

      const browser = await launch({ headless: true });
      const page = await browser.newPage();
      await page.goto("about:blank");

      const webdriver = await page.evaluate(() => navigator.webdriver);
      expect(webdriver).toBeFalsy();

      const plugins = await page.evaluate(() => navigator.plugins.length);
      expect(plugins).toBeGreaterThan(0);

      await browser.close();
    }, 30_000);
  }
);
