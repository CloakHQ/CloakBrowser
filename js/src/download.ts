/**
 * Binary download and cache management for cloakbrowser.
 * Downloads the patched Chromium binary on first use, caches it locally.
 * Mirrors Python cloakbrowser/download.py.
 */

import { execFileSync } from "node:child_process";
import { createHash, createPublicKey, verify as cryptoVerify } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { createWriteStream } from "node:fs";
import { extract as tarExtract } from "tar";

import type { BinaryInfo } from "./types.js";
import {
  BINARY_SIGNING_PUBKEYS,
  CHROMIUM_VERSION,
  DOWNLOAD_BASE_URL,
  GITHUB_API_URL,
  GITHUB_DOWNLOAD_BASE_URL,
  WRAPPER_VERSION,
  checkPlatformAvailable,
  getArchiveExt,
  getArchiveName,
  getBinaryDir,
  getBinaryPath,
  getCacheDir,
  getChromiumVersion,
  getDownloadUrl,
  getEffectiveVersion,
  getFallbackDownloadUrl,
  getLocalBinaryOverride,
  getPlatformTag,
  normalizeRequestedVersion,
  versionNewer,
} from "./config.js";
import { resolveLicenseKey, validateLicense, getProLatestVersion } from "./license.js";

const DOWNLOAD_TIMEOUT_MS = 600_000; // 10 minutes
// Seconds, matching the Python/.NET `.last_update_check` marker format so the
// three wrappers share one cache dir without corrupting each other's rate limit.
const UPDATE_CHECK_INTERVAL_SEC = 3600; // 1 hour
// Free-tier welcome banner re-show interval (3 days, in seconds). Free users see
// the Pro upsell again after this gap; Pro users see it only once (see showWelcome).
// Seconds (not ms) so the shared marker is consistent with the Python/.NET wrappers.
// @internal Exported for testing only.
export const WELCOME_FREE_INTERVAL_SEC = 3 * 24 * 60 * 60;
// Pro Chromium major shown in the welcome banner. Bump at each Pro major release
// (no local constant to derive it from — the live Pro version comes from the
// network, which we don't call just to print a banner). Mirrors download.py.
const PRO_MAJOR = "150";

/**
 * A downloaded binary could not be authenticated (bad/missing signature,
 * version mismatch, or checksum failure). Distinct from transient
 * download/network errors: a verification failure is a tampering signal and
 * MUST surface, never silently fall back to another binary. The Pro routing in
 * ensureBinary re-throws this rather than downgrading to the free tier.
 */
export class BinaryVerificationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "BinaryVerificationError";
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Ensure the stealth Chromium binary is available. Download if needed.
 * Returns the path to the chrome executable.
 */
export async function ensureBinary(licenseKey?: string, browserVersion?: string): Promise<string> {
  // Check for local override
  const localOverride = getLocalBinaryOverride();
  if (localOverride) {
    if (!fs.existsSync(localOverride)) {
      throw new Error(
        `CLOAKBROWSER_BINARY_PATH set to '${localOverride}' but file does not exist`
      );
    }
    console.log(`[cloakbrowser] Using local binary override: ${localOverride}`);
    return localOverride;
  }

  const requestedVersion = normalizeRequestedVersion(browserVersion);

  // Pro license key check (custom download URL overrides Pro path)
  const key = resolveLicenseKey(licenseKey);
  const effectiveKey = process.env.CLOAKBROWSER_DOWNLOAD_URL ? undefined : key;
  if (effectiveKey) {
    const info = await validateLicense(effectiveKey);
    if (info?.valid) {
      // A valid license is entitled to Pro, so Pro failures surface loudly
      // rather than silently substituting the older free binary. (A blip during
      // a routine update never reaches here: ensureProBinary returns the cached
      // Pro binary and updates in the background.)
      try {
        return await ensureProBinary(effectiveKey, requestedVersion);
      } catch (e) {
        // Authenticity could not be confirmed — surface verbatim.
        if (e instanceof BinaryVerificationError) throw e;
        // Transient failure with no cached Pro binary to use — surface a clear
        // error rather than silently downloading the free binary.
        throw new Error(
          `Pro binary unavailable: ${e}. Your license is valid but the Pro ` +
            `binary could not be downloaded right now. Retry in a moment. To use ` +
            `the free binary instead, unset CLOAKBROWSER_LICENSE_KEY.`,
          { cause: e }
        );
      }
    } else if (info) {
      console.log(`[cloakbrowser] License validation failed (plan=${info.plan}), using free tier`);
    } else {
      console.log("[cloakbrowser] License validation unavailable, using free tier");
    }
  }

  // Fail fast if no binary available for this platform
  checkPlatformAvailable();

  if (requestedVersion) {
    const binaryPath = getBinaryPath(requestedVersion);
    if (fs.existsSync(binaryPath) && isExecutable(binaryPath)) {
      showWelcome();
      return binaryPath;
    }

    console.log(
      `[cloakbrowser] Stealth Chromium ${requestedVersion} not found. Downloading for ${getPlatformTag()}...`
    );
    await downloadAndExtract(requestedVersion);

    if (!fs.existsSync(binaryPath) || !isExecutable(binaryPath)) {
      throw new Error(
        `Pinned download completed but binary not found at expected path: ${binaryPath}. ` +
          `This may indicate a packaging issue. Please report at ` +
          `https://github.com/CloakHQ/cloakbrowser/issues`
      );
    }
    showWelcome();
    return binaryPath;
  }

  // Check for auto-updated version first, then fall back to hardcoded
  const effective = getEffectiveVersion();
  const binaryPath = getBinaryPath(effective);

  if (fs.existsSync(binaryPath) && isExecutable(binaryPath)) {
    showWelcome();
    maybeTriggerUpdateCheck();
    return binaryPath;
  }

  // Fall back to platform's hardcoded version if effective version binary doesn't exist
  const platformVersion = getChromiumVersion();
  if (effective !== platformVersion) {
    const fallbackPath = getBinaryPath();
    if (fs.existsSync(fallbackPath) && isExecutable(fallbackPath)) {
      maybeTriggerUpdateCheck();
      return fallbackPath;
    }
  }

  // Download platform's hardcoded version
  console.log(
    `[cloakbrowser] Stealth Chromium ${platformVersion} not found. Downloading for ${getPlatformTag()}...`
  );
  await downloadAndExtract();

  const downloadedPath = getBinaryPath();
  if (!fs.existsSync(downloadedPath)) {
    throw new Error(
      `Download completed but binary not found at expected path: ${downloadedPath}. ` +
      `This may indicate a packaging issue. Please report at ` +
      `https://github.com/CloakHQ/cloakbrowser/issues`
    );
  }

  maybeTriggerUpdateCheck();
  return downloadedPath;
}

/** Remove all cached binaries. Forces re-download on next launch. */
export function clearCache(): void {
  const cacheDir = getCacheDir();
  if (fs.existsSync(cacheDir)) {
    fs.rmSync(cacheDir, { recursive: true, force: true });
    console.log(`[cloakbrowser] Cache cleared: ${cacheDir}`);
  }
}

/**
 * Return info about the current binary installation.
 *
 * tier reflects what is actually installed on disk, not merely whether a license
 * is cached — a cached license with no Pro binary downloaded yet is still
 * effectively running the free binary, and the active key may differ from the
 * cached one.
 */
export function binaryInfo(browserVersion?: string): BinaryInfo {
  // browserVersion (or CLOAKBROWSER_VERSION) pins the reported version so the
  // info matches what a pinned launch actually runs, instead of latest.
  const requested = normalizeRequestedVersion(browserVersion);
  // Prefer Pro only if a Pro binary actually exists on disk. getEffectiveVersion
  // returns null for Pro when nothing is cached (it never falls back to free).
  const proVersion = requested ?? getEffectiveVersion(true);
  const isPro = proBinaryReady(proVersion);

  const effective = isPro ? proVersion : (requested ?? getEffectiveVersion(false));
  const binaryPath = isPro ? getBinaryPath(proVersion, true) : getBinaryPath(effective, false);
  return {
    version: effective,
    bundledVersion: CHROMIUM_VERSION,
    tier: isPro ? "pro" : "free",
    platform: getPlatformTag(),
    binaryPath,
    installed: fs.existsSync(binaryPath),
    cacheDir: getBinaryDir(effective, isPro),
    downloadUrl: isPro ? `${DOWNLOAD_BASE_URL}/api/download/latest` : getDownloadUrl(effective),
  };
}

/** Manually check for a newer Chromium version. Returns new version or null. */
export async function checkForUpdate(): Promise<string | null> {
  const latest = await getLatestChromiumVersion();
  if (!latest || !versionNewer(latest, getChromiumVersion())) return null;

  const binaryDir = getBinaryDir(latest);
  if (fs.existsSync(binaryDir)) {
    writeVersionMarker(latest);
    return latest;
  }

  console.log(`[cloakbrowser] Downloading Chromium ${latest}...`);
  await downloadAndExtract(latest);
  writeVersionMarker(latest);
  return latest;
}

/**
 * Move a Pro install to the server's latest stable. Blocks until complete.
 * Returns the new version when a newer Pro build is downloaded or an
 * already-cached newer build is activated, else null (already up to date or the
 * server could not be reached). Requires a valid Pro license key.
 */
export async function checkForProUpdate(licenseKey: string): Promise<string | null> {
  const latest = await getProLatestVersion();
  if (!latest) return null;

  const effective = getEffectiveVersion(true);
  if (effective && !versionNewer(latest, effective) && proBinaryReady(effective)) {
    // Already on the latest cached Pro build.
    return null;
  }

  if (!proBinaryReady(latest)) {
    console.log(`[cloakbrowser] Downloading Pro Chromium ${latest}...`);
    await downloadProBinary(latest, licenseKey);
    if (!fs.existsSync(getBinaryPath(latest, true))) {
      throw new Error(
        `Pro download completed but binary not found at: ${getBinaryPath(latest, true)}`
      );
    }
  }

  writeProVersionMarker(latest);
  return latest;
}

// ---------------------------------------------------------------------------
// Welcome message (shown once per install)
// ---------------------------------------------------------------------------

/**
 * Whether the welcome banner should be shown now. Pro: once ever (only when
 * the marker is absent). Free: re-show when the marker is absent or its
 * timestamp is older than WELCOME_FREE_INTERVAL_MS. Unreadable or legacy empty
 * markers count as stale (due).
 *
 * @internal Exported for testing only.
 */
export function welcomeDue(marker: string, pro: boolean): boolean {
  if (!fs.existsSync(marker)) return true;
  if (pro) return false;
  try {
    const last = parseInt(fs.readFileSync(marker, "utf8").trim(), 10);
    if (Number.isNaN(last)) return true;
    return Math.floor(Date.now() / 1000) - last >= WELCOME_FREE_INTERVAL_SEC;
  } catch {
    return true;
  }
}

function showWelcome(pro = false): void {
  const marker = path.join(getCacheDir(), ".welcome_shown");
  if (!welcomeDue(marker, pro)) return;
  console.error();
  console.error("  CloakBrowser — stealth Chromium for automation");
  console.error("  https://github.com/CloakHQ/CloakBrowser");
  console.error();
  if (pro) {
    console.error(
      `  CloakBrowser Pro active (v${PRO_MAJOR}) — latest binary, newest patches.`,
    );
    console.error("  Pro support → support@cloakbrowser.dev");
  } else {
    const freeMajor = CHROMIUM_VERSION.split(".")[0];
    console.error(
      `  Running free tier (v${freeMajor}). ` +
        `Pro = latest binary (v${PRO_MAJOR}) + newest anti-bot patches.`,
    );
    console.error("  Try Pro free for 7 days → https://cloakbrowser.dev");
  }
  console.error("  Star us if CloakBrowser helps your project!");
  console.error();
  try {
    fs.mkdirSync(getCacheDir(), { recursive: true });
    fs.writeFileSync(marker, String(Math.floor(Date.now() / 1000)));
  } catch {
    // Non-fatal
  }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

async function downloadAndExtract(version?: string): Promise<void> {
  const primaryUrl = getDownloadUrl(version);
  const fallbackUrl = getFallbackDownloadUrl(version);
  const binaryDir = getBinaryDir(version);
  const binaryPath = getBinaryPath(version);

  // Create cache dir
  fs.mkdirSync(path.dirname(binaryDir), { recursive: true });

  // Download to temp file (atomic — no partial downloads in cache)
  const tmpPath = path.join(
    path.dirname(binaryDir),
    `_download_${Date.now()}${getArchiveExt()}`
  );

  try {
    // Try primary server, fall back to GitHub Releases (skip fallback if custom URL)
    try {
      await downloadFile(primaryUrl, tmpPath);
    } catch (primaryErr) {
      if (process.env.CLOAKBROWSER_DOWNLOAD_URL) {
        throw primaryErr;
      }
      console.warn(
        `[cloakbrowser] Primary download failed (${primaryErr instanceof Error ? primaryErr.message : primaryErr}), trying GitHub Releases...`
      );
      await downloadFile(fallbackUrl, tmpPath);
    }

    // Verify the download before extraction. On the official path this is a
    // mandatory, non-bypassable Ed25519 signature check (see
    // verifyDownloadChecksum); the skip flag only applies to custom
    // self-hosted CLOAKBROWSER_DOWNLOAD_URL setups.
    await verifyDownloadChecksum(tmpPath, version);

    await extractArchive(tmpPath, binaryDir, binaryPath);
    showWelcome();
  } finally {
    // Clean up temp file
    if (fs.existsSync(tmpPath)) {
      fs.unlinkSync(tmpPath);
    }
  }
}

/** @internal Exported for testing only. */
export async function verifyDownloadChecksum(filePath: string, version?: string): Promise<void> {
  const tarballName = getArchiveName();

  if (process.env.CLOAKBROWSER_DOWNLOAD_URL) {
    // Self-hosted mirror: the pinned signature keys do not apply to a
    // third-party server. Preserve the legacy same-origin checksum behavior,
    // skippable via CLOAKBROWSER_SKIP_CHECKSUM.
    if (process.env.CLOAKBROWSER_SKIP_CHECKSUM?.toLowerCase() === "true") {
      console.warn(
        "[cloakbrowser] CLOAKBROWSER_SKIP_CHECKSUM set — skipping verification for custom download URL"
      );
      return;
    }
    const checksums = await fetchChecksums(version);
    if (!checksums) {
      console.warn(
        "[cloakbrowser] SHA256SUMS not available from custom URL — skipping checksum verification"
      );
      return;
    }
    const expectedCustom = checksums.get(tarballName);
    if (!expectedCustom) {
      console.warn(
        `[cloakbrowser] SHA256SUMS found but no entry for ${tarballName} — skipping verification`
      );
      return;
    }
    await verifyChecksum(filePath, expectedCustom);
    return;
  }

  // Official path: signature is the trust root and is non-bypassable.
  const manifest = await fetchSignedManifest(version);
  if (!manifest) {
    throw new Error(
      "Could not fetch a signed SHA256SUMS (SHA256SUMS + SHA256SUMS.sig) for " +
        "this release — refusing to use an unverified binary. " +
        "Retry, or report at https://github.com/CloakHQ/cloakbrowser/issues"
    );
  }
  const { manifestBytes, sigBytes } = manifest;
  verifySignature(manifestBytes, sigBytes);
  const manifestText = new TextDecoder().decode(manifestBytes);

  // Version binding: the signed manifest must declare the version we asked for.
  // The signature proves "we made this manifest", not "this is the version you
  // requested" — without this check a mirror could serve a genuinely-signed
  // older release in place of the requested one (forced downgrade).
  const requested = version || getChromiumVersion();
  const declared = parseManifestVersion(manifestText);
  if (declared !== requested) {
    throw new Error(
      `Version mismatch in signed SHA256SUMS: requested ${requested}, ` +
        `manifest declares ${declared ?? "none"}. Refusing (possible downgrade).`
    );
  }

  const checksums = parseChecksums(manifestText);
  const expected = checksums.get(tarballName);
  if (!expected) {
    throw new Error(
      `Signature-verified SHA256SUMS has no entry for ${tarballName} — ` +
        `cannot confirm binary integrity.`
    );
  }
  await verifyChecksum(filePath, expected);
}

/**
 * Read the 'version=<v>' line from a signed manifest. null if absent.
 * The line has no internal whitespace so older wrappers' SHA256SUMS parsers
 * ignore it (they only accept '<hash>  <filename>' lines).
 * @internal Exported for testing only.
 */
export function parseManifestVersion(text: string): string | null {
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (line.startsWith("version=")) {
      return line.slice("version=".length).trim();
    }
  }
  return null;
}

/**
 * Fetch (SHA256SUMS, SHA256SUMS.sig) raw bytes for a version, or null.
 * Both files come from the SAME origin so the signature always matches the
 * exact manifest bytes it certifies. Primary origin first, then GitHub mirror.
 * @internal Exported for testing only.
 */
export async function fetchSignedManifest(
  version?: string
): Promise<{ manifestBytes: Uint8Array; sigBytes: Uint8Array } | null> {
  const v = version || getChromiumVersion();
  const bases = [
    `${DOWNLOAD_BASE_URL}/chromium-v${v}`,
    `${GITHUB_DOWNLOAD_BASE_URL}/chromium-v${v}`,
  ];
  for (const base of bases) {
    try {
      const manifestResp = await fetch(`${base}/SHA256SUMS`, {
        redirect: "follow",
        signal: AbortSignal.timeout(10_000),
      });
      if (!manifestResp.ok) continue;
      const sigResp = await fetch(`${base}/SHA256SUMS.sig`, {
        redirect: "follow",
        signal: AbortSignal.timeout(10_000),
      });
      if (!sigResp.ok) continue;
      return {
        manifestBytes: new Uint8Array(await manifestResp.arrayBuffer()),
        sigBytes: new Uint8Array(await sigResp.arrayBuffer()),
      };
    } catch {
      // Try the next manifest origin.
    }
  }
  return null;
}

/**
 * Verify a detached Ed25519 signature over the raw manifest bytes.
 * sigB64Bytes is the (base64-text) content of SHA256SUMS.sig. Tries each pinned
 * key; succeeds if any validates. Throws if malformed or no key validates.
 * @internal Exported for testing only.
 */
export function verifySignature(manifestBytes: Uint8Array, sigB64Bytes: Uint8Array): void {
  // Node's Buffer.from(...,"base64") is lenient — it silently drops invalid
  // characters instead of throwing. Validate by canonical round-trip so a
  // malformed .sig is reported as such (parity with Python's
  // base64.b64decode(validate=True)).
  const sigText = new TextDecoder().decode(sigB64Bytes).trim();
  const signature = Buffer.from(sigText, "base64");
  if (signature.toString("base64") !== sigText) {
    throw new Error("Malformed SHA256SUMS.sig (not valid base64)");
  }

  for (const pubkeyB64 of BINARY_SIGNING_PUBKEYS) {
    let keyObject;
    try {
      // Build an Ed25519 public key from raw 32 bytes via JWK import.
      const x = Buffer.from(pubkeyB64, "base64").toString("base64url");
      keyObject = createPublicKey({
        key: { kty: "OKP", crv: "Ed25519", x },
        format: "jwk",
      });
    } catch {
      // Skip an unparsable pinned key (e.g. the placeholder); another may validate.
      continue;
    }
    try {
      if (cryptoVerify(null, manifestBytes, keyObject, signature)) {
        console.log("[cloakbrowser] SHA256SUMS signature verified: Ed25519 OK");
        return;
      }
    } catch {
      // InvalidSignature, or a malformed/wrong-length signature that makes
      // verify raise something else — either way this key didn't match,
      // so try the next pinned key (and ultimately fail closed below).
    }
  }

  throw new Error(
    "SHA256SUMS signature verification failed — no pinned key validated the " +
      "manifest. The binary's authenticity could not be confirmed. " +
      "Report at https://github.com/CloakHQ/cloakbrowser/issues"
  );
}

/** @internal Exported for testing only. */
export async function fetchChecksums(version?: string): Promise<Map<string, string> | null> {
  const v = version || getChromiumVersion();
  const hasCustomUrl = !!process.env.CLOAKBROWSER_DOWNLOAD_URL;

  // Respect custom URL contract — no GitHub fallback when custom URL is set
  const urls = [`${DOWNLOAD_BASE_URL}/chromium-v${v}/SHA256SUMS`];
  if (!hasCustomUrl) {
    urls.push(`${GITHUB_DOWNLOAD_BASE_URL}/chromium-v${v}/SHA256SUMS`);
  }

  for (const url of urls) {
    try {
      const resp = await fetch(url, {
        redirect: "follow",
        signal: AbortSignal.timeout(10_000),
      });
      if (!resp.ok) continue;
      return parseChecksums(await resp.text());
    } catch {
      // Try the next checksum origin.
    }
  }
  return null;
}

/** @internal Exported for testing only. */
export function parseChecksums(text: string): Map<string, string> {
  const result = new Map<string, string>();
  for (const line of text.trim().split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const match = trimmed.match(/^([a-f0-9]{64})\s+\*?(.+)$/i);
    if (match) {
      result.set(match[2]!, match[1]!.toLowerCase());
    }
  }
  return result;
}

async function verifyChecksum(filePath: string, expectedHash: string): Promise<void> {
  const hash = createHash("sha256");
  const stream = fs.createReadStream(filePath);
  for await (const chunk of stream) {
    hash.update(chunk);
  }
  const actual = hash.digest("hex").toLowerCase();
  if (actual !== expectedHash) {
    throw new Error(
      `Checksum verification failed!\n` +
      `  Expected: ${expectedHash}\n` +
      `  Got:      ${actual}\n` +
      `  File may be corrupted or tampered with. ` +
      `Please retry or report at https://github.com/CloakHQ/cloakbrowser/issues`
    );
  }
  console.log("[cloakbrowser] Checksum verified: SHA-256 OK");
}

async function downloadFile(url: string, dest: string, headers?: Record<string, string>): Promise<void> {
  console.log(`[cloakbrowser] Downloading from ${url}`);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), DOWNLOAD_TIMEOUT_MS);

  // Create file stream early so we can ensure cleanup on error
  const fileStream = createWriteStream(dest);

  try {
    const response = await fetch(url, {
      signal: controller.signal,
      redirect: "follow",
      ...(headers ? { headers } : {}),
    });

    if (!response.ok) {
      throw new Error(`Download failed: HTTP ${response.status} ${response.statusText}`);
    }

    if (!response.body) {
      throw new Error("Download failed: empty response body");
    }

    const total = Number(response.headers.get("content-length") || 0);
    let downloaded = 0;
    let lastLoggedPct = -1;

    const reader = response.body.getReader();

    // Stream chunks to file with progress logging
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      fileStream.write(value);
      downloaded += value.length;

      if (total > 0) {
        const pct = Math.floor((downloaded / total) * 100);
        if (pct >= lastLoggedPct + 10) {
          lastLoggedPct = pct;
          const dlMB = Math.floor(downloaded / (1024 * 1024));
          const totalMB = Math.floor(total / (1024 * 1024));
          console.log(
            `[cloakbrowser] Download progress: ${pct}% (${dlMB}/${totalMB} MB)`
          );
        }
      }
    }

    // Wait for file stream to fully close (not just finish)
    await new Promise<void>((resolve, reject) => {
      fileStream.end();
      fileStream.on("close", () => resolve());
      fileStream.on("error", reject);
    });

    const sizeMB = Math.floor(fs.statSync(dest).size / (1024 * 1024));
    console.log(`[cloakbrowser] Download complete: ${sizeMB} MB`);
  } catch (err) {
    // Ensure file stream is destroyed on error to release the handle
    if (!fileStream.destroyed) {
      await new Promise<void>((resolve) => {
        fileStream.destroy();
        fileStream.on("close", () => resolve());
        // Safety timeout in case close never fires
        setTimeout(resolve, 2000);
      });
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
}


// ---------------------------------------------------------------------------
// Pro binary download
// ---------------------------------------------------------------------------

/** True when a cached, executable Pro binary exists for `version`. */
function proBinaryReady(version: string | null): version is string {
  if (!version) return false;
  const p = getBinaryPath(version, true);
  return fs.existsSync(p) && isExecutable(p);
}

/** Atomically write the latest Pro version marker for this platform. */
function writeProVersionMarker(version: string): void {
  const cacheDir = getCacheDir();
  fs.mkdirSync(cacheDir, { recursive: true });
  const marker = path.join(cacheDir, `latest_pro_version_${getPlatformTag()}`);
  const tmp = `${marker}.tmp`;
  fs.writeFileSync(tmp, version);
  fs.renameSync(tmp, marker);
}

// A valid Pro license NEVER falls back to the free binary. If the latest Pro build
// cannot be resolved or downloaded and no cached Pro binary exists, the error is
// thrown rather than silently launching the free tier.
async function ensureProBinary(
  licenseKey: string,
  requestedVersion?: string
): Promise<string> {
  // Pinned: launch the exact requested version, no server cross-check, no marker
  // write (a rollback pin must not stick future unpinned launches).
  if (requestedVersion) {
    if (proBinaryReady(requestedVersion)) {
      showWelcome(true);
      return getBinaryPath(requestedVersion, true);
    }
    console.log(
      `[cloakbrowser] Downloading Pro Chromium ${requestedVersion} for ${getPlatformTag()}...`
    );
    await downloadProBinary(requestedVersion, licenseKey);
    const p = getBinaryPath(requestedVersion, true);
    if (!fs.existsSync(p)) {
      throw new Error(`Pro download completed but binary not found at: ${p}`);
    }
    showWelcome(true);
    return p;
  }

  // Unpinned: track the server's latest stable.
  const effective = getEffectiveVersion(true);

  // Honor CLOAKBROWSER_AUTO_UPDATE=false the way the free path does: frozen AND a
  // cached Pro build present → keep it, skip the server check. With no cached build
  // we must still fetch one — a valid Pro license never launches the free binary.
  // (The `update` CLI ignores this and always acts.)
  const frozen =
    (process.env.CLOAKBROWSER_AUTO_UPDATE ?? "").toLowerCase() === "false";
  if (frozen && proBinaryReady(effective)) {
    showWelcome(true);
    return getBinaryPath(effective, true);
  }

  // getProLatestVersion() is rate-limited to one network call per hour and returns
  // a cached string in between, so this foreground check stays cheap steady-state.
  const latest = await getProLatestVersion();

  // Prefer the server's latest when it is newer than — or replaces a missing —
  // the cached build. Otherwise stay on the cached Pro binary (fast, offline-ok).
  let version: string | null;
  if (
    latest &&
    (!proBinaryReady(effective) || // also covers effective === null
      versionNewer(latest, effective))
  ) {
    version = latest;
  } else {
    version = effective;
  }

  if (version === null) {
    // Valid Pro license but nothing resolvable (server unreachable AND no cached
    // Pro build). Never downgrade to the free binary — fail loudly.
    throw new Error("Could not determine latest Pro version from server");
  }

  if (proBinaryReady(version)) {
    // Advance the marker if this cached build is newer than what the marker names,
    // so `info` (and a later server-outage launch) reflect the build we actually
    // launch — never a stale marker.
    if (version !== effective) {
      try {
        writeProVersionMarker(version);
      } catch {
        // Non-fatal
      }
    }
    showWelcome(true);
    return getBinaryPath(version, true);
  }

  // `version` (the server latest) needs downloading. On failure, fall back to a
  // cached Pro build if we have one — never the free binary.
  try {
    console.log(
      `[cloakbrowser] Downloading Pro Chromium ${version} for ${getPlatformTag()}...`
    );
    await downloadProBinary(version, licenseKey);
  } catch (err) {
    // A tampering signal must surface verbatim — never mask it behind the
    // cached-Pro fallback, which is only for transient download failures.
    if (err instanceof BinaryVerificationError) throw err;
    if (proBinaryReady(effective)) {
      console.log(
        `[cloakbrowser] Pro update to ${version} failed; launching cached Pro binary ${effective}`
      );
      showWelcome(true);
      return getBinaryPath(effective, true);
    }
    throw err;
  }

  const downloadedPath = getBinaryPath(version, true);
  if (!fs.existsSync(downloadedPath)) {
    throw new Error(
      `Pro download completed but binary not found at: ${downloadedPath}`
    );
  }

  // Advance the marker so future unpinned launches use this build.
  try {
    writeProVersionMarker(version);
  } catch {
    // Non-fatal
  }

  showWelcome(true);
  return downloadedPath;
}

/** @internal Exported for testing only. */
export async function downloadProBinary(version: string, licenseKey: string): Promise<void> {
  // Request the explicit version so the served archive matches the signed
  // manifest verified in verifyProDownload.
  const downloadUrl = `${DOWNLOAD_BASE_URL}/api/download/${version}`;
  const binaryDir = getBinaryDir(version, true);
  const binaryPath = getBinaryPath(version, true);
  const platformTag = getPlatformTag();

  fs.mkdirSync(path.dirname(binaryDir), { recursive: true });

  const tmpPath = path.join(
    path.dirname(binaryDir),
    `_download_${Date.now()}${getArchiveExt()}`
  );

  try {
    await downloadFile(downloadUrl, tmpPath, {
      Authorization: `Bearer ${licenseKey}`,
      "X-Platform": platformTag,
    });

    // Pro binaries come from cloakbrowser.dev — the same origin as free
    // downloads — so the M1 attack the Ed25519 signature defends against
    // applies equally. Verify with the same non-bypassable signature check;
    // CLOAKBROWSER_SKIP_CHECKSUM does NOT bypass it (parity with the official
    // free path).
    await verifyProDownload(tmpPath, version);

    await extractArchive(tmpPath, binaryDir, binaryPath);
  } finally {
    if (fs.existsSync(tmpPath)) {
      fs.unlinkSync(tmpPath);
    }
  }
}

/**
 * Verify a Pro archive with the same non-bypassable Ed25519 signature check as
 * official free downloads. Pro binaries are served from cloakbrowser.dev (same
 * origin as the free tier), so a tampered same-origin SHA256SUMS could
 * otherwise certify a tampered binary (M1, #308). Fetch the Pro SHA256SUMS +
 * detached SHA256SUMS.sig, verify the signature against the pinned keys FIRST,
 * bind the manifest to the requested version, then verify the archive's
 * SHA-256.
 *
 * An invalid signature, checksum, or version mismatch throws
 * BinaryVerificationError (a tampering signal the router surfaces verbatim);
 * CLOAKBROWSER_SKIP_CHECKSUM cannot bypass it. A failed manifest FETCH is
 * transient — nothing was validated — and throws a plain Error. A valid-license
 * user is never silently downgraded to the free binary.
 * @internal Exported for testing only.
 */
export async function verifyProDownload(filePath: string, version: string): Promise<void> {
  const base = `${DOWNLOAD_BASE_URL}/releases/pro/chromium-v${version}`;
  let manifestBytes: Uint8Array;
  let sigBytes: Uint8Array;
  try {
    const manifestResp = await fetch(`${base}/SHA256SUMS`, {
      redirect: "follow",
      signal: AbortSignal.timeout(10_000),
    });
    if (!manifestResp.ok) throw new Error(`HTTP ${manifestResp.status} for SHA256SUMS`);
    const sigResp = await fetch(`${base}/SHA256SUMS.sig`, {
      redirect: "follow",
      signal: AbortSignal.timeout(10_000),
    });
    if (!sigResp.ok) throw new Error(`HTTP ${sigResp.status} for SHA256SUMS.sig`);
    manifestBytes = new Uint8Array(await manifestResp.arrayBuffer());
    sigBytes = new Uint8Array(await sigResp.arrayBuffer());
  } catch (e) {
    // Fetch failure is transient, not tampering — throw a plain Error (the
    // router reports it as "unavailable, retry") rather than a
    // BinaryVerificationError (which it surfaces as a tampering signal).
    throw new Error(`Could not fetch the signed SHA256SUMS for Pro ${version} (${e})`);
  }

  // verifySignature / verifyChecksum throw a plain Error; convert to
  // BinaryVerificationError so the Pro router treats them as tampering signals
  // (re-throw) rather than transient failures (fall back to free).
  try {
    verifySignature(manifestBytes, sigBytes);
  } catch (e) {
    throw new BinaryVerificationError(e instanceof Error ? e.message : String(e));
  }
  const manifestText = new TextDecoder().decode(manifestBytes);

  // Version binding: same forced-downgrade defense as the official path.
  const declared = parseManifestVersion(manifestText);
  if (declared !== version) {
    throw new BinaryVerificationError(
      `Version mismatch in signed Pro SHA256SUMS: requested ${version}, ` +
        `manifest declares ${declared ?? "none"}. Refusing (possible downgrade).`
    );
  }

  const tarballName = getArchiveName();
  const expected = parseChecksums(manifestText).get(tarballName);
  if (!expected) {
    throw new BinaryVerificationError(
      `Signature-verified Pro SHA256SUMS has no entry for ${tarballName} — ` +
        `cannot confirm binary integrity.`
    );
  }
  try {
    await verifyChecksum(filePath, expected);
  } catch (e) {
    throw new BinaryVerificationError(e instanceof Error ? e.message : String(e));
  }
}

async function extractArchive(
  archivePath: string,
  destDir: string,
  binaryPath?: string
): Promise<void> {
  console.log(`[cloakbrowser] Extracting to ${destDir}`);

  // Clean existing dir if partial download existed
  if (fs.existsSync(destDir)) {
    fs.rmSync(destDir, { recursive: true, force: true });
  }
  fs.mkdirSync(destDir, { recursive: true });

  if (archivePath.endsWith(".zip")) {
    await extractZip(archivePath, destDir);
  } else {
    await extractTar(archivePath, destDir);
  }

  // Flatten single subdirectory if needed
  flattenSingleSubdir(destDir);

  // Make binary executable (skip on Windows — no-op / AV lock risk)
  const bp = binaryPath || getBinaryPath();
  if (process.platform !== "win32" && fs.existsSync(bp)) {
    fs.chmodSync(bp, 0o755);
  }

  // macOS: remove quarantine/provenance xattrs to prevent Gatekeeper prompts
  if (process.platform === "darwin") {
    removeQuarantine(destDir);
  }

  if (fs.existsSync(bp)) {
    console.log(`[cloakbrowser] Binary ready: ${bp}`);
  }
}

async function extractTar(archivePath: string, destDir: string): Promise<void> {
  await tarExtract({
    file: archivePath,
    cwd: destDir,
    strip: 0,
    filter: (entryPath: string) => {
      if (path.isAbsolute(entryPath) || entryPath.includes("..")) {
        console.warn(
          `[cloakbrowser] Skipping suspicious archive entry: ${entryPath}`
        );
        return false;
      }
      return true;
    },
  });
}

async function extractZip(archivePath: string, destDir: string): Promise<void> {
  // Brief delay to ensure OS fully releases file handles (Windows)
  await new Promise(resolve => setTimeout(resolve, 500));

  if (process.platform === "win32") {
    // PowerShell 5.1's Expand-Archive uses .NET FileStream which can conflict
    // with recently-closed Node.js file handles. Use ZipFile API directly.
    // Pass paths via env vars (not interpolated into the script) so a quote or
    // other special char in the path can't break out and be parsed as code.
    execFileSync("powershell", [
      "-NoProfile", "-Command",
      `Add-Type -AssemblyName System.IO.Compression.FileSystem; ` +
      `[System.IO.Compression.ZipFile]::ExtractToDirectory($env:CB_ARCHIVE, $env:CB_DEST)`,
    ], {
      timeout: 120_000,
      env: { ...process.env, CB_ARCHIVE: archivePath, CB_DEST: destDir },
    });
  } else {
    execFileSync("unzip", ["-o", archivePath, "-d", destDir], { timeout: 120_000 });
  }
}

/**
 * If extraction created a single subdirectory, move its contents up.
 * Many tarballs wrap files in a top-level directory.
 */
function flattenSingleSubdir(destDir: string): void {
  const entries = fs.readdirSync(destDir);
  if (entries.length === 1) {
    const subdir = path.join(destDir, entries[0]!);
    // Never flatten .app bundles — macOS needs the bundle structure
    if (entries[0]!.endsWith(".app")) return;
    if (fs.statSync(subdir).isDirectory()) {
      const children = fs.readdirSync(subdir);
      for (const child of children) {
        fs.renameSync(
          path.join(subdir, child),
          path.join(destDir, child)
        );
      }
      fs.rmdirSync(subdir);
    }
  }
}

/** Remove macOS quarantine/provenance xattrs so Gatekeeper doesn't block the binary. */
function removeQuarantine(dirPath: string): void {
  try {
    execFileSync("xattr", ["-cr", dirPath], { timeout: 30_000 });
  } catch {
    // Non-fatal — user can manually run: xattr -cr ~/.cloakbrowser/
  }
}

function isExecutable(filePath: string): boolean {
  try {
    fs.accessSync(filePath, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Auto-update
// ---------------------------------------------------------------------------

function shouldCheckForUpdate(): boolean {
  if (process.env.CLOAKBROWSER_AUTO_UPDATE?.toLowerCase() === "false")
    return false;
  if (getLocalBinaryOverride()) return false;
  if (process.env.CLOAKBROWSER_DOWNLOAD_URL) return false;

  const checkFile = path.join(getCacheDir(), ".last_update_check");
  try {
    const lastCheck = Number(fs.readFileSync(checkFile, "utf-8").trim());
    if (Math.floor(Date.now() / 1000) - lastCheck < UPDATE_CHECK_INTERVAL_SEC)
      return false;
  } catch {
    /* file doesn't exist or unreadable */
  }
  return true;
}

/** @internal Exported for testing only. */
export async function getLatestChromiumVersion(): Promise<string | null> {
  try {
    const resp = await fetch(`${GITHUB_API_URL}?per_page=10`, {
      signal: AbortSignal.timeout(10_000),
    });
    if (!resp.ok) return null;
    const releases = (await resp.json()) as Array<{
      tag_name: string;
      draft: boolean;
      assets: Array<{ name: string }>;
    }>;
    const platformTarball = getArchiveName();
    for (const release of releases) {
      if (release.tag_name.startsWith("chromium-v") && !release.draft) {
        const assetNames = new Set(
          (release.assets ?? []).map((a) => a.name)
        );
        if (assetNames.has(platformTarball)) {
          return release.tag_name.replace(/^chromium-v/, "");
        }
      }
    }
    return null;
  } catch {
    return null;
  }
}

function writeVersionMarker(version: string): void {
  const cacheDir = getCacheDir();
  fs.mkdirSync(cacheDir, { recursive: true });
  const marker = path.join(cacheDir, `latest_version_${getPlatformTag()}`);
  const tmp = `${marker}.tmp`;
  fs.writeFileSync(tmp, version);
  fs.renameSync(tmp, marker);
}

let wrapperUpdateChecked = false;

/** @internal Exported for testing only. */
export function resetWrapperUpdateChecked(): void {
  wrapperUpdateChecked = false;
}

/** @internal Exported for testing only. */
export async function checkWrapperUpdate(): Promise<void> {
  if (wrapperUpdateChecked) return;
  wrapperUpdateChecked = true;
  if (process.env.CLOAKBROWSER_AUTO_UPDATE?.toLowerCase() === "false") return;
  if (process.env.CLOAKBROWSER_DOWNLOAD_URL) return;
  try {
    const resp = await fetch("https://registry.npmjs.org/cloakbrowser/latest", {
      signal: AbortSignal.timeout(5_000),
    });
    if (!resp.ok) return;
    const data = (await resp.json()) as { version: string };
    if (data.version && versionNewer(data.version, WRAPPER_VERSION)) {
      console.warn(
        `[cloakbrowser] Update available: ${WRAPPER_VERSION} → ${data.version}. ` +
        `Run: npm install cloakbrowser@latest`
      );
    }
  } catch {
    // Non-fatal — never block binary update check
  }
}

async function checkAndDownloadUpdate(): Promise<void> {
  try {
    // Record check timestamp first (rate limiting)
    const cacheDir = getCacheDir();
    fs.mkdirSync(cacheDir, { recursive: true });
    fs.writeFileSync(
      path.join(cacheDir, ".last_update_check"),
      String(Math.floor(Date.now() / 1000))
    );

    const platformVersion = getChromiumVersion();
    const latest = await getLatestChromiumVersion();
    if (!latest || !versionNewer(latest, platformVersion)) return;

    // Already downloaded?
    if (fs.existsSync(getBinaryDir(latest))) {
      writeVersionMarker(latest);
      return;
    }

    console.log(
      `[cloakbrowser] Newer Chromium available: ${latest} (current: ${platformVersion}). Downloading in background...`
    );
    await downloadAndExtract(latest);
    writeVersionMarker(latest);
    console.log(
      `[cloakbrowser] Background update complete: Chromium ${latest} ready. Will use on next launch.`
    );
  } catch (err) {
    // Background update failed — don't disrupt the user
    if (process.env.DEBUG) {
      console.error("[cloakbrowser] Background update failed:", err);
    }
  }
}

function maybeTriggerUpdateCheck(): void {
  // Wrapper update: once per process, not rate-limited
  if (!wrapperUpdateChecked) {
    checkWrapperUpdate().catch(() => { });
  }

  // Binary update: rate-limited to once per hour
  if (!shouldCheckForUpdate()) return;
  checkAndDownloadUpdate().catch(() => { });
}

