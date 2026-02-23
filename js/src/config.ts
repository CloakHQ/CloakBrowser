/**
 * Stealth configuration and platform detection for cloakbrowser.
 * Mirrors Python cloakbrowser/config.py.
 */

import os from "node:os";
import path from "node:path";

// ---------------------------------------------------------------------------
// Chromium version shipped with this release
// ---------------------------------------------------------------------------
export const CHROMIUM_VERSION = "142.0.7444.175";

// ---------------------------------------------------------------------------
// Platform detection
// ---------------------------------------------------------------------------
const SUPPORTED_PLATFORMS: Record<string, string> = {
  "linux-x64": "linux-x64",
  "linux-arm64": "linux-arm64",
  "darwin-arm64": "darwin-arm64",
  "darwin-x64": "darwin-x64",
};

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

export function getBinaryDir(): string {
  return path.join(getCacheDir(), `chromium-${CHROMIUM_VERSION}`);
}

export function getBinaryPath(): string {
  const binaryDir = getBinaryDir();
  if (process.platform === "darwin") {
    return path.join(binaryDir, "Chromium.app", "Contents", "MacOS", "Chromium");
  }
  return path.join(binaryDir, "chrome");
}

// ---------------------------------------------------------------------------
// Download URL
// ---------------------------------------------------------------------------
const DOWNLOAD_BASE_URL =
  process.env.CLOAKBROWSER_DOWNLOAD_URL ||
  "https://github.com/CloakHQ/chromium-stealth-builds/releases/download";

export function getDownloadUrl(): string {
  const tag = getPlatformTag();
  return `${DOWNLOAD_BASE_URL}/v${CHROMIUM_VERSION}/cloakbrowser-${tag}.tar.gz`;
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
  return [
    "--no-sandbox",
    "--disable-blink-features=AutomationControlled",
    `--fingerprint=${seed}`,
    "--fingerprint-platform=windows",
    "--fingerprint-hardware-concurrency=8",
    "--fingerprint-gpu-vendor=NVIDIA Corporation",
    "--fingerprint-gpu-renderer=NVIDIA GeForce RTX 3070",
  ];
}
