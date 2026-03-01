/**
 * Stealth configuration and platform detection for cloakbrowser.
 * Mirrors Python cloakbrowser/config.py.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// ---------------------------------------------------------------------------
// Chromium version shipped with this release
// ---------------------------------------------------------------------------
export const CHROMIUM_VERSION = "145.0.7632.109";

// ---------------------------------------------------------------------------
// Platform detection
// ---------------------------------------------------------------------------
const SUPPORTED_PLATFORMS: Record<string, string> = {
  "linux-x64": "linux-x64",
  "linux-arm64": "linux-arm64",
  "darwin-arm64": "darwin-arm64",
  "darwin-x64": "darwin-x64",
};

// Platforms with pre-built binaries available for download.
// Update this set as new platform builds are released.
const AVAILABLE_PLATFORMS = new Set(["linux-x64", "darwin-arm64", "darwin-x64"]);

export function getPlatformTag(): string {
  const platform = process.platform;
  const arch = process.arch;

  // Map Node.js platform/arch to our tag format
  let key: string;
  if (platform === "linux" && arch === "x64") key = "linux-x64";
  else if (platform === "linux" && arch === "arm64") key = "linux-arm64";
  else if (platform === "darwin" && arch === "arm64") key = "darwin-arm64";
  else if (platform === "darwin" && arch === "x64") key = "darwin-x64";
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
  return path.join(getCacheDir(), `chromium-${version || CHROMIUM_VERSION}`);
}

export function getBinaryPath(version?: string): string {
  const binaryDir = getBinaryDir(version);
  if (process.platform === "darwin") {
    return path.join(binaryDir, "Chromium.app", "Contents", "MacOS", "Chromium");
  }
  return path.join(binaryDir, "chrome");
}

export function checkPlatformAvailable(): void {
  if (getLocalBinaryOverride()) return;

  const tag = getPlatformTag(); // throws if unsupported entirely
  if (!AVAILABLE_PLATFORMS.has(tag)) {
    const available = [...AVAILABLE_PLATFORMS].sort().join(", ");
    throw new Error(
      `CloakBrowser — Pre-built binaries are currently only available for: ${available}.\n` +
        `Windows builds are coming soon.\n\n` +
        `To use CloakBrowser now, run in Docker (see README) or set CLOAKBROWSER_BINARY_PATH.`
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

export function getDownloadUrl(version?: string): string {
  const v = version || CHROMIUM_VERSION;
  const tag = getPlatformTag();
  return `${DOWNLOAD_BASE_URL}/chromium-v${v}/cloakbrowser-${tag}.tar.gz`;
}

export function getFallbackDownloadUrl(version?: string): string {
  const v = version || CHROMIUM_VERSION;
  const tag = getPlatformTag();
  return `${GITHUB_DOWNLOAD_BASE_URL}/chromium-v${v}/cloakbrowser-${tag}.tar.gz`;
}

export function getEffectiveVersion(): string {
  const marker = path.join(getCacheDir(), "latest_version");
  try {
    if (fs.existsSync(marker)) {
      const version = fs.readFileSync(marker, "utf-8").trim();
      if (version && versionNewer(version, CHROMIUM_VERSION)) {
        const binary = getBinaryPath(version);
        if (fs.existsSync(binary)) {
          return version;
        }
      }
    }
  } catch {
    // Marker unreadable — fall back to hardcoded
  }
  return CHROMIUM_VERSION;
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
// Default stealth arguments
// ---------------------------------------------------------------------------
// Default viewport — realistic maximized Chrome on 1080p Windows
// screen=1920x1080, availHeight=1040 (minus 40px taskbar),
// innerHeight=955 (minus ~85px Chrome UI: tabs + address bar + bookmarks)
export const DEFAULT_VIEWPORT = { width: 1920, height: 955 };

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
    return [...base, "--fingerprint-platform=macos"];
  }

  // Linux: spoof as Windows
  return [
    ...base,
    "--fingerprint-platform=windows",
    "--fingerprint-hardware-concurrency=8",
    "--fingerprint-device-memory=8",
    "--fingerprint-gpu-vendor=NVIDIA Corporation",
    "--fingerprint-gpu-renderer=NVIDIA GeForce RTX 3070",
    "--fingerprint-taskbar-height=40",
    "--fingerprint-screen-width=1920",
    "--fingerprint-screen-height=1080",
    "--window-size=1920,1080",
  ];
}
