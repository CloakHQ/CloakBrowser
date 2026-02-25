/**
 * Binary download and cache management for cloakbrowser.
 * Downloads the patched Chromium binary on first use, caches it locally.
 * Mirrors Python cloakbrowser/download.py.
 */

import fs from "node:fs";
import path from "node:path";
import { pipeline } from "node:stream/promises";
import { createWriteStream } from "node:fs";
import { extract as tarExtract } from "tar";

import type { BinaryInfo } from "./types.js";
import {
  CHROMIUM_VERSION,
  GITHUB_API_URL,
  checkPlatformAvailable,
  getBinaryDir,
  getBinaryPath,
  getCacheDir,
  getDownloadUrl,
  getEffectiveVersion,
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
    maybeTriggerUpdateCheck();
    return binaryPath;
  }

  // Fall back to hardcoded version if effective version binary doesn't exist
  if (effective !== CHROMIUM_VERSION) {
    const fallbackPath = getBinaryPath();
    if (fs.existsSync(fallbackPath) && isExecutable(fallbackPath)) {
      maybeTriggerUpdateCheck();
      return fallbackPath;
    }
  }

  // Download hardcoded version
  console.log(
    `[cloakbrowser] Stealth Chromium ${CHROMIUM_VERSION} not found. Downloading for ${getPlatformTag()}...`
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
  if (!latest || !versionNewer(latest, CHROMIUM_VERSION)) return null;

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
// Internal helpers
// ---------------------------------------------------------------------------

async function downloadAndExtract(version?: string): Promise<void> {
  const url = getDownloadUrl(version);
  const binaryDir = getBinaryDir(version);
  const binaryPath = getBinaryPath(version);

  // Create cache dir
  fs.mkdirSync(path.dirname(binaryDir), { recursive: true });

  // Download to temp file (atomic — no partial downloads in cache)
  const tmpPath = path.join(
    path.dirname(binaryDir),
    `_download_${Date.now()}.tar.gz`
  );

  try {
    await downloadFile(url, tmpPath);
    await extractArchive(tmpPath, binaryDir, binaryPath);
  } finally {
    // Clean up temp file
    if (fs.existsSync(tmpPath)) {
      fs.unlinkSync(tmpPath);
    }
  }
}

async function downloadFile(url: string, dest: string): Promise<void> {
  console.log(`[cloakbrowser] Downloading from ${url}`);

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), DOWNLOAD_TIMEOUT_MS);

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

    const fileStream = createWriteStream(dest);
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

    // Wait for file stream to finish
    await new Promise<void>((resolve, reject) => {
      fileStream.end(() => resolve());
      fileStream.on("error", reject);
    });

    const sizeMB = Math.floor(fs.statSync(dest).size / (1024 * 1024));
    console.log(`[cloakbrowser] Download complete: ${sizeMB} MB`);
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

  // Extract with tar — the 'tar' package handles symlink/traversal safety
  await tarExtract({
    file: archivePath,
    cwd: destDir,
    // Security: strip leading path components and reject absolute paths
    strip: 0,
    filter: (entryPath: string) => {
      // Reject absolute paths and path traversal
      if (path.isAbsolute(entryPath) || entryPath.includes("..")) {
        console.warn(
          `[cloakbrowser] Skipping suspicious archive entry: ${entryPath}`
        );
        return false;
      }
      return true;
    },
  });

  // Flatten single subdirectory if needed
  flattenSingleSubdir(destDir);

  // Make binary executable
  const bp = binaryPath || getBinaryPath();
  if (fs.existsSync(bp)) {
    fs.chmodSync(bp, 0o755);
    console.log(`[cloakbrowser] Binary ready: ${bp}`);
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

async function getLatestChromiumVersion(): Promise<string | null> {
  try {
    const resp = await fetch(`${GITHUB_API_URL}?per_page=10`, {
      signal: AbortSignal.timeout(10_000),
    });
    if (!resp.ok) return null;
    const releases = (await resp.json()) as Array<{
      tag_name: string;
      draft: boolean;
    }>;
    for (const release of releases) {
      if (release.tag_name.startsWith("chromium-v") && !release.draft) {
        return release.tag_name.replace("chromium-v", "");
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
  const marker = path.join(cacheDir, "latest_version");
  const tmp = `${marker}.tmp`;
  fs.writeFileSync(tmp, version);
  fs.renameSync(tmp, marker);
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

    const latest = await getLatestChromiumVersion();
    if (!latest || !versionNewer(latest, CHROMIUM_VERSION)) return;

    // Already downloaded?
    if (fs.existsSync(getBinaryDir(latest))) {
      writeVersionMarker(latest);
      return;
    }

    console.log(
      `[cloakbrowser] Newer Chromium available: ${latest} (current: ${CHROMIUM_VERSION}). Downloading in background...`
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
  if (!shouldCheckForUpdate()) return;
  // Fire-and-forget — don't await
  checkAndDownloadUpdate().catch(() => {});
}
