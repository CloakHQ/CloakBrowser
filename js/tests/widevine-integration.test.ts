import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";

// Assert the persistent-context launchers actually invoke seedWidevineHint,
// so accidental removal of the wiring fails CI (parity with the Python
// test_persistent_context_seeds_widevine tests).

vi.mock("../src/widevine.js", () => ({
  seedWidevineHint: vi.fn(),
  resolveWidevineCdmDir: vi.fn(),
}));
vi.mock("../src/download.js", () => ({
  ensureBinary: vi.fn().mockResolvedValue("/fake/chrome"),
}));
vi.mock("../src/geoip.js", () => ({
  resolveProxyGeo: vi.fn().mockResolvedValue({ timezone: null, locale: null }),
  maybeResolveGeoip: vi.fn().mockResolvedValue({}),
  resolveWebrtcArgs: vi.fn().mockImplementation((opts: any) => Promise.resolve(opts.args)),
}));
vi.mock("playwright-core", () => ({ chromium: { launchPersistentContext: vi.fn() } }));
vi.mock("puppeteer-core", () => ({ default: { launch: vi.fn() } }));

describe("persistent context seeds Widevine (integration)", () => {
  beforeEach(() => {
    delete process.env.CLOAKBROWSER_BINARY_PATH;
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("Playwright launchPersistentContext seeds with (userDataDir, binaryPath)", async () => {
    const pw = await import("playwright-core");
    vi.mocked(pw.chromium.launchPersistentContext).mockResolvedValue({
      close: vi.fn(),
      pages: () => [],
    } as any);

    const { seedWidevineHint } = await import("../src/widevine.js");
    const { launchPersistentContext } = await import("../src/playwright.js");
    await launchPersistentContext({ userDataDir: "/tmp/profile" });

    expect(seedWidevineHint).toHaveBeenCalledWith("/tmp/profile", "/fake/chrome");
  });

  it("Puppeteer launchPersistentContext seeds with (userDataDir, binaryPath)", async () => {
    const pptr = await import("puppeteer-core");
    vi.mocked(pptr.default.launch).mockResolvedValue({
      newPage: vi.fn().mockResolvedValue({ authenticate: vi.fn() }),
      close: vi.fn(),
    } as any);

    const { seedWidevineHint } = await import("../src/widevine.js");
    const { launchPersistentContext } = await import("../src/puppeteer.js");
    await launchPersistentContext({ userDataDir: "/tmp/profile" });

    expect(seedWidevineHint).toHaveBeenCalledWith("/tmp/profile", "/fake/chrome");
  });
});
