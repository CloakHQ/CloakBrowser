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
// Ed25519 public keys for verifying downloaded binaries.
//
// Each release publishes SHA256SUMS and a detached signature SHA256SUMS.sig.
// The wrapper verifies that signature against the keys below before trusting
// any hash in the manifest, so the download origin alone cannot certify a
// tampered binary. Values are base64 of the 32-byte raw public key. Multiple
// entries are accepted to allow key rotation. Keep in parity with config.py.
// ---------------------------------------------------------------------------
export const BINARY_SIGNING_PUBKEYS: string[] = [
  "MKFKwIhUcKWq5xTuNA0Ovg99njcDEcEJvmWYYhApvaU=",
];

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

const VERSION_PIN_RE = /^[0-9]+(?:\.[0-9]+){3,4}$/;

export function normalizeReleaseChannel(releaseChannel?: string): "stable" | "preview" {
  const raw = releaseChannel ?? process.env.CLOAKBROWSER_RELEASE_CHANNEL ?? "stable";
  return raw.trim().toLowerCase() === "preview" ? "preview" : "stable";
}

export function normalizeRequestedVersion(version?: string): string | undefined {
  const raw = version ?? process.env.CLOAKBROWSER_VERSION;
  if (raw == null) return undefined;
  const normalized = raw.trim();
  if (!normalized) return undefined;
  if (!VERSION_PIN_RE.test(normalized)) {
    throw new Error(
      "Invalid browser version pin. Use a full numeric Chromium version, " +
        "e.g. '148.0.7778.215.2'."
    );
  }
  return normalized;
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

/** Cache dir for a build. Kept as "-pro" so existing caches stay valid. */
export function getBinaryDir(version: string): string {
  return path.join(getCacheDir(), `chromium-${version}-pro`);
}

export function getBinaryPath(version: string): string {
  const binaryDir = getBinaryDir(version);
  if (process.platform === "darwin") {
    return path.join(binaryDir, "Chromium.app", "Contents", "MacOS", "Chromium");
  }
  if (process.platform === "win32") {
    return path.join(binaryDir, "chrome.exe");
  }
  return path.join(binaryDir, "chrome");
}

// ---------------------------------------------------------------------------
// Download URL
// ---------------------------------------------------------------------------
export const DOWNLOAD_BASE_URL = "https://cloakbrowser.dev";

export function getArchiveExt(): string {
  return process.platform === "win32" ? ".zip" : ".tar.gz";
}

export function getArchiveName(tag?: string): string {
  return `cloakbrowser-${tag || getPlatformTag()}${getArchiveExt()}`;
}

/**
 * The cached build the channel's marker names, or null when nothing usable is
 * cached (callers then resolve the latest build from the server).
 */
export function getEffectiveVersion(releaseChannel?: string): string | null {
  const channel = normalizeReleaseChannel(releaseChannel);
  const markerPrefix = channel === "preview"
    ? "latest_pro_version_preview"
    : "latest_pro_version";
  const marker = path.join(getCacheDir(), `${markerPrefix}_${getPlatformTag()}`);
  try {
    const version = fs.readFileSync(marker, "utf-8").trim();
    if (!version) return null;
    // Match launch's proBinaryReady (exists AND executable) so `info` never
    // reports a build that launch would reject.
    fs.accessSync(getBinaryPath(version), fs.constants.X_OK);
    return version;
  } catch {
    return null; // no marker, or its build is missing / not executable
  }
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
export const SEED_MIN = 10000;
export const SEED_MAX = 99999;

export function randomSeed(): number {
  return Math.floor(Math.random() * (SEED_MAX - SEED_MIN + 1)) + SEED_MIN;
}

export function getDefaultStealthArgs(): string[] {
  const seed = randomSeed();
  const isMac = process.platform === "darwin";

  const base = [
    "--no-sandbox",
    `--fingerprint=${seed}`,
  ];

  if (isMac) {
    // macOS: run as native Mac browser — GPU/UA match natively
    return [...base, "--fingerprint-platform=macos"];
  }

  // Linux/Windows: spoof as Windows desktop.
  // Screen and window size come from the real display, not this flag (verified:
  // identical across seeds), so the wrapper must not emulate a viewport on top in
  // headed mode — that would break outerWidth >= innerWidth coherence.
  return [...base, "--fingerprint-platform=windows"];
}
