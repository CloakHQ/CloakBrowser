import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import { binaryInfo } from "../src/download.js";
import { DEFAULT_VIEWPORT, getChromiumVersion } from "../src/config.js";

describe("binaryInfo", () => {
  it("returns correct structure", () => {
    const info = binaryInfo();

    expect(info.version).toBe(getChromiumVersion());
    expect(info.platform).toMatch(/^(linux|darwin|windows)-(x64|arm64)$/);
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

// ---------------------------------------------------------------------------
// launchContext / launchPersistentContext unit tests (mock playwright-core)
// ---------------------------------------------------------------------------

describe("launchContext (unit)", () => {
  let mockContext: any;
  let mockBrowser: any;
  let mockChromium: any;
  const origEnv = process.env.CLOAKBROWSER_BINARY_PATH;

  beforeEach(() => {
    process.env.CLOAKBROWSER_BINARY_PATH = "/fake/chrome";
    const origClose = vi.fn();
    mockContext = { close: origClose, _origClose: origClose };
    mockBrowser = {
      newContext: vi.fn().mockResolvedValue(mockContext),
      close: vi.fn(),
    };
    mockChromium = { launch: vi.fn().mockResolvedValue(mockBrowser) };

    vi.doMock("playwright-core", () => ({ chromium: mockChromium }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
    if (origEnv) {
      process.env.CLOAKBROWSER_BINARY_PATH = origEnv;
    } else {
      delete process.env.CLOAKBROWSER_BINARY_PATH;
    }
  });

  it("applies DEFAULT_VIEWPORT when no viewport given", async () => {
    const { launchContext } = await import("../src/playwright.js");
    await launchContext();

    const ctxArgs = mockBrowser.newContext.mock.calls[0][0];
    expect(ctxArgs.viewport).toEqual(DEFAULT_VIEWPORT);
  });

  it("uses custom viewport when provided", async () => {
    const { launchContext } = await import("../src/playwright.js");
    const custom = { width: 1280, height: 720 };
    await launchContext({ viewport: custom });

    const ctxArgs = mockBrowser.newContext.mock.calls[0][0];
    expect(ctxArgs.viewport).toEqual(custom);
  });

  it("forwards userAgent to newContext", async () => {
    const { launchContext } = await import("../src/playwright.js");
    await launchContext({ userAgent: "Custom/1.0" });

    const ctxArgs = mockBrowser.newContext.mock.calls[0][0];
    expect(ctxArgs.userAgent).toBe("Custom/1.0");
  });

  it("passes timezone via binary flag, not CDP context", async () => {
    const { launchContext } = await import("../src/playwright.js");
    await launchContext({ timezone: "America/New_York" });

    // launch() called with --fingerprint-timezone binary flag
    const launchArgs = mockChromium.launch.mock.calls[0][0];
    const hasTimezoneFlag = launchArgs.args.some((a: string) =>
      a.startsWith("--fingerprint-timezone=America/New_York")
    );
    expect(hasTimezoneFlag).toBe(true);

    // NOT in newContext() — no CDP emulation
    const ctxArgs = mockBrowser.newContext.mock.calls[0][0];
    expect(ctxArgs.timezoneId).toBeUndefined();
  });

  it("forwards colorScheme to newContext", async () => {
    const { launchContext } = await import("../src/playwright.js");
    await launchContext({ colorScheme: "dark" });

    const ctxArgs = mockBrowser.newContext.mock.calls[0][0];
    expect(ctxArgs.colorScheme).toBe("dark");
  });

  it("close() also closes browser", async () => {
    const { launchContext } = await import("../src/playwright.js");
    const ctx = await launchContext();

    await ctx.close();
    // Original context close called
    expect(mockContext._origClose).toHaveBeenCalledOnce();
    // Browser also closed
    expect(mockBrowser.close).toHaveBeenCalledOnce();
  });

  it("forwards contextOptions to newContext (storageState, etc.)", async () => {
    const { launchContext } = await import("../src/playwright.js");
    await launchContext({
      contextOptions: {
        storageState: "state.json",
        permissions: ["geolocation"],
      },
    });

    const ctxArgs = mockBrowser.newContext.mock.calls[0][0];
    expect(ctxArgs.storageState).toBe("state.json");
    expect(ctxArgs.permissions).toEqual(["geolocation"]);
  });

  it("explicit top-level fields win over contextOptions on collision", async () => {
    const { launchContext } = await import("../src/playwright.js");
    await launchContext({
      userAgent: "Explicit/1.0",
      viewport: { width: 1280, height: 720 },
      colorScheme: "dark",
      contextOptions: {
        userAgent: "ShouldBeOverridden/9.9",
        viewport: { width: 9999, height: 9999 },
        colorScheme: "light",
      },
    });

    const ctxArgs = mockBrowser.newContext.mock.calls[0][0];
    expect(ctxArgs.userAgent).toBe("Explicit/1.0");
    expect(ctxArgs.viewport).toEqual({ width: 1280, height: 720 });
    expect(ctxArgs.colorScheme).toBe("dark");
  });

  it("strips locale and timezoneId from contextOptions (stealth-sensitive)", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { launchContext } = await import("../src/playwright.js");
    await launchContext({
      contextOptions: {
        storageState: "state.json",
        locale: "de-DE",
        timezoneId: "Europe/Berlin",
      },
    });

    const ctxArgs = mockBrowser.newContext.mock.calls[0][0];
    // Stealth-sensitive keys stripped — they would reintroduce detectable CDP emulation.
    expect(ctxArgs.locale).toBeUndefined();
    expect(ctxArgs.timezoneId).toBeUndefined();
    // Benign keys preserved
    expect(ctxArgs.storageState).toBe("state.json");
    // Warning was logged for both stripped keys
    expect(warnSpy).toHaveBeenCalledTimes(2);
  });
});

describe("launchPersistentContext (unit)", () => {
  let mockContext: any;
  let mockChromium: any;
  const origEnv = process.env.CLOAKBROWSER_BINARY_PATH;

  beforeEach(() => {
    process.env.CLOAKBROWSER_BINARY_PATH = "/fake/chrome";
    mockContext = { close: vi.fn(), pages: vi.fn().mockReturnValue([]) };
    mockChromium = {
      launchPersistentContext: vi.fn().mockResolvedValue(mockContext),
    };

    vi.doMock("playwright-core", () => ({ chromium: mockChromium }));
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
    if (origEnv) {
      process.env.CLOAKBROWSER_BINARY_PATH = origEnv;
    } else {
      delete process.env.CLOAKBROWSER_BINARY_PATH;
    }
  });

  it("applies DEFAULT_VIEWPORT", async () => {
    const { launchPersistentContext } = await import("../src/playwright.js");
    await launchPersistentContext({ userDataDir: "/tmp/profile" });

    const args = mockChromium.launchPersistentContext.mock.calls[0][1];
    expect(args.viewport).toEqual(DEFAULT_VIEWPORT);
  });

  it("passes timezone and locale via binary args, not CDP context", async () => {
    const { launchPersistentContext } = await import("../src/playwright.js");
    await launchPersistentContext({
      userDataDir: "/tmp/profile",
      timezone: "Asia/Tokyo",
      locale: "ja-JP",
    });

    const args = mockChromium.launchPersistentContext.mock.calls[0][1];
    // Binary args (native, undetectable)
    expect(args.args).toContain("--fingerprint-timezone=Asia/Tokyo");
    expect(args.args).toContain("--lang=ja-JP");
    // NOT in context kwargs (would trigger detectable CDP emulation)
    expect(args.timezoneId).toBeUndefined();
    expect(args.locale).toBeUndefined();
  });

  it("forwards proxy string", async () => {
    const { launchPersistentContext } = await import("../src/playwright.js");
    await launchPersistentContext({
      userDataDir: "/tmp/profile",
      proxy: "http://user:pass@proxy:8080",
    });

    const args = mockChromium.launchPersistentContext.mock.calls[0][1];
    expect(args.proxy.server).toBe("http://proxy:8080");
    expect(args.proxy.username).toBe("user");
    expect(args.proxy.password).toBe("pass");
  });

  it("forwards userAgent and colorScheme", async () => {
    const { launchPersistentContext } = await import("../src/playwright.js");
    await launchPersistentContext({
      userDataDir: "/tmp/profile",
      userAgent: "Custom/1.0",
      colorScheme: "dark",
    });

    const args = mockChromium.launchPersistentContext.mock.calls[0][1];
    expect(args.userAgent).toBe("Custom/1.0");
    expect(args.colorScheme).toBe("dark");
  });

  it("forwards contextOptions to launchPersistentContext", async () => {
    const { launchPersistentContext } = await import("../src/playwright.js");
    await launchPersistentContext({
      userDataDir: "/tmp/profile",
      contextOptions: {
        permissions: ["geolocation"],
        extraHTTPHeaders: { "X-Custom": "1" },
      },
    });

    const args = mockChromium.launchPersistentContext.mock.calls[0][1];
    expect(args.permissions).toEqual(["geolocation"]);
    expect(args.extraHTTPHeaders).toEqual({ "X-Custom": "1" });
  });

  it("explicit top-level fields win over contextOptions in persistent context", async () => {
    const { launchPersistentContext } = await import("../src/playwright.js");
    await launchPersistentContext({
      userDataDir: "/tmp/profile",
      userAgent: "Explicit/1.0",
      viewport: { width: 1280, height: 720 },
      contextOptions: {
        userAgent: "ShouldBeOverridden/9.9",
        viewport: { width: 9999, height: 9999 },
      },
    });

    const args = mockChromium.launchPersistentContext.mock.calls[0][1];
    expect(args.userAgent).toBe("Explicit/1.0");
    expect(args.viewport).toEqual({ width: 1280, height: 720 });
  });

  it("strips locale and timezoneId from contextOptions (persistent context)", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { launchPersistentContext } = await import("../src/playwright.js");
    await launchPersistentContext({
      userDataDir: "/tmp/profile",
      contextOptions: {
        locale: "de-DE",
        timezoneId: "Europe/Berlin",
      },
    });

    const args = mockChromium.launchPersistentContext.mock.calls[0][1];
    expect(args.locale).toBeUndefined();
    expect(args.timezoneId).toBeUndefined();
    expect(warnSpy).toHaveBeenCalledTimes(2);
  });
});
