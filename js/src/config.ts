/**
 * Stealth configuration and platform detection for cloakbrowser.
 * Mirrors Python cloakbrowser/config.py.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Read wrapper version from package.json (single source of truth)
let WRAPPER_VERSION = "0.0.0";
try {
  const _configDir = path.dirname(fileURLToPath(import.meta.url));
  const _pkgPath = path.resolve(_configDir, "..", "package.json");
  const _pkg = JSON.parse(fs.readFileSync(_pkgPath, "utf-8")) as { version: string };
  WRAPPER_VERSION = _pkg.version;
} catch {
  // Fallback — package.json not found (bundled or unusual layout).
  // Wrapper update check will compare against 0.0.0 and always suggest updating.
}
export { WRAPPER_VERSION };

// ---------------------------------------------------------------------------
// Chromium version shipped with this release.
// Different platforms may ship different versions during transition periods.
// CHROMIUM_VERSION is the latest across all platforms (for display/reference).
// Use getChromiumVersion() for the current platform's actual version.
// ---------------------------------------------------------------------------
export const CHROMIUM_VERSION = "145.0.7632.159.6";

export const PLATFORM_CHROMIUM_VERSIONS: Record<string, string> = {
  "linux-x64": "145.0.7632.159.6",
  "darwin-arm64": "145.0.7632.109.2",
  "darwin-x64": "145.0.7632.109.2",
  "windows-x64": "145.0.7632.109.2",
};

// ---------------------------------------------------------------------------
// Platform detection
// ---------------------------------------------------------------------------
const SUPPORTED_PLATFORMS: Record<string, string> = {
  "linux-x64": "linux-x64",
  "linux-arm64": "linux-arm64",
  "darwin-arm64": "darwin-arm64",
  "darwin-x64": "darwin-x64",
  "win32-x64": "windows-x64",
};

// Platforms with pre-built binaries available for download (derived from version map).
const AVAILABLE_PLATFORMS = new Set(Object.keys(PLATFORM_CHROMIUM_VERSIONS));

export function getChromiumVersion(): string {
  const tag = getPlatformTag();
  return PLATFORM_CHROMIUM_VERSIONS[tag] ?? CHROMIUM_VERSION;
}

export function getPlatformTag(): string {
  const platform = process.platform;
  const arch = process.arch;

  // Map Node.js platform/arch to our tag format
  let key: string;
  if (platform === "linux" && arch === "x64") key = "linux-x64";
  else if (platform === "linux" && arch === "arm64") key = "linux-arm64";
  else if (platform === "darwin" && arch === "arm64") key = "darwin-arm64";
  else if (platform === "darwin" && arch === "x64") key = "darwin-x64";
  else if (platform === "win32" && arch === "x64") key = "win32-x64";
  else {
    const supported = Object.values(SUPPORTED_PLATFORMS).join(", ");
    throw new Error(
      `Unsupported platform: ${platform} ${arch}. Supported: ${supported}`
    );
  }

  return SUPPORTED_PLATFORMS[key]!;
}

// ---------------------------------------------------------------------------
// Binary cache paths
// ---------------------------------------------------------------------------
export function getCacheDir(): string {
  const custom = process.env.CLOAKBROWSER_CACHE_DIR;
  if (custom) return custom;
  return path.join(os.homedir(), ".cloakbrowser");
}

export function getBinaryDir(version?: string): string {
  return path.join(getCacheDir(), `chromium-${version || getChromiumVersion()}`);
}

export function getBinaryPath(version?: string): string {
  const binaryDir = getBinaryDir(version);
  if (process.platform === "darwin") {
    return path.join(binaryDir, "Chromium.app", "Contents", "MacOS", "Chromium");
  }
  if (process.platform === "win32") {
    return path.join(binaryDir, "chrome.exe");
  }
  return path.join(binaryDir, "chrome");
}

export function checkPlatformAvailable(): void {
  if (getLocalBinaryOverride()) return;

  const tag = getPlatformTag(); // throws if unsupported entirely
  if (!AVAILABLE_PLATFORMS.has(tag)) {
    const available = [...AVAILABLE_PLATFORMS].sort().join(", ");
    throw new Error(
      `CloakBrowser — Pre-built binaries are currently only available for: ${available}.\n\n` +
        `To use CloakBrowser now, set CLOAKBROWSER_BINARY_PATH to a local Chromium binary.`
    );
  }
}

// ---------------------------------------------------------------------------
// Download URL
// ---------------------------------------------------------------------------
export const DOWNLOAD_BASE_URL =
  process.env.CLOAKBROWSER_DOWNLOAD_URL ||
  "https://cloakbrowser.dev";

export const GITHUB_API_URL =
  "https://api.github.com/repos/CloakHQ/cloakbrowser/releases";

export const GITHUB_DOWNLOAD_BASE_URL =
  "https://github.com/CloakHQ/cloakbrowser/releases/download";

export function getArchiveExt(): string {
  return process.platform === "win32" ? ".zip" : ".tar.gz";
}

export function getArchiveName(tag?: string): string {
  return `cloakbrowser-${tag || getPlatformTag()}${getArchiveExt()}`;
}

export function getDownloadUrl(version?: string): string {
  const v = version || getChromiumVersion();
  return `${DOWNLOAD_BASE_URL}/chromium-v${v}/${getArchiveName()}`;
}

export function getFallbackDownloadUrl(version?: string): string {
  const v = version || getChromiumVersion();
  return `${GITHUB_DOWNLOAD_BASE_URL}/chromium-v${v}/${getArchiveName()}`;
}

export function getEffectiveVersion(): string {
  const base = getChromiumVersion();
  const cacheDir = getCacheDir();
  // Try platform-scoped marker first, fall back to legacy marker for upgrades from <0.3.0
  for (const name of [`latest_version_${getPlatformTag()}`, "latest_version"]) {
    const marker = path.join(cacheDir, name);
    try {
      if (fs.existsSync(marker)) {
        const version = fs.readFileSync(marker, "utf-8").trim();
        if (version && versionNewer(version, base)) {
          const binary = getBinaryPath(version);
          if (fs.existsSync(binary)) {
            return version;
          }
        }
      }
    } catch {
      // Marker unreadable — try next
    }
  }
  return base;
}

export function parseVersion(v: string): number[] {
  return v.split(".").map(Number);
}

export function versionNewer(a: string, b: string): boolean {
  const va = parseVersion(a);
  const vb = parseVersion(b);
  for (let i = 0; i < Math.max(va.length, vb.length); i++) {
    if ((va[i] ?? 0) > (vb[i] ?? 0)) return true;
    if ((va[i] ?? 0) < (vb[i] ?? 0)) return false;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Local binary override
// ---------------------------------------------------------------------------
export function getLocalBinaryOverride(): string | undefined {
  return process.env.CLOAKBROWSER_BINARY_PATH || undefined;
}

// ---------------------------------------------------------------------------
// Playwright default args to suppress — these leak automation signals.
// --enable-automation: exposes navigator.webdriver = true
// --enable-unsafe-swiftshader: forces software WebGL rendering via SwiftShader,
//   producing a distinctive renderer string that no real user browser has
// ---------------------------------------------------------------------------
export const IGNORE_DEFAULT_ARGS = ["--enable-automation", "--enable-unsafe-swiftshader"];

// ---------------------------------------------------------------------------
// Default stealth arguments
// ---------------------------------------------------------------------------
// Default viewport — realistic maximized Chrome on 1080p Windows
// screen=1920x1080, availHeight=1032 (minus 48px taskbar, binary default),
// innerHeight=947 (minus ~85px Chrome UI: tabs + address bar + bookmarks)
export const DEFAULT_VIEWPORT = { width: 1920, height: 947 };

export function getDefaultStealthArgs(): string[] {
  const seed = Math.floor(Math.random() * 90000) + 10000; // 10000-99999
  const isMac = process.platform === "darwin";

  const base = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    `--fingerprint=${seed}`,
  ];

  if (isMac) {
    // macOS: run as native Mac browser — GPU/UA match natively
    return [
      ...base,
      "--fingerprint-platform=macos",
      "--fingerprint-gpu-vendor=Google Inc. (Apple)",
      "--fingerprint-gpu-renderer=ANGLE (Apple, ANGLE Metal Renderer: Apple M3, Unspecified Version)",
    ];
  }

  // Linux/Windows: spoof as Windows desktop
  // Hardware concurrency, device memory, screen, and window size are
  // auto-generated by the binary from the seed (v14+).
  return [
    ...base,
    "--fingerprint-platform=windows",
    "--fingerprint-gpu-vendor=Google Inc. (NVIDIA)",
    "--fingerprint-gpu-renderer=ANGLE (NVIDIA, NVIDIA GeForce RTX 3070 (0x00002484) Direct3D11 vs_5_0 ps_5_0, D3D11)",
  ];
}
