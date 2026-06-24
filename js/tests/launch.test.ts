import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { binaryInfo } from "../src/download.js";
import { DEFAULT_VIEWPORT, getBinaryPath, getChromiumVersion, getPlatformTag } from "../src/config.js";
import * as config from "../src/config.js";

describe("binaryInfo", () => {
  it("returns correct structure", () => {
    const orig = process.env.CLOAKBROWSER_CACHE_DIR;
    process.env.CLOAKBROWSER_CACHE_DIR = `/tmp/cloakbrowser-test-${Date.now()}`;
    try {
      const info = binaryInfo();

      expect(info.version).toBe(getChromiumVersion());
      expect(info.bundledVersion).toBeTruthy();
      expect(info.platform).toMatch(/^(linux|darwin|windows)-(x64|arm64)$/);
      expect(info.binaryPath).toBeTruthy();
      expect(typeof info.installed).toBe("boolean");
      expect(info.cacheDir).toContain("cloakbrowser");
    } finally {
      if (orig) process.env.CLOAKBROWSER_CACHE_DIR = orig;
      else delete process.env.CLOAKBROWSER_CACHE_DIR;
    }
  });

  it("reports tier from the installed binary, not a cached license", () => {
    // A valid, fresh license is cached but NO Pro binary is on disk → free.
    const orig = process.env.CLOAKBROWSER_CACHE_DIR;
    const dir = `/tmp/cloakbrowser-test-${Date.now()}-tier`;
    fs.mkdirSync(dir, { recursive: true });
    process.env.CLOAKBROWSER_CACHE_DIR = dir;
    try {
      fs.writeFileSync(
        path.join(dir, ".license_cache"),
        JSON.stringify({
          key_sha256: "abc",
          valid: true,
          plan: "solo",
          expires: null,
          validated_at: Date.now() / 1000,
        })
      );
      expect(binaryInfo().tier).toBe("free");

      // Now drop a Pro binary on disk → pro.
      fs.writeFileSync(path.join(dir, `latest_pro_version_${getPlatformTag()}`), "147.0.5555.1");
      const bp = getBinaryPath("147.0.5555.1", true);
      fs.mkdirSync(path.dirname(bp), { recursive: true });
      fs.writeFileSync(bp, "fake");
      fs.chmodSync(bp, 0o755);
      const info = binaryInfo();
      expect(info.tier).toBe("pro");
      expect(info.version).toBe("147.0.5555.1");
    } finally {
      fs.rmSync(dir, { recursive: true, force: true });
      if (orig) process.env.CLOAKBROWSER_CACHE_DIR = orig;
      else delete process.env.CLOAKBROWSER_CACHE_DIR;
    }
  });
});

describe("composable Playwright launch helpers", () => {
  const origBinaryPath = process.env.CLOAKBROWSER_BINARY_PATH;

  beforeEach(() => {
    process.env.CLOAKBROWSER_BINARY_PATH = "/fake/chrome";
    vi.resetModules();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
    if (origBinaryPath) {
      process.env.CLOAKBROWSER_BINARY_PATH = origBinaryPath;
    } else {
      delete process.env.CLOAKBROWSER_BINARY_PATH;
    }
  });

  it("exports composable helpers from the package entrypoint", async () => {
    const entry = await import("../src/index.js");

    expect(entry.buildLaunchOptions).toBeTypeOf("function");
    expect(entry.buildContextOptions).toBeTypeOf("function");
    expect(entry.humanizeBrowser).toBeTypeOf("function");
  });

  it("buildContextOptions returns Playwright context options without launching a browser", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { buildContextOptions } = await import("../src/index.js");

    const options = buildContextOptions({
      userAgent: "Explicit/1.0",
      viewport: { width: 1280, height: 720 },
      colorScheme: "dark",
      contextOptions: {
        userAgent: "Context/9.9",
        viewport: { width: 9999, height: 9999 },
        colorScheme: "light",
        storageState: "state.json",
        locale: "de-DE",
        timezoneId: "Europe/Berlin",
      },
    });

    expect(options).toMatchObject({
      userAgent: "Explicit/1.0",
      viewport: { width: 1280, height: 720 },
      colorScheme: "dark",
      storageState: "state.json",
    });
    expect(options.locale).toBeUndefined();
    expect(options.timezoneId).toBeUndefined();
    expect(warnSpy).toHaveBeenCalledTimes(2);
  });

  it("buildContextOptions applies DEFAULT_VIEWPORT by default and allows null viewport", async () => {
    const { buildContextOptions } = await import("../src/index.js");

    expect(buildContextOptions().viewport).toEqual(DEFAULT_VIEWPORT);
    expect(buildContextOptions({ viewport: null }).viewport).toBeNull();
  });

  it("buildContextOptions uses no viewport (null) when headed, so the page tracks the real window", async () => {
    const { buildContextOptions } = await import("../src/index.js");

    // Headed: no emulated viewport (CDP emulation would force outerWidth < innerWidth).
    expect(buildContextOptions({ headless: false }).viewport).toBeNull();
    // Headless keeps the deterministic default.
    expect(buildContextOptions({ headless: true }).viewport).toEqual(DEFAULT_VIEWPORT);
    // Explicit viewport always honored, even headed.
    const custom = { width: 800, height: 600 };
    expect(buildContextOptions({ headless: false, viewport: custom }).viewport).toEqual(custom);
  });

  it("buildContextOptions reads effective headless from launchOptions.headless", async () => {
    const { buildContextOptions } = await import("../src/index.js");

    // buildLaunchOptions spreads launchOptions LAST, so launchOptions.headless wins
    // at the actual launch. Viewport must follow it — a raw headless:false (browser
    // actually headed) must NOT get a fixed viewport (would reintroduce outer<inner).
    expect(buildContextOptions({ launchOptions: { headless: false } }).viewport).toBeNull();
    // And launchOptions.headless:true forces the deterministic viewport even if the
    // top-level field said headed.
    expect(
      buildContextOptions({ headless: false, launchOptions: { headless: true } }).viewport,
    ).toEqual(DEFAULT_VIEWPORT);
  });

  it("buildLaunchOptions returns Playwright options without launching a browser", async () => {
    const freshConfig = await import("../src/config.js");
    vi.spyOn(freshConfig, "getPlatformTag").mockReturnValue("darwin-arm64");
    try {
      const { buildLaunchOptions } = await import("../src/index.js");

      const options = await buildLaunchOptions({
        headless: false,
        proxy: "http://user:pass@proxy.example:8080",
        args: ["--custom-flag"],
        launchOptions: { timeout: 1234 },
      });

      expect(options.executablePath).toBe("/fake/chrome");
      expect(options.headless).toBe(false);
      expect(options.args).toContain("--custom-flag");
      expect(options.ignoreDefaultArgs).toContain("--enable-automation");
      expect(options.proxy).toEqual({
        server: "http://proxy.example:8080",
        username: "user",
        password: "pass",
      });
      expect(options.timeout).toBe(1234);
    } finally {
      vi.restoreAllMocks();
    }
  });

  it("humanizeBrowser patches an existing browser only when requested", async () => {
    const { humanizeBrowser } = await import("../src/index.js");
    const browser = {
      contexts: () => [],
      newContext: vi.fn(async () => ({})),
      newPage: vi.fn(async () => ({ context: () => ({}) })),
    };
    const originalNewContext = browser.newContext;

    await humanizeBrowser(browser as any, { humanize: false });
    expect(browser.newContext).toBe(originalNewContext);

    await humanizeBrowser(browser as any, { humanize: true });
    expect(browser.newContext).not.toBe(originalNewContext);
  });
});

describe("launch geoip warnings (unit)", () => {
  let mockChromium: any;
  const origBinaryPath = process.env.CLOAKBROWSER_BINARY_PATH;

  beforeEach(() => {
    vi.resetModules();
    vi.doUnmock("../src/geoip.js");
    process.env.CLOAKBROWSER_BINARY_PATH = "/fake/chrome";
    mockChromium = {
      launch: vi.fn().mockResolvedValue({ close: vi.fn() }),
    };
    vi.doMock("playwright-core", () => ({ chromium: mockChromium }));
  });

  afterEach(() => {
    vi.doUnmock("../src/geoip.js");
    vi.doUnmock("playwright-core");
    vi.restoreAllMocks();
    vi.resetModules();
    if (origBinaryPath) {
      process.env.CLOAKBROWSER_BINARY_PATH = origBinaryPath;
    } else {
      delete process.env.CLOAKBROWSER_BINARY_PATH;
    }
  });

  it("warns when geoip is true and no proxy is set", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { launch } = await import("../src/playwright.js");

    await launch({ geoip: true });

    expect(warnSpy).toHaveBeenCalledOnce();
    expect(warnSpy.mock.calls[0][0]).toMatch(/timezone\/locale will default/);
  });

  it("does not warn when proxy is set", async () => {
    vi.doMock("../src/geoip.js", () => ({
      maybeResolveGeoip: vi.fn(async (options: any) => ({
        timezone: options.timezone,
        locale: options.locale,
      })),
      resolveWebrtcArgs: vi.fn(async (options: any) => options.args),
    }));
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    const { launch } = await import("../src/playwright.js");

    await launch({ geoip: true, proxy: "http://example.com:8080" });

    expect(warnSpy).not.toHaveBeenCalled();
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
    const freshConfig = await import("../src/config.js");
    vi.spyOn(freshConfig, "getPlatformTag").mockReturnValue("darwin-arm64");
    try {
      const { launchPersistentContext } = await import("../src/playwright.js");
      await launchPersistentContext({
        userDataDir: "/tmp/profile",
        proxy: "http://user:pass@proxy:8080",
      });

      const args = mockChromium.launchPersistentContext.mock.calls[0][1];
      expect(args.proxy.server).toBe("http://proxy:8080");
      expect(args.proxy.username).toBe("user");
      expect(args.proxy.password).toBe("pass");
    } finally {
      vi.restoreAllMocks();
    }
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
