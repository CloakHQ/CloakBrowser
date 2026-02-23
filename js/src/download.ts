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
  getBinaryDir,
  getBinaryPath,
  getDownloadUrl,
  getLocalBinaryOverride,
  getPlatformTag,
  getCacheDir,
} from "./config.js";

const DOWNLOAD_TIMEOUT_MS = 600_000; // 10 minutes

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

  // Check if binary is cached
  const binaryPath = getBinaryPath();
  if (fs.existsSync(binaryPath) && isExecutable(binaryPath)) {
    return binaryPath;
  }

  // Download
  console.log(
    `[cloakbrowser] Stealth Chromium ${CHROMIUM_VERSION} not found. Downloading for ${getPlatformTag()}...`
  );
  await downloadAndExtract();

  if (!fs.existsSync(binaryPath)) {
    throw new Error(
      `Download completed but binary not found at expected path: ${binaryPath}. ` +
        `This may indicate a packaging issue. Please report at ` +
        `https://github.com/CloakHQ/cloakbrowser/issues`
    );
  }

  return binaryPath;
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
  const binaryPath = getBinaryPath();
  return {
    version: CHROMIUM_VERSION,
    platform: getPlatformTag(),
    binaryPath,
    installed: fs.existsSync(binaryPath),
    cacheDir: getBinaryDir(),
    downloadUrl: getDownloadUrl(),
  };
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

async function downloadAndExtract(): Promise<void> {
  const url = getDownloadUrl();
  const binaryDir = getBinaryDir();

  // Create cache dir
  fs.mkdirSync(path.dirname(binaryDir), { recursive: true });

  // Download to temp file (atomic — no partial downloads in cache)
  const tmpPath = path.join(
    path.dirname(binaryDir),
    `_download_${Date.now()}.tar.gz`
  );

  try {
    await downloadFile(url, tmpPath);
    await extractArchive(tmpPath, binaryDir);
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
  destDir: string
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
  const binaryPath = getBinaryPath();
  if (fs.existsSync(binaryPath)) {
    fs.chmodSync(binaryPath, 0o755);
    console.log(`[cloakbrowser] Binary ready: ${binaryPath}`);
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
