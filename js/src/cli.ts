#!/usr/bin/env node
/**
 * CLI for cloakbrowser — download and manage the stealth Chromium binary.
 *
 * Usage:
 *   npx cloakbrowser install      # Download binary (with progress)
 *   npx cloakbrowser info         # Show binary version, path, platform
 *   npx cloakbrowser update       # Check for and download newer binary
 *   npx cloakbrowser clear-cache  # Remove cached binaries
 */

import { ensureBinary, binaryInfo, checkForUpdate, clearCache } from "./download.js";
import { getLocalBinaryOverride, getCacheDir } from "./config.js";
import fs from "node:fs";

const USAGE = `Usage: cloakbrowser <command>

Commands:
  install      Download the Chromium binary
  info         Show binary version, path, and platform
  update       Check for and download a newer binary
  clear-cache  Remove all cached binaries`;

async function cmdInstall(): Promise<void> {
  const binaryPath = await ensureBinary();
  console.log(binaryPath);
}

function cmdInfo(): void {
  const info = binaryInfo();
  const override = getLocalBinaryOverride();

  console.log(`Version:   ${info.version}`);
  console.log(`Platform:  ${info.platform}`);
  console.log(`Binary:    ${info.binaryPath}`);
  console.log(`Installed: ${info.installed}`);
  console.log(`Cache:     ${info.cacheDir}`);
  if (override) {
    console.log(`Override:  ${override} (CLOAKBROWSER_BINARY_PATH)`);
  }
}

async function cmdUpdate(): Promise<void> {
  console.error("Checking for updates...");
  const newVersion = await checkForUpdate();
  if (newVersion) {
    console.log(`Updated to Chromium ${newVersion}`);
  } else {
    console.log("Already up to date.");
  }
}

function cmdClearCache(): void {
  const cacheDir = getCacheDir();
  if (!fs.existsSync(cacheDir)) {
    console.log("No cache to clear.");
    return;
  }
  clearCache();
  console.log("Cache cleared.");
}

async function main(): Promise<void> {
  const command = process.argv[2];

  if (!command || command === "--help" || command === "-h") {
    console.log(USAGE);
    process.exit(command ? 0 : 2);
  }

  try {
    switch (command) {
      case "install":
        await cmdInstall();
        break;
      case "info":
        cmdInfo();
        break;
      case "update":
        await cmdUpdate();
        break;
      case "clear-cache":
        cmdClearCache();
        break;
      default:
        console.error(`Unknown command: ${command}\n`);
        console.log(USAGE);
        process.exit(2);
    }
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    console.error(`Error: ${message}`);
    process.exit(1);
  }
}

main();
