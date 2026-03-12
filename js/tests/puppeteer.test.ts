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
}));

describe("puppeteer launch", () => {
  let puppeteerMock: any;
  let mockBrowser: any;

  beforeEach(async () => {
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

  it("monkey-patches newPage for proxy auth", async () => {
    const { launch } = await import("../src/puppeteer.js");
    const browser = await launch({ proxy: "http://user:pass@proxy:8080" });

    // newPage should auto-authenticate
    const page = await browser.newPage();
    expect(page.authenticate).toHaveBeenCalledWith({
      username: "user",
      password: "pass",
    });
  });

  it("injects timezone and locale as binary flags", async () => {
    const { launch } = await import("../src/puppeteer.js");
    await launch({ timezone: "Asia/Tokyo", locale: "ja-JP" });

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.args).toContain("--fingerprint-timezone=Asia/Tokyo");
    expect(callArgs.args).toContain("--lang=ja-JP");
  });

  it("merges extra args", async () => {
    const { launch } = await import("../src/puppeteer.js");
    await launch({ args: ["--disable-gpu", "--no-first-run"] });

    const callArgs = vi.mocked(puppeteerMock.default.launch).mock.calls[0][0];
    expect(callArgs.args).toContain("--disable-gpu");
    expect(callArgs.args).toContain("--no-first-run");
  });
});
