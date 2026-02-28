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
export const CHROMIUM_VERSION = "142.0.7444.175";

// ---------------------------------------------------------------------------
const SUPPORTED_PLATFORMS: Record<string, string> = {
  "linux-x64": "linux-x64",
  "linux-arm64": "linux-arm64",
  "darwin-arm64": "darwin-arm64",
  "darwin-x64": "darwin-x64",
  "win32-x64": "win32-x64",
  "win32-arm64": "win32-arm64",
};

// Platforms with pre-built binaries available for download.
// Update this set as new platform builds are released.
const AVAILABLE_PLATFORMS = new Set(["linux-x64", "darwin-arm64", "darwin-x64", "win32-x64"]);

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
  return path.join(getCacheDir(), `chromium-${version || CHROMIUM_VERSION}`);
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

export function getDownloadUrl(version?: string): string {
  const v = version || CHROMIUM_VERSION;
  const tag = getPlatformTag();
  return `${DOWNLOAD_BASE_URL}/chromium-v${v}/cloakbrowser-${tag}.tar.gz`;
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
export function getDefaultStealthArgs(): string[] {
  const seed = Math.floor(Math.random() * 90000) + 10000; // 10000-99999
  const isMac = process.platform === "darwin";
  const isWindows = process.platform === "win32";

  const base = [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    `--fingerprint=${seed}`,
  ];

  if (isMac) {
    // macOS: run as native Mac browser — GPU/UA match natively
    return [...base, "--fingerprint-platform=macos"];
  }

  if (isWindows) {
    // Windows: native platform
    return [...base, "--fingerprint-platform=windows"];
  }

  // Linux: spoof as Windows
  return [
    ...base,
    "--fingerprint-platform=windows",
    "--fingerprint-hardware-concurrency=8",
    "--fingerprint-gpu-vendor=NVIDIA Corporation",
    "--fingerprint-gpu-renderer=NVIDIA GeForce RTX 3070",
  ];
}


