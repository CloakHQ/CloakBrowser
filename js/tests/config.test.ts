import { afterEach, describe, it, expect } from "vitest";
import {
  CHROMIUM_VERSION,
  getArchiveExt,
  getChromiumVersion,
  getDefaultStealthArgs,
  getCacheDir,
  getBinaryDir,
  getDownloadUrl,
  getFallbackDownloadUrl,
} from "../src/config.js";
import { _buildArgsForTest, resolveTimezone } from "../src/playwright.js";

const originalPlatform = Object.getOwnPropertyDescriptor(process, "platform")!;
const originalGpuAccel = process.env.CLOAKBROWSER_GPU_ACCEL;

afterEach(() => {
  Object.defineProperty(process, "platform", originalPlatform);
  if (originalGpuAccel === undefined) {
    delete process.env.CLOAKBROWSER_GPU_ACCEL;
  } else {
    process.env.CLOAKBROWSER_GPU_ACCEL = originalGpuAccel;
  }
});

function setPlatform(platform: NodeJS.Platform): void {
  Object.defineProperty(process, "platform", { ...originalPlatform, value: platform });
}

describe("config", () => {
  it("CHROMIUM_VERSION matches expected format", () => {
    expect(CHROMIUM_VERSION).toMatch(/^\d+\.\d+\.\d+\.\d+(\.\d+)?$/);
  });

  it("getDefaultStealthArgs returns expected flags", () => {
    const args = getDefaultStealthArgs();
    const isMac = process.platform === "darwin";

    expect(args).toContain("--no-sandbox");

    if (isMac) {
      expect(args).toContain("--fingerprint-platform=macos");
    } else {
      expect(args).toContain("--fingerprint-platform=windows");
    }

    // GPU flags removed — binary auto-generates from seed + platform
    expect(args.some((a) => a.includes("fingerprint-gpu-vendor"))).toBe(false);
    expect(args.some((a) => a.includes("fingerprint-gpu-renderer"))).toBe(false);

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

  it("getBinaryDir includes platform version", () => {
    const dir = getBinaryDir();
    expect(dir).toContain(`chromium-${getChromiumVersion()}`);
  });

  it("getDownloadUrl contains platform version and platform tag", () => {
    const url = getDownloadUrl();
    expect(url).toContain(getChromiumVersion());
    expect(url).toContain("cloakbrowser-");
    expect(url).toContain(".tar.gz");
    expect(url).toContain("cloakbrowser.dev");
  });
});

describe("archive helpers", () => {
  it("getArchiveExt returns correct extension for platform", () => {
    const ext = getArchiveExt();
    if (process.platform === "win32") {
      expect(ext).toBe(".zip");
    } else {
      expect(ext).toBe(".tar.gz");
    }
  });

  it("getFallbackDownloadUrl uses GitHub Releases", () => {
    const url = getFallbackDownloadUrl("145.0.0.0");
    expect(url).toContain("github.com/CloakHQ/cloakbrowser/releases/download");
    expect(url).toContain("chromium-v145.0.0.0");
  });

  it("getFallbackDownloadUrl uses default version", () => {
    const url = getFallbackDownloadUrl();
    expect(url).toContain(`chromium-v${getChromiumVersion()}`);
  });
});

describe("buildArgs timezone/locale", () => {
  it("injects --fingerprint-timezone when timezone is set", () => {
    const args = _buildArgsForTest({ timezone: "America/New_York" });
    expect(args).toContain("--fingerprint-timezone=America/New_York");
  });

  it("injects --lang and --fingerprint-locale when locale is set", () => {
    const args = _buildArgsForTest({ locale: "en-US" });
    expect(args).toContain("--lang=en-US");
    expect(args).toContain("--fingerprint-locale=en-US");
  });

  it("injects both when both are set", () => {
    const args = _buildArgsForTest({ timezone: "Europe/Berlin", locale: "de-DE" });
    expect(args).toContain("--fingerprint-timezone=Europe/Berlin");
    expect(args).toContain("--lang=de-DE");
    expect(args).toContain("--fingerprint-locale=de-DE");
  });

  it("injects timezone/locale even when stealthArgs=false", () => {
    const args = _buildArgsForTest({ stealthArgs: false, timezone: "America/New_York", locale: "en-US" });
    expect(args).toContain("--fingerprint-timezone=America/New_York");
    expect(args).toContain("--lang=en-US");
    expect(args).toContain("--fingerprint-locale=en-US");
    expect(args.some(a => a.startsWith("--fingerprint="))).toBe(false);
  });

  it("does not inject flags when not set", () => {
    const args = _buildArgsForTest({});
    expect(args.some(a => a.startsWith("--fingerprint-timezone="))).toBe(false);
    expect(args.some(a => a.startsWith("--lang="))).toBe(false);
    expect(args.some(a => a.startsWith("--fingerprint-locale="))).toBe(false);
  });
});

describe("buildArgs deduplication", () => {
  it("user --fingerprint overrides default seed", () => {
    const args = _buildArgsForTest({ args: ["--fingerprint=99887"] });
    const fpArgs = args.filter(a => a.startsWith("--fingerprint="));
    expect(fpArgs).toHaveLength(1);
    expect(fpArgs[0]).toBe("--fingerprint=99887");
  });

  it("user --fingerprint-platform overrides default", () => {
    const args = _buildArgsForTest({ args: ["--fingerprint-platform=linux"] });
    const platArgs = args.filter(a => a.startsWith("--fingerprint-platform="));
    expect(platArgs).toHaveLength(1);
    expect(platArgs[0]).toBe("--fingerprint-platform=linux");
  });

  it("timezone param overrides user --fingerprint-timezone arg", () => {
    const args = _buildArgsForTest({
      args: ["--fingerprint-timezone=Europe/London"],
      timezone: "America/New_York",
    });
    const tzArgs = args.filter(a => a.startsWith("--fingerprint-timezone="));
    expect(tzArgs).toHaveLength(1);
    expect(tzArgs[0]).toBe("--fingerprint-timezone=America/New_York");
  });

  it("locale param overrides user --lang and --fingerprint-locale args", () => {
    const args = _buildArgsForTest({
      args: ["--lang=de-DE", "--fingerprint-locale=de-DE"],
      locale: "en-US",
    });
    const langArgs = args.filter(a => a.startsWith("--lang="));
    expect(langArgs).toHaveLength(1);
    expect(langArgs[0]).toBe("--lang=en-US");
    const localeArgs = args.filter(a => a.startsWith("--fingerprint-locale="));
    expect(localeArgs).toHaveLength(1);
    expect(localeArgs[0]).toBe("--fingerprint-locale=en-US");
  });

  it("no duplicate flag keys in output", () => {
    const args = _buildArgsForTest({
      args: ["--fingerprint=99887", "--fingerprint-timezone=UTC", "--lang=fr-FR"],
      timezone: "Europe/Berlin",
      locale: "de-DE",
    });
    const keys = args.map(a => a.split("=")[0]);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("non-value flags preserved without dedup issues", () => {
    const args = _buildArgsForTest({ args: ["--disable-gpu", "--no-zygote"] });
    expect(args).toContain("--disable-gpu");
    expect(args).toContain("--no-zygote");
    expect(args).toContain("--no-sandbox");
  });
});

describe("buildArgs GPU acceleration", () => {
  it("leaves GPU acceleration flags off by default", () => {
    delete process.env.CLOAKBROWSER_GPU_ACCEL;
    const args = _buildArgsForTest({});
    expect(args).not.toContain("--use-gl=egl");
    expect(args).not.toContain("--enable-gpu-rasterization");
    expect(args).not.toContain("--enable-features=VaapiVideoDecoder");
  });

  it("CLOAKBROWSER_GPU_ACCEL adds Linux GPU flags", () => {
    process.env.CLOAKBROWSER_GPU_ACCEL = "1";
    setPlatform("linux");
    const args = _buildArgsForTest({});
    expect(args).toContain("--use-gl=egl");
    expect(args).toContain("--enable-gpu-rasterization");
    expect(args).toContain("--ignore-gpu-blocklist");
    expect(args).toContain("--enable-features=VaapiVideoDecoder");
  });

  it("skips VaapiVideoDecoder off Linux", () => {
    process.env.CLOAKBROWSER_GPU_ACCEL = "1";
    setPlatform("darwin");
    const args = _buildArgsForTest({});
    expect(args).toContain("--use-gl=egl");
    expect(args).toContain("--enable-gpu-rasterization");
    expect(args).not.toContain("--enable-features=VaapiVideoDecoder");
  });

  it("gpuAccel option adds GPU flags without the environment variable", () => {
    delete process.env.CLOAKBROWSER_GPU_ACCEL;
    setPlatform("linux");
    const args = _buildArgsForTest({ gpuAccel: true });
    expect(args).toContain("--use-gl=egl");
    expect(args).toContain("--enable-gpu-rasterization");
    expect(args).toContain("--ignore-gpu-blocklist");
    expect(args).toContain("--enable-features=VaapiVideoDecoder");
  });
});

describe("buildArgs webrtc IP", () => {
  it("passes --fingerprint-webrtc-ip from args", () => {
    const args = _buildArgsForTest({ args: ["--fingerprint-webrtc-ip=1.2.3.4"] });
    expect(args).toContain("--fingerprint-webrtc-ip=1.2.3.4");
  });

  it("does not inject when not in args", () => {
    const args = _buildArgsForTest({});
    expect(args.some(a => a.startsWith("--fingerprint-webrtc-ip"))).toBe(false);
  });
});

describe("resolveTimezone alias", () => {
  it("resolves timezoneId to timezone", () => {
    const result = resolveTimezone({ timezoneId: "Europe/Paris" });
    expect(result.timezone).toBe("Europe/Paris");
    expect(result).not.toHaveProperty("timezoneId");
  });

  it("preserves explicit timezone over timezoneId", () => {
    const result = resolveTimezone({ timezone: "UTC", timezoneId: "Europe/Paris" });
    expect(result.timezone).toBe("UTC");
    expect(result).not.toHaveProperty("timezoneId");
  });

  it("returns options unchanged when no timezoneId", () => {
    const opts = { timezone: "UTC" };
    const result = resolveTimezone(opts);
    expect(result).toBe(opts); // same reference, no copy
    expect(result.timezone).toBe("UTC");
  });

  it("returns options unchanged when neither is set", () => {
    const opts = {};
    const result = resolveTimezone(opts);
    expect(result).toBe(opts);
  });
});
