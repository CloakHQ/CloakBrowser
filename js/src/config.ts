/**
 * Stealth configuration and platform detection for cloakbrowser.
 * Mirrors Python cloakbrowser/config.py.
 */

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { resolveLicenseKey } from "./license.js";

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
export const CHROMIUM_VERSION = "146.0.7680.177.5";

export const PLATFORM_CHROMIUM_VERSIONS: Record<string, string> = {
  "linux-x64": "146.0.7680.177.5",
  "linux-arm64": "146.0.7680.177.3",
  "darwin-arm64": "145.0.7632.109.2",
  "darwin-x64": "145.0.7632.109.2",
  "windows-x64": "146.0.7680.177.5",
};

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

// Platforms with pre-built binaries available for download (derived from version map).
const AVAILABLE_PLATFORMS = new Set(Object.keys(PLATFORM_CHROMIUM_VERSIONS));

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

export function getBinaryDir(version?: string, pro = false): string {
  const suffix = pro ? "-pro" : "";
  return path.join(getCacheDir(), `chromium-${version || getChromiumVersion()}${suffix}`);
}

export function getBinaryPath(version?: string, pro = false): string {
  const binaryDir = getBinaryDir(version, pro);
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

export function getEffectiveVersion(pro?: false, releaseChannel?: string): string;
export function getEffectiveVersion(pro: boolean, releaseChannel?: string): string | null;
export function getEffectiveVersion(pro = false, releaseChannel?: string): string | null {
  const base = getChromiumVersion();
  const cacheDir = getCacheDir();

  if (pro) {
    // A valid Pro license must NEVER fall back to the free binary, so there is
    // deliberately no free-version fallback here — return null when no cached Pro
    // binary matches the marker; callers resolve the latest Pro version instead.
    const channel = normalizeReleaseChannel(releaseChannel);
    const markerPrefix = channel === "preview"
      ? "latest_pro_version_preview"
      : "latest_pro_version";
    const marker = path.join(cacheDir, `${markerPrefix}_${getPlatformTag()}`);
    try {
      if (fs.existsSync(marker)) {
        const version = fs.readFileSync(marker, "utf-8").trim();
        if (version) {
          const binary = getBinaryPath(version, true);
          // Match launch's proBinaryReady (exists AND executable) so `info` never
          // reports a build that launch would reject.
          if (fs.existsSync(binary)) {
            try {
              fs.accessSync(binary, fs.constants.X_OK);
              return version;
            } catch {
              // Present but not executable → not launch-ready.
            }
          }
        }
      }
    } catch {
      // Marker unreadable
    }
    return null;
  }

  // Free tier: try platform-scoped marker first, fall back to legacy marker for upgrades from <0.3.0
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
// Headless viewport handling by binary version
// ---------------------------------------------------------------------------
// First Chromium build that reports coherent headless dimensions without an
// emulated viewport. On these binaries the wrapper launches headless with no
// viewport; older binaries need a fixed DEFAULT_VIEWPORT to stay coherent.
// null => not shipped yet; feature off, behavior byte-identical to today.
// TODO: set to the chromium version string that first ships it.
export const HEADLESS_NO_VIEWPORT_MIN_VERSION: string | null = "148.0.7778.215.4";

/**
 * Whether headless can launch without an emulated viewport on the resolved
 * binary. Only binaries at or above HEADLESS_NO_VIEWPORT_MIN_VERSION qualify;
 * older ones keep DEFAULT_VIEWPORT. A local override binary
 * (CLOAKBROWSER_BINARY_PATH) is unknown-version, so stay on the safe path.
 */
export function binarySupportsHeadlessNoViewport(
  licenseKey?: string,
  browserVersion?: string,
  releaseChannel?: string,
): boolean {
  if (HEADLESS_NO_VIEWPORT_MIN_VERSION === null) return false;
  // A declared version (browserVersion arg OR CLOAKBROWSER_VERSION env) wins even
  // under a local override — the caller asserts the version (also how internal builds
  // opt in). Only an override with no declared version stays on the safe path.
  let declared: string | undefined;
  try {
    declared = normalizeRequestedVersion(browserVersion);
  } catch {
    declared = undefined;
  }
  let version: string | null;
  if (declared) {
    version = declared;
  } else if (getLocalBinaryOverride()) {
    return false;
  } else {
    // Full resolution (param > env > ~/.cloakbrowser/license.key) — mirrors Python
    // and .NET; a bare env/param check would miss file-based Pro keys.
    const pro = Boolean(resolveLicenseKey(licenseKey));
    version = getEffectiveVersion(pro, releaseChannel);
  }
  // No cached Pro build resolvable (getEffectiveVersion returned null) → fail safe.
  if (version === null) return false;
  try {
    // Fail safe (feature OFF) on a malformed version — parseVersion yields NaN
    // instead of throwing, so guard explicitly (Python/.NET throw + fail OFF).
    if (parseVersion(version).some(Number.isNaN)) return false;
    return !versionNewer(HEADLESS_NO_VIEWPORT_MIN_VERSION, version);
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// First build whose `--fingerprint-webrtc-ip` accepts a second address for the
// other address family. Below this floor the flag takes a single address only,
// so the wrapper MUST pass one, as it always has.
export const WEBRTC_DUAL_STACK_MIN_VERSION: string | null = "150.0.7871.114.5";

/**
 * Whether the resolved binary understands a two-address WebRTC exit IP.
 * Same resolution rules as binarySupportsHeadlessNoViewport: a declared version
 * wins, an unknown-version local override stays on the safe (IPv4-only) path.
 */
export function binarySupportsDualStackWebrtc(
  licenseKey?: string,
  browserVersion?: string,
  releaseChannel?: string,
): boolean {
  if (WEBRTC_DUAL_STACK_MIN_VERSION === null) return false;
  let declared: string | undefined;
  try {
    declared = normalizeRequestedVersion(browserVersion);
  } catch {
    declared = undefined;
  }
  let version: string | null;
  if (declared) {
    version = declared;
  } else if (getLocalBinaryOverride()) {
    return false;
  } else {
    const pro = Boolean(resolveLicenseKey(licenseKey));
    version = getEffectiveVersion(pro, releaseChannel);
  }
  if (version === null) return false;
  try {
    if (parseVersion(version).some(Number.isNaN)) return false;
    return !versionNewer(WEBRTC_DUAL_STACK_MIN_VERSION, version);
  } catch {
    return false;
  }
}

/**
 * Whether the wrapper may auto-add `--start-maximized`. Gated on the same
 * threshold as the no_viewport shim: only binaries whose headless surface-fix +
 * headed screen-clamp make a maximized window coherent (`outer == screen`).
 * Below it, maximizing headless while the CDP viewport stays at 1280x720 yields
 * `outerWidth < innerWidth` — a bot tell — so the flag must NOT be added. Shares
 * HEADLESS_NO_VIEWPORT_MIN_VERSION; own name so the two can diverge later.
 * Python, JS and .NET mirror this gate.
 */
export function binarySupportsMaximizedWindow(
  licenseKey?: string,
  browserVersion?: string,
  releaseChannel?: string,
): boolean {
  return binarySupportsHeadlessNoViewport(licenseKey, browserVersion, releaseChannel);
}

// ---------------------------------------------------------------------------
// Inline HTTP proxy authentication by binary version
// ---------------------------------------------------------------------------
// First Chromium build, per platform, whose binary can take inline HTTP proxy
// credentials (Chromium-native `--proxy-server=http://user:pass@host`). Below
// the floor the wrapper MUST route credentialed HTTP/HTTPS proxies through
// Playwright's proxy dict / page.authenticate — an older binary treats the
// `user:pass@` authority as an invalid proxy host and drops proxy auth (#182).
// A single global threshold can't model this: the capability landed in
// different build lineages at different points (linux-x64/windows-x64 at
// 146.0.7680.177.5, but the free macOS 145.x and linux-arm64 146.0.7680.177.3
// floors predate it, qualifying only once they resolve to a Pro/newer 148+
// build). Platforms absent from this map are treated as never-inline.
export const HTTP_PROXY_INLINE_AUTH_MIN_VERSION: Record<string, string> = {
  "linux-x64": "146.0.7680.177.5",
  "windows-x64": "146.0.7680.177.5",
  "linux-arm64": "148.0.7778.215.3",
  "darwin-arm64": "148.0.7778.215.3",
  "darwin-x64": "148.0.7778.215.3",
};

/**
 * Whether the resolved binary accepts inline HTTP proxy credentials. The
 * capability is a function of the binary version; `licenseKey` only resolves
 * which version launches (Pro build vs free default), exactly like
 * binarySupportsHeadlessNoViewport. A declared pin wins, else a valid Pro
 * license resolves to the Pro build (which ships the patch), else the free
 * per-platform default — then it compares to this platform's floor. Below the
 * floor, credentialed HTTP proxies fall back to Playwright's proxy dict. A
 * local override with no declared version is unknown-version, so fail safe.
 * Python, JS and .NET mirror this gate.
 */
export function binarySupportsHttpProxyInlineAuth(
  licenseKey?: string,
  browserVersion?: string,
  releaseChannel?: string,
): boolean {
  let tag: string;
  try {
    tag = getPlatformTag();
  } catch {
    return false;
  }
  const floor = HTTP_PROXY_INLINE_AUTH_MIN_VERSION[tag];
  if (!floor) return false;
  let declared: string | undefined;
  try {
    declared = normalizeRequestedVersion(browserVersion);
  } catch {
    declared = undefined;
  }
  let version: string | null;
  if (declared) {
    version = declared;
  } else if (getLocalBinaryOverride()) {
    return false;
  } else {
    const pro = Boolean(resolveLicenseKey(licenseKey));
    version = getEffectiveVersion(pro, releaseChannel);
  }
  if (version === null) return false;
  try {
    if (parseVersion(version).some(Number.isNaN)) return false;
    return !versionNewer(floor, version);
  } catch {
    return false;
  }
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
// Default viewport — used for HEADLESS only (headed launches use no viewport so
// the page tracks the real window). Headless has no window chrome, so a fixed
// viewport stays coherent (outer == inner) and gives deterministic dimensions.
// Models a maximized Chrome on 1080p Windows: screen=1920x1080,
// innerHeight=947 (minus ~85px Chrome UI: tabs + address bar + bookmarks).
export const DEFAULT_VIEWPORT = { width: 1920, height: 947 };

export function getDefaultStealthArgs(): string[] {
  const seed = Math.floor(Math.random() * 90000) + 10000; // 10000-99999
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
