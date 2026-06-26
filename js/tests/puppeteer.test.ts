import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";

// Mock puppeteer-core and download before importing the module under test
vi.mock("puppeteer-core", () => ({
  default: {
    launch: vi.fn(),
  },
}));

vi.mock("../src/download.js", () => ({
  ensureBinary: vi.fn().mockResolvedValue("/fake/chrome"),
}));

vi.mock("../src/geoip.js", () => ({
  resolveProxyGeo: vi.fn().mockResolvedValue({ timezone: null, locale: null }),
  maybeResolveGeoip: vi.fn().mockResolvedValue({}),
  resolveWebrtcArgs: vi.fn().mockImplementation((opts: any) => Promise.resolve(opts.args)),
  appendWebrtcExitIp: vi.fn((args: any) => args),
}));

describe("puppeteer launch", () => {
  let puppeteerMock: any;
  let mockBrowser: any;

  beforeEach(async () => {
    delete process.env.CLOAKBROWSER_BINARY_PATH;
    puppeteerMock = await import("puppeteer-core");
    mockBrowser = {
      newPage: vi.fn().mockResolvedValue({
        authenticate: vi.fn(),
      }),
      close: vi.fn(),
    };
    vi.mocked(puppeteerMock.default.launch).mockResolvedValue(mockBrowser);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("calls ensureBinary and launches with binary path", async () => {
    const { launch } = await import("../src/puppeteer.js");
    await launch();

    expect(puppeteerMock.default.launch).toHaveBeenCalledWith(
      expect.objectContaining({
        executablePath: "/fake/chrome",
      })
    );
  });

  it("includes stealth args by default", async () => {
    const { launch } = await import("../src/puppeteer.js");
    await launch();

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.args.some((a: string) => a.startsWith("--fingerprint="))).toBe(true);
    expect(callArgs.args).toContain("--no-sandbox");
  });

  it("excludes stealth args when stealthArgs=false", async () => {
    const { launch } = await import("../src/puppeteer.js");
    await launch({ stealthArgs: false });

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.args.some((a: string) => a.startsWith("--fingerprint="))).toBe(false);
  });

  it("headless (default) uses a fixed defaultViewport; headed uses null", async () => {
    const { DEFAULT_VIEWPORT } = await import("../src/config.js");
    const { launch } = await import("../src/puppeteer.js");

    // Headless (default): deterministic viewport.
    await launch();
    expect(
      vi.mocked(puppeteerMock.default.launch).mock.calls[0][0].defaultViewport
    ).toEqual(DEFAULT_VIEWPORT);

    // Headed: null so the page tracks the real window (else Puppeteer forces 800x600).
    vi.mocked(puppeteerMock.default.launch).mockClear();
    await launch({ headless: false });
    expect(
      vi.mocked(puppeteerMock.default.launch).mock.calls[0][0].defaultViewport
    ).toBeNull();
  });

  it("honors an explicit launchOptions.defaultViewport (incl. null)", async () => {
    const { launch } = await import("../src/puppeteer.js");

    const custom = { width: 640, height: 480 };
    await launch({ headless: true, launchOptions: { defaultViewport: custom } });
    expect(
      vi.mocked(puppeteerMock.default.launch).mock.calls[0][0].defaultViewport
    ).toEqual(custom);

    // Explicit null honored even in headless (would otherwise default to DEFAULT_VIEWPORT).
    vi.mocked(puppeteerMock.default.launch).mockClear();
    await launch({ headless: true, launchOptions: { defaultViewport: null } });
    expect(
      vi.mocked(puppeteerMock.default.launch).mock.calls[0][0].defaultViewport
    ).toBeNull();
  });

  it("Puppeteer headless precedence: top-level headless wins over launchOptions.headless", async () => {
    const { DEFAULT_VIEWPORT } = await import("../src/config.js");
    const { launch } = await import("../src/puppeteer.js");

    // Puppeteer sets headless AFTER the launchOptions spread, so top-level wins at
    // launch — the viewport decision must follow the same (top-level) value.
    await launch({ headless: true, launchOptions: { headless: false } });
    const opts = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(opts.headless).toBe(true);
    expect(opts.defaultViewport).toEqual(DEFAULT_VIEWPORT);
  });

  it("adds --proxy-server for string proxy", async () => {
    const { launch } = await import("../src/puppeteer.js");
    await launch({ proxy: "http://proxy:8080" });

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.args).toContain("--proxy-server=http://proxy:8080");
  });

  it("adds --proxy-bypass-list for dict proxy with bypass", async () => {
    const { launch } = await import("../src/puppeteer.js");
    await launch({
      proxy: { server: "http://proxy:8080", bypass: ".google.com,localhost" },
    });

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.args).toContain("--proxy-server=http://proxy:8080");
    expect(callArgs.args).toContain("--proxy-bypass-list=.google.com,localhost");
  });

  it("uses page.authenticate fallback for http proxy on unsupported platform", async () => {
    const config = await import("../src/config.js");
    vi.spyOn(config, "getPlatformTag").mockReturnValue("darwin-arm64");
    try {
      const { launch } = await import("../src/puppeteer.js");
      const browser = await launch({ proxy: "http://user:pass@proxy:8080" });

      const page = await browser.newPage();
      expect(page.authenticate).toHaveBeenCalledWith({
        username: "user",
        password: "pass",
      });
    } finally {
      vi.restoreAllMocks();
    }
  });

  it("passes inline creds via --proxy-server on supported platform (no page.authenticate)", async () => {
    const config = await import("../src/config.js");
    vi.spyOn(config, "getPlatformTag").mockReturnValue("linux-x64");
    vi.spyOn(config, "getChromiumVersion").mockReturnValue("146.0.7680.177.5");
    try {
      const { launch } = await import("../src/puppeteer.js");
      const browser = await launch({ proxy: "http://user:pass@proxy:8080" });

      const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
      expect(callArgs.args).toContain("--proxy-server=http://user:pass@proxy:8080");

      const page = await browser.newPage();
      expect(page.authenticate).not.toHaveBeenCalled();
    } finally {
      vi.restoreAllMocks();
    }
  });

  it("injects timezone and locale as binary flags", async () => {
    const { launch } = await import("../src/puppeteer.js");
    await launch({ timezone: "Asia/Tokyo", locale: "ja-JP" });

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.args).toContain("--fingerprint-timezone=Asia/Tokyo");
    expect(callArgs.args).toContain("--lang=ja-JP");
  });

  it("resolves timezoneId to --fingerprint-timezone", async () => {
    const { launch } = await import("../src/puppeteer.js");
    await launch({ timezoneId: "Asia/Tokyo" } as unknown as Parameters<typeof launch>[0]);

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.args).toContain("--fingerprint-timezone=Asia/Tokyo");
  });

  it("merges extra args", async () => {
    const { launch } = await import("../src/puppeteer.js");
    await launch({ args: ["--disable-gpu", "--no-first-run"] });

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.args).toContain("--disable-gpu");
    expect(callArgs.args).toContain("--no-first-run");
  });

  it("keeps SOCKS5 credentials in --proxy-server URL", async () => {
    const { launch } = await import("../src/puppeteer.js");
    const browser = await launch({ proxy: "socks5://user:pass@proxy:1080" });

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.args).toContain("--proxy-server=socks5://user:pass@proxy:1080");

    // Should NOT set up page.authenticate for SOCKS5
    const page = await browser.newPage();
    expect(page.authenticate).not.toHaveBeenCalled();
  });

  it("forwards launchOptions to puppeteer launch", async () => {
    const { launch } = await import("../src/puppeteer.js");
    await launch({ launchOptions: { slowMo: 50 } });

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.slowMo).toBe(50);
  });

  it("reconstructs SOCKS5 dict with auth into --proxy-server URL", async () => {
    const { launch } = await import("../src/puppeteer.js");
    const browser = await launch({
      proxy: { server: "socks5://proxy:1080", username: "user", password: "p@ss" },
    });

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.args).toContain("--proxy-server=socks5://user:p%40ss@proxy:1080");

    const page = await browser.newPage();
    expect(page.authenticate).not.toHaveBeenCalled();
  });

  it("injects env when licenseKey provided", async () => {
    const { launch } = await import("../src/puppeteer.js");
    await launch({ licenseKey: "cb_pup_key" });
    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.env).toBeDefined();
    expect(callArgs.env!.CLOAKBROWSER_LICENSE_KEY).toBe("cb_pup_key");
  });

  it("does not inject env without license key", async () => {
    const { launch } = await import("../src/puppeteer.js");
    await launch({});
    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.env).toBeUndefined();
  });

  it("merges custom launchOptions.env with license key via puppeteer", async () => {
    const { launch } = await import("../src/puppeteer.js");
    await launch({
      licenseKey: "cb_merge",
      launchOptions: { env: { EXTRA: "val" } },
    });
    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.env!.CLOAKBROWSER_LICENSE_KEY).toBe("cb_merge");
    expect(callArgs.env!.EXTRA).toBe("val");
  });
});

describe("puppeteer launchPersistentContext", () => {
  let puppeteerMock: any;
  let mockBrowser: any;

  beforeEach(async () => {
    delete process.env.CLOAKBROWSER_BINARY_PATH;
    puppeteerMock = await import("puppeteer-core");
    mockBrowser = {
      newPage: vi.fn().mockResolvedValue({
        authenticate: vi.fn(),
      }),
      close: vi.fn(),
    };
    vi.mocked(puppeteerMock.default.launch).mockResolvedValue(mockBrowser);
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("passes userDataDir to puppeteer launch", async () => {
    process.env.CLOAKBROWSER_BINARY_PATH = "/fake/chrome";
    const { launchPersistentContext } = await import("../src/puppeteer.js");
    await launchPersistentContext({ userDataDir: "./my-profile" });

    expect(puppeteerMock.default.launch).toHaveBeenCalledWith(
      expect.objectContaining({
        userDataDir: "./my-profile",
        executablePath: "/fake/chrome",
      })
    );
  });

  it("includes stealth args", async () => {
    const { launchPersistentContext } = await import("../src/puppeteer.js");
    await launchPersistentContext({ userDataDir: "./my-profile" });

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.args.some((a: string) => a.startsWith("--fingerprint="))).toBe(true);
  });

  it("headed persistent context uses null defaultViewport (tracks real window)", async () => {
    const { DEFAULT_VIEWPORT } = await import("../src/config.js");
    const { launchPersistentContext } = await import("../src/puppeteer.js");

    await launchPersistentContext({ userDataDir: "./my-profile", headless: false });
    expect(
      vi.mocked(puppeteerMock.default.launch).mock.calls[0][0].defaultViewport
    ).toBeNull();

    vi.mocked(puppeteerMock.default.launch).mockClear();
    await launchPersistentContext({ userDataDir: "./my-profile", headless: true });
    expect(
      vi.mocked(puppeteerMock.default.launch).mock.calls[0][0].defaultViewport
    ).toEqual(DEFAULT_VIEWPORT);
  });

  it("uses page.authenticate fallback for http proxy in persistent context on unsupported platform", async () => {
    const config = await import("../src/config.js");
    vi.spyOn(config, "getPlatformTag").mockReturnValue("darwin-arm64");
    try {
      const { launchPersistentContext } = await import("../src/puppeteer.js");
      const browser = await launchPersistentContext({
        userDataDir: "./my-profile",
        proxy: "http://user:pass@proxy:8080",
      });

      const page = await browser.newPage();
      expect(page.authenticate).toHaveBeenCalledWith({
        username: "user",
        password: "pass",
      });
    } finally {
      vi.restoreAllMocks();
    }
  });

  it("keeps SOCKS5 credentials in --proxy-server URL", async () => {
    const { launchPersistentContext } = await import("../src/puppeteer.js");
    const browser = await launchPersistentContext({
      userDataDir: "./my-profile",
      proxy: "socks5://user:pass@proxy:1080",
    });

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.args).toContain("--proxy-server=socks5://user:pass@proxy:1080");

    const page = await browser.newPage();
    expect(page.authenticate).not.toHaveBeenCalled();
  });

  it("forwards launchOptions to puppeteer launch", async () => {
    const { launchPersistentContext } = await import("../src/puppeteer.js");
    await launchPersistentContext({ userDataDir: "./my-profile", launchOptions: { slowMo: 50 } });

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.slowMo).toBe(50);
    expect(callArgs.userDataDir).toBe("./my-profile");
  });

  it("injects timezone and locale as binary flags", async () => {
    const { launchPersistentContext } = await import("../src/puppeteer.js");
    await launchPersistentContext({
      userDataDir: "./my-profile",
      timezone: "Asia/Tokyo",
      locale: "ja-JP",
    });

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.args).toContain("--fingerprint-timezone=Asia/Tokyo");
    expect(callArgs.args).toContain("--lang=ja-JP");
  });

  it("injects env with licenseKey in persistent context", async () => {
    const { launchPersistentContext } = await import("../src/puppeteer.js");
    await launchPersistentContext({
      userDataDir: "./my-profile",
      licenseKey: "cb_pup_persist",
    });
    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.env).toBeDefined();
    expect(callArgs.env!.CLOAKBROWSER_LICENSE_KEY).toBe("cb_pup_persist");
  });

  it("preserves custom env via launchOptions in persistent context", async () => {
    const { launchPersistentContext } = await import("../src/puppeteer.js");
    await launchPersistentContext({
      userDataDir: "./my-profile",
      licenseKey: "cb_cust",
      launchOptions: { env: { CUSTOM: "val" } },
    });
    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.env!.CLOAKBROWSER_LICENSE_KEY).toBe("cb_cust");
    expect(callArgs.env!.CUSTOM).toBe("val");
  });
});
