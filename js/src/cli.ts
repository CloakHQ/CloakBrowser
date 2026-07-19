#!/usr/bin/env node
/**
 * CLI for cloakbrowser — download and manage the stealth Chromium binary.
 *
 * Usage:
 *   npx cloakbrowser install      # Download binary (with progress)
 *   npx cloakbrowser info         # Environment + binary diagnostics
 *   npx cloakbrowser doctor       # Alias for info
 *   npx cloakbrowser update       # Check for and download newer binary
 *   npx cloakbrowser clear-cache  # Remove cached binaries
 */

import { ensureBinary, checkForUpdate, checkForProUpdate, clearCache } from "./download.js";
import {
  getLocalBinaryOverride,
  getCacheDir,
  getPlatformTag,
  getBinaryPath,
  getBinaryDir,
  getEffectiveVersion,
  normalizeRequestedVersion,
  CHROMIUM_VERSION,
} from "./config.js";
import { countFontsPresent, WINDOWS_FONT_TELLS, OFFICE_FONT_TELLS } from "./fonts.js";
import { resolveLicenseKey, validateLicense, getProLatestVersion, getActiveSessionCount, type LicenseInfo } from "./license.js";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const UPGRADE_HINT =
  "→ Try the latest Pro binary (Chromium 150) free for 7 days: https://cloakbrowser.dev";

const USAGE = `Usage: cloakbrowser <command>

Commands:
  install      Download the Chromium binary
  info         Environment + binary diagnostics (--quick, --json)
  doctor       Alias for info
  update       Check for and download a newer binary
  clear-cache  Remove all cached binaries`;

async function cmdInstall(): Promise<void> {
  const binaryPath = await ensureBinary();
  console.log(binaryPath);
}

function moduleAvailable(name: string): boolean {
  try {
    createRequire(import.meta.url).resolve(name);
    return true;
  } catch {
    return false;
  }
}

/** Launch `<binary> --version` to prove it runs. */
function binaryVersion(binaryPath: string): { ok: boolean; version: string; error: string } {
  try {
    const out = execFileSync(binaryPath, ["--version"], {
      encoding: "utf8",
      timeout: 10000,
      killSignal: "SIGKILL",
    });
    return { ok: true, version: out.trim(), error: "" };
  } catch (err) {
    const e = err as { stderr?: Buffer | string; message?: string };
    const stderr = e.stderr ? e.stderr.toString().trim() : "";
    return { ok: false, version: "", error: stderr || e.message || String(err) };
  }
}

/** Linux-only: ldd the binary and return missing .so names. */
function missingSharedLibs(binaryPath: string): string[] {
  if (os.platform() !== "linux") return [];
  let out: string;
  try {
    // -- so a path starting with - isn't read as a flag by ldd
    out = execFileSync("ldd", ["--", binaryPath], {
      encoding: "utf8",
      timeout: 10000,
      killSignal: "SIGKILL",
    });
  } catch (err) {
    // ldd commonly exits non-zero when libraries are missing; execFileSync throws
    // but the listing we need is on err.stdout. Fall back to it rather than drop it.
    const e = err as { stdout?: Buffer | string };
    if (!e.stdout) return [];
    out = e.stdout.toString();
  }
  return out
    .split("\n")
    .filter((l) => l.includes("=> not found"))
    .map((l) => l.split("=>")[0].trim());
}

/** Resolve + validate the license the way ensureBinary does. */
async function resolveLicense(): Promise<{ license: Record<string, unknown>; entitledPro: boolean }> {
  let key = resolveLicenseKey();
  // ensureBinary disables Pro routing when a custom download URL is set, so the
  // diagnostic must report free too (matches download.ts).
  if (process.env.CLOAKBROWSER_DOWNLOAD_URL) key = undefined;
  if (!key) return { license: { tier: "free" }, entitledPro: false };
  try {
    const lic: LicenseInfo | null = await validateLicense(key);
    if (lic === null) return { license: { tier: "unknown", error: "could not validate" }, entitledPro: false };
    if (lic.valid) return { license: { tier: lic.plan, valid: true, expires: lic.expires }, entitledPro: true };
    return { license: { tier: "invalid", valid: false }, entitledPro: false };
  } catch (err) {
    return { license: { tier: "unknown", error: (err as Error).message }, entitledPro: false };
  }
}

/** Describe the binary ensureBinary would actually launch (no download). */
async function effectiveBinary(
  entitledPro: boolean,
  quick = false
): Promise<Record<string, unknown>> {
  const override = getLocalBinaryOverride();
  if (override) {
    return {
      version: null,
      latest_version: null,
      pinned: false,
      tier: "override",
      bundled_version: CHROMIUM_VERSION,
      path: override,
      installed: fs.existsSync(override),
      cache_dir: null,
      override,
    };
  }
  const requested = normalizeRequestedVersion();

  // For a Pro license, surface the server's latest separately from the version
  // that will actually launch, so `info` can never silently diverge from launch
  // (the divergence a customer hit: info showed latest, launch ran a stale cache).
  // --quick keeps `info` fully network-free (skip the server latest lookup).
  let latestVersion: string | null = null;
  if (entitledPro && !quick) {
    latestVersion = await getProLatestVersion();
  }

  let version: string | null;
  if (requested) {
    version = requested;
  } else if (entitledPro) {
    // "Will launch now" is the cached Pro build; if none is cached, the next launch
    // downloads latestVersion. getEffectiveVersion(true) returns null (never free).
    version = getEffectiveVersion(true) ?? latestVersion;
  } else {
    version = getEffectiveVersion(false);
  }
  const binPath = version ? getBinaryPath(version, entitledPro) : null;
  return {
    version,
    latest_version: latestVersion,
    pinned: Boolean(requested),
    tier: entitledPro ? "pro" : "free",
    bundled_version: CHROMIUM_VERSION,
    path: binPath,
    installed: binPath ? fs.existsSync(binPath) : false,
    cache_dir: version ? getBinaryDir(version, entitledPro) : null,
    override: null,
  };
}

export async function collectDiagnostics(quick: boolean): Promise<Record<string, unknown>> {
  const diag: Record<string, any> = {};

  diag.environment = {
    node: process.version,
    os: os.type(),
    arch: os.arch(),
  };

  // Resolve the license up front — it decides which binary actually launches
  // (ensureBinary only uses the Pro binary when a key validates).
  const { license, entitledPro } = await resolveLicense();

  // Live seat count — a Pro-only extra lookup, so gated exactly like the server
  // latest-version check: --quick keeps `info` network-free, and a free tier
  // holds no seats. Never cached (a cached count is a wrong count).
  if (entitledPro && !quick) {
    const key = resolveLicenseKey();
    if (key) {
      license.sessions = { active: await getActiveSessionCount(key) };
    }
  }

  try {
    diag.environment.platform_tag = getPlatformTag();
  } catch (err) {
    diag.environment.platform_tag = `unavailable (${(err as Error).message})`;
  }

  try {
    diag.binary = await effectiveBinary(entitledPro, quick);
  } catch (err) {
    diag.binary = { error: (err as Error).message };
  }

  // Launch test (skipped by --quick or when the binary is not installed).
  const binPath: string | undefined = diag.binary.path;
  const installed: boolean | undefined = diag.binary.installed;
  if (quick) {
    diag.launch = { tested: false, reason: "skipped (--quick)" };
  } else if (!binPath || !(installed || fs.existsSync(binPath))) {
    diag.launch = { tested: false, reason: "binary not installed" };
  } else {
    const { ok, version, error } = binaryVersion(binPath);
    diag.launch = { tested: true, ok, version, error };
    if (!ok) diag.launch.missing_libs = missingSharedLibs(binPath);
  }

  // Windows-font probe — only meaningful on a Linux host spoofing Windows.
  // Omitted entirely off Linux, where it carries no signal.
  if (os.platform() === "linux") {
    // Strict count, not "any one present" — real font installs are atomic
    // (you have the whole pack or none), so report how complete the set is.
    const winN = countFontsPresent(WINDOWS_FONT_TELLS);
    const officeN = countFontsPresent(OFFICE_FONT_TELLS);
    diag.fonts = {
      windows: winN === null ? null : [winN, WINDOWS_FONT_TELLS.length],
      office: officeN === null ? null : [officeN, OFFICE_FONT_TELLS.length],
    };
  }

  diag.license = license;

  // GeoIP DB — presence only, never downloads.
  const dbPath = path.join(getCacheDir(), "geoip", "GeoLite2-City.mmdb");
  diag.geoip = { db_present: fs.existsSync(dbPath), path: dbPath };

  // Optional peer deps.
  diag.modules = {
    "playwright-core": moduleAvailable("playwright-core"),
    "puppeteer-core": moduleAvailable("puppeteer-core"),
    "mmdb-lib": moduleAvailable("mmdb-lib"),
  };

  return diag;
}

function printDiagnostics(diag: Record<string, any>): void {
  const env = diag.environment;
  console.log("CloakBrowser diagnostics");
  console.log(`Node:      ${env.node}`);
  console.log(`OS:        ${env.os} ${env.arch}`);
  console.log(`Platform:  ${env.platform_tag ?? "unknown"}`);

  const binary = diag.binary;
  if (binary.error) {
    console.log(`Binary:    unavailable (${binary.error})`);
  } else {
    if (binary.tier === "override") {
      console.log("Version:   set via CLOAKBROWSER_BINARY_PATH (see Launch line)");
    } else if (binary.latest_version) {
      // Pro: show what launches now AND the server's latest, so the two can't diverge.
      console.log(`Version:   ${binary.version} (${binary.tier}) — will launch`);
      if (binary.latest_version === binary.version) {
        console.log(`Latest:    ${binary.latest_version} (up to date)`);
      } else if (binary.pinned) {
        console.log(
          `Latest:    ${binary.latest_version} (available — pinned; unset CLOAKBROWSER_VERSION to upgrade)`
        );
      } else {
        console.log(`Latest:    ${binary.latest_version} (available — next launch upgrades)`);
      }
    } else if (binary.version === null) {
      // Pro with no cached build and no server answer (e.g. offline).
      console.log(
        `Version:   not downloaded yet (${binary.tier}) — next launch downloads the latest`
      );
    } else {
      console.log(`Version:   ${binary.version} (${binary.tier})`);
    }
    console.log(`Binary:    ${binary.path}`);
    console.log(`Installed: ${binary.installed}`);
    if (binary.cache_dir) console.log(`Cache:     ${binary.cache_dir}`);
    if (binary.override) {
      console.log(`Override:  ${binary.override} (CLOAKBROWSER_BINARY_PATH)`);
    }
  }

  const launch = diag.launch;
  if (!launch.tested) {
    console.log(`Launch:    ${launch.reason}`);
  } else if (launch.ok) {
    console.log(`Launch:    ✓ ${launch.version}`);
  } else {
    console.log(`Launch:    ✗ failed — ${launch.error}`);
    for (const lib of launch.missing_libs ?? []) {
      console.log(`           missing: ${lib}`);
    }
    if ((launch.missing_libs ?? []).length) {
      console.log("           → install the missing system libraries (e.g. apt-get install)");
    }
  }

  if (diag.fonts) {
    const win = diag.fonts.windows;
    if (win === null) {
      console.log("Win fonts: unknown (fc-list unavailable)");
    } else {
      const [n, total] = win;
      const verdict = n === total ? "ok" : n === 0 ? "missing" : "partial";
      console.log(`Win fonts: ${verdict} (${n}/${total})`);
      if (n < total) {
        console.log("           → incomplete Windows font set; copy real Windows fonts (Segoe UI, Calibri, Consolas)");
      }
    }
    const office = diag.fonts.office;
    if (office != null) {
      const [n, total] = office;
      // Office is informational only — no Office pack is a normal Windows
      // persona (~53% of real machines have none), so no install nudge.
      const verdict = n === total ? "ok" : n === 0 ? "absent" : "partial";
      console.log(`Office fonts: ${verdict} (${n}/${total})`);
    }
  }

  const lic = diag.license;
  if (lic.tier === "free") {
    console.log("License:   Free");
    console.log(`           ${UPGRADE_HINT}`);
  } else if (lic.error) {
    console.log(`License:   ${lic.tier} (${lic.error})`);
  } else {
    console.log(`License:   ${lic.tier}`);
  }

  if (lic.sessions) {
    const active = (lic.sessions as { active: number | null }).active;
    console.log(
      active === null
        ? "Sessions:  unavailable"
        : `Sessions:  ${active} seat${active === 1 ? "" : "s"} in use`
    );
  }

  console.log(`GeoIP DB:  ${diag.geoip.db_present ? "present" : "not downloaded (optional)"}`);

  console.log("Modules:");
  for (const [label, available] of Object.entries(diag.modules)) {
    console.log(`  ${label}: ${available ? "ok" : "missing"}`);
  }
}

async function cmdInfo(args: string[]): Promise<void> {
  const quick = args.includes("--quick") || args.includes("--no-launch");
  const asJson = args.includes("--json");
  const diag = await collectDiagnostics(quick);
  if (asJson) {
    console.log(JSON.stringify(diag, null, 2));
  } else {
    printDiagnostics(diag);
  }
}

async function cmdUpdate(): Promise<void> {
  console.error("Checking for updates...");
  // A valid Pro license updates the Pro binary; everyone else updates free.
  const { entitledPro } = await resolveLicense();
  let newVersion: string | null;
  let label: string;
  if (entitledPro) {
    newVersion = await checkForProUpdate(resolveLicenseKey()!);
    label = "Pro Chromium";
  } else {
    newVersion = await checkForUpdate();
    label = "Chromium";
  }
  if (newVersion) {
    console.log(`Updated to ${label} ${newVersion}`);
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
  const rest = process.argv.slice(3);

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
      case "doctor":
        await cmdInfo(rest);
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

// Only run when invoked as the CLI entry point — not when imported by tests.
// import.meta.url and process.argv[1] may each be a symlink (npm/pnpm/npx bin
// shims resolve through node_modules/.bin), and the two need not start equal,
// so realpath BOTH sides before comparing. This is what lets `npx cloakbrowser
// info` (and every other subcommand) actually run instead of exiting 0 with no
// output (#427).
export function isCliEntry(invokedPath: string | undefined, metaUrl: string): boolean {
  if (!invokedPath) {
    return false;
  }
  try {
    const invokedReal = fs.realpathSync(invokedPath);
    const thisReal = fs.realpathSync(fileURLToPath(metaUrl));
    return invokedReal === thisReal;
  } catch {
    // If either path can't be resolved (e.g. a shim that doesn't exist yet),
    // don't auto-run main() — safer to do nothing than to run with a bad path.
    return false;
  }
}

if (isCliEntry(process.argv[1], import.meta.url)) {
  main();
}
