import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";

describe("buildLaunchOptions", () => {
  const origEnv = process.env.CLOAKBROWSER_BINARY_PATH;

  beforeEach(() => {
    process.env.CLOAKBROWSER_BINARY_PATH = "/fake/chrome";
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

  it("returns executablePath, args, and ignoreDefaultArgs with no proxy key by default", async () => {
    const { buildLaunchOptions } = await import("../src/playwright.js");
    const opts = await buildLaunchOptions();

    expect(opts.executablePath).toBe("/fake/chrome");
    expect(Array.isArray(opts.args)).toBe(true);
    expect((opts.args as string[]).length).toBeGreaterThan(0);
    expect(opts.ignoreDefaultArgs).toBeDefined();
    expect("proxy" in opts).toBe(false);
  });

  it("defaults headless to true and respects explicit false", async () => {
    const { buildLaunchOptions } = await import("../src/playwright.js");

    const defaultOpts = await buildLaunchOptions();
    expect(defaultOpts.headless).toBe(true);

    const headedOpts = await buildLaunchOptions({ headless: false });
    expect(headedOpts.headless).toBe(false);
  });

  it("includes parsed proxy server/username/password for http://u:p@host:port", async () => {
    const { buildLaunchOptions } = await import("../src/playwright.js");
    const opts = await buildLaunchOptions({ proxy: "http://u:p@host:1080" });

    expect(opts.proxy).toBeDefined();
    const proxy = opts.proxy as { server: string; username?: string; password?: string };
    expect(proxy.server).toBe("http://host:1080");
    expect(proxy.username).toBe("u");
    expect(proxy.password).toBe("p");
  });

  it("does not consume `humanize` — humanize is purely a humanizeBrowser concern", async () => {
    const { buildLaunchOptions } = await import("../src/playwright.js");
    // Fixed args + stealthArgs:false makes the resulting args list deterministic
    // (default stealth args inject a random --fingerprint=<seed> per call).
    const fixed: import("../src/types.js").LaunchOptions = {
      stealthArgs: false,
      args: ["--fingerprint=12345"],
    };
    const optsBase = await buildLaunchOptions(fixed);
    const optsHumanized = await buildLaunchOptions({ ...fixed, humanize: true });

    expect(optsHumanized.args).toEqual(optsBase.args);
    expect("humanize" in optsHumanized).toBe(false);
  });

  it("forwards launchOptions overrides into the returned dict", async () => {
    const { buildLaunchOptions } = await import("../src/playwright.js");
    const opts = await buildLaunchOptions({
      launchOptions: { downloadsPath: "/tmp/downloads", timeout: 5000 },
    });

    expect((opts as any).downloadsPath).toBe("/tmp/downloads");
    expect((opts as any).timeout).toBe(5000);
  });
});

describe("launch (regression — uses buildLaunchOptions)", () => {
  let mockBrowser: any;
  let mockChromium: any;
  const origEnv = process.env.CLOAKBROWSER_BINARY_PATH;

  beforeEach(() => {
    process.env.CLOAKBROWSER_BINARY_PATH = "/fake/chrome";
    mockBrowser = { close: vi.fn() };
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

  it("forwards the buildLaunchOptions dict verbatim to chromium.launch", async () => {
    const { launch, buildLaunchOptions } = await import("../src/playwright.js");
    // Pin args + disable stealth defaults so the comparison is deterministic
    // (default stealth args inject a random --fingerprint=<seed> per call).
    const fixed = {
      headless: false,
      stealthArgs: false,
      args: ["--fingerprint=12345"],
    } as const;
    const expected = await buildLaunchOptions(fixed);

    await launch(fixed);

    const call = mockChromium.launch.mock.calls[0][0];
    expect(call.executablePath).toBe(expected.executablePath);
    expect(call.headless).toBe(false);
    expect(call.args).toEqual(expected.args);
    expect(call.ignoreDefaultArgs).toEqual(expected.ignoreDefaultArgs);
  });
});

describe("humanizeBrowser", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });

  it("is a no-op when humanize is false — does not import ./human/index.js", async () => {
    const humanModuleSpy = vi.fn();
    vi.doMock("../src/human/index.js", () => {
      humanModuleSpy();
      return { patchBrowser: vi.fn() };
    });

    const { humanizeBrowser } = await import("../src/playwright.js");
    const fakeBrowser = {} as any;
    await humanizeBrowser(fakeBrowser, { humanize: false });
    await humanizeBrowser(fakeBrowser, {}); // humanize undefined

    expect(humanModuleSpy).not.toHaveBeenCalled();
  });

  it("invokes patchBrowser when humanize is true", async () => {
    const patchBrowser = vi.fn();
    vi.doMock("../src/human/index.js", () => ({ patchBrowser }));

    const { humanizeBrowser } = await import("../src/playwright.js");
    const fakeBrowser = {} as any;
    await humanizeBrowser(fakeBrowser, { humanize: true });

    expect(patchBrowser).toHaveBeenCalledOnce();
    expect(patchBrowser.mock.calls[0][0]).toBe(fakeBrowser);
  });
});
