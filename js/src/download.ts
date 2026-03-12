/**
 * Binary download and cache management for cloakbrowser.
 * Downloads the patched Chromium binary on first use, caches it locally.
 * Mirrors Python cloakbrowser/download.py.
 */

import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { pipeline } from "node:stream/promises";
import { createWriteStream } from "node:fs";
import { extract as tarExtract } from "tar";

import type { BinaryInfo } from "./types.js";
import {
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
  versionNewer,
} from "./config.js";

const DOWNLOAD_TIMEOUT_MS = 600_000; // 10 minutes
const UPDATE_CHECK_INTERVAL_MS = 3_600_000; // 1 hour

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Ensure the stealth Chromium binary is available. Download if needed.
 * Returns the path to the chrome executable.
 */
export async function ensureBinary(): Promise<string> {
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

  // Fail fast if no binary available for this platform
  checkPlatformAvailable();

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

/** Return info about the current binary installation. */
export function binaryInfo(): BinaryInfo {
  const effective = getEffectiveVersion();
  const binaryPath = getBinaryPath(effective);
  return {
    version: effective,
    platform: getPlatformTag(),
    binaryPath,
    installed: fs.existsSync(binaryPath),
    cacheDir: getBinaryDir(effective),
    downloadUrl: getDownloadUrl(effective),
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

// ---------------------------------------------------------------------------
// Welcome message (shown once per install)
// ---------------------------------------------------------------------------

function showWelcome(): void {
  const marker = path.join(getCacheDir(), ".welcome_shown");
  if (fs.existsSync(marker)) return;
  console.log();
  console.log("  CloakBrowser — stealth Chromium for automation");
  console.log("  https://github.com/CloakHQ/CloakBrowser");
  console.log();
  console.log("  Issues?  https://github.com/CloakHQ/CloakBrowser/issues");
  console.log("  Star us if CloakBrowser helps your project!");
  console.log();
  try {
    fs.mkdirSync(getCacheDir(), { recursive: true });
    fs.writeFileSync(marker, "");
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

    // Verify checksum before extraction
    if (process.env.CLOAKBROWSER_SKIP_CHECKSUM?.toLowerCase() !== "true") {
      await verifyDownloadChecksum(tmpPath, version);
    }

    await extractArchive(tmpPath, binaryDir, binaryPath);
    showWelcome();
  } finally {
    // Clean up temp file
    if (fs.existsSync(tmpPath)) {
      fs.unlinkSync(tmpPath);
    }
  }
}

async function verifyDownloadChecksum(filePath: string, version?: string): Promise<void> {
  const checksums = await fetchChecksums(version);
  const tarballName = getArchiveName();

  if (!checksums) {
    console.warn("[cloakbrowser] SHA256SUMS not available for this release — skipping checksum verification");
    return;
  }

  const expected = checksums.get(tarballName);
  if (!expected) {
    console.warn(`[cloakbrowser] SHA256SUMS found but no entry for ${tarballName} — skipping verification`);
    return;
  }

  await verifyChecksum(filePath, expected);
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
      continue;
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

async function downloadFile(url: string, dest: string): Promise<void> {
  console.log(`[cloakbrowser] Downloading from ${url}`);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), DOWNLOAD_TIMEOUT_MS);

  // Create file stream early so we can ensure cleanup on error
  const fileStream = createWriteStream(dest);

  try {
    const response = await fetch(url, {
      signal: controller.signal,
      redirect: "follow",
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
    execFileSync("powershell", [
      "-NoProfile", "-Command",
      `Add-Type -AssemblyName System.IO.Compression.FileSystem; ` +
      `[System.IO.Compression.ZipFile]::ExtractToDirectory('${archivePath}', '${destDir}')`,
    ], { timeout: 120_000 });
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
    if (Date.now() - lastCheck < UPDATE_CHECK_INTERVAL_MS) return false;
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
      String(Date.now())
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
