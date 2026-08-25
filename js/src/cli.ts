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
  normalizeReleaseChannel,
  normalizeRequestedVersion,
  versionNewer,
  CHROMIUM_VERSION,
  WRAPPER_VERSION,
} from "./config.js";
import { countFontsPresent, WINDOWS_FONT_TELLS, OFFICE_FONT_TELLS } from "./fonts.js";
import { resolveProxyGeo } from "./geoip.js";
import { resolveLicenseKey, validateLicense, getProLatestRelease, getSessionSeats, type LicenseInfo } from "./license.js";
import { execFileSync, spawn } from "node:child_process";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";
import readline from "node:readline";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const UPGRADE_HINT = "For more than one concurrent session → https://cloakbrowser.dev";
const FREE_LATEST_HINT =
  "Get the latest binary free → run 'cloakbrowser login' or https://cloakbrowser.dev/free";
const FREE_LOGIN_URL = "https://cloakbrowser.dev/api/license/free/github/start";

const USAGE = `Usage: cloakbrowser <command>

Commands:
  login        Save a license key (or get a free key via GitHub)
  logout       Remove the saved license key (revert to free binary)
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

/**
 * Launch `<binary> --version` to prove it runs.
 *
 * Chromium only handles --version on POSIX, so on Windows the switch is ignored
 * and a browser starts instead of printing — the probe then times out and a
 * healthy install looks broken. --no-startup-window makes it exit right away
 * without putting a window on screen; a broken binary still exits non-zero, so
 * the check keeps its meaning. It just reports no version there, as nothing is
 * printed.
 */
function binaryVersion(binaryPath: string): { ok: boolean; version: string; error: string } {
  const argv = ["--version"];
  if (os.platform() === "win32") argv.push("--no-startup-window");
  try {
    const out = execFileSync(binaryPath, argv, {
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
  const requestedChannel = normalizeReleaseChannel();

  // For a Pro license, surface the server's latest separately from the version
  // that will actually launch, so `info` can never silently diverge from launch
  // (the divergence a customer hit: info showed latest, launch ran a stale cache).
  // --quick keeps `info` fully network-free (skip the server latest lookup).
  let latestVersion: string | null = null;
  let resolvedChannel: "stable" | "preview" | null = null;
  let channelFallback = false;
  if (entitledPro && !quick) {
    const latestRelease = await getProLatestRelease(requestedChannel);
    if (latestRelease) {
      latestVersion = latestRelease.version;
      resolvedChannel = latestRelease.resolvedChannel;
      channelFallback = latestRelease.fallback;
    }
  }

  let version: string | null;
  let installedVersion: string | null = null;
  if (requested) {
    version = requested;
  } else if (entitledPro) {
    // Mirror ensureBinary: report what the next launch resolves to, while
    // CLOAKBROWSER_AUTO_UPDATE=false retains an installed channel build.
    installedVersion = getEffectiveVersion(true, requestedChannel);
    const autoUpdate = (process.env.CLOAKBROWSER_AUTO_UPDATE ?? "true").toLowerCase();
    const updatesEnabled = autoUpdate !== "false";
    if (installedVersion && !updatesEnabled) {
      version = installedVersion;
    } else if (latestVersion && (!installedVersion || versionNewer(latestVersion, installedVersion))) {
      version = latestVersion;
    } else {
      version = installedVersion ?? latestVersion;
    }
  } else {
    version = getEffectiveVersion(false);
    installedVersion = version;
  }
  const binPath = version ? getBinaryPath(version, entitledPro) : null;
  return {
    version,
    latest_version: latestVersion,
    requested_channel: requestedChannel,
    resolved_channel: resolvedChannel,
    channel_fallback: channelFallback,
    installed_version: installedVersion,
    pinned: Boolean(requested),
    tier: entitledPro ? "pro" : "free",
    bundled_version: CHROMIUM_VERSION,
    path: binPath,
    installed: binPath ? fs.existsSync(binPath) : false,
    cache_dir: version ? getBinaryDir(version, entitledPro) : null,
    override: null,
  };
}

export async function collectDiagnostics(
  quick: boolean,
  proxy?: string
): Promise<Record<string, unknown>> {
  const diag: Record<string, any> = {};

  diag.environment = {
    wrapper: WRAPPER_VERSION,
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
      const seats = await getSessionSeats(key);
      license.sessions = {
        active: seats.active,
        limit: seats.limit,
        state: seats.state,
        reason: seats.reason,
      };
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

  // Live resolution — only when a proxy is explicitly given. Mirrors launch():
  // resolves the exit IP and, computing tz/locale, caches the DB if absent.
  if (proxy) {
    try {
      const { timezone, locale, exitIp } = await resolveProxyGeo(proxy);
      diag.geoip.resolved = { exit_ip: exitIp, timezone, locale };
    } catch (err) {
      diag.geoip.resolved = { error: (err as Error).message };
    }
  }

  // Optional peer deps.
  diag.modules = {
    "playwright-core": moduleAvailable("playwright-core"),
    "puppeteer-core": moduleAvailable("puppeteer-core"),
    "mmdb-lib": moduleAvailable("mmdb-lib"),
  };

  return diag;
}

interface SeatSection {
  active?: number | null;
  limit?: number | null;
  state?: string;
  reason?: string | null;
}

// Server error codes → the words a customer can act on. Anything unrecognised is
// printed verbatim rather than swallowed, so a new server code still says something.
const SEAT_DENIAL_REASONS: Record<string, string> = {
  invalid_key: "invalid key",
  license_inactive: "license inactive",
  rate_limited: "rate limited",
};

/** Render the seat lookup. Kept identical in the Python and .NET wrappers. */
export function formatSeats(sessions: SeatSection): string {
  const state = sessions.state ?? "ok";
  if (state === "unreachable") return "unavailable (cannot reach cloakbrowser.dev)";
  if (state === "denied") {
    const reason = sessions.reason || "refused";
    return `unavailable (${SEAT_DENIAL_REASONS[reason] ?? reason})`;
  }
  if (state !== "ok" || typeof sessions.active !== "number") {
    // The server is up and the key is fine — it just cannot count right now.
    return "unavailable (server cannot report seats right now)";
  }

  const active = sessions.active;
  if (typeof sessions.limit !== "number") {
    // No cap to show (unlimited, unrecognised plan, or a server predating the
    // field). Fall back to the bare count — never print "N/unknown".
    return `${active} seat${active === 1 ? "" : "s"} in use`;
  }
  return `${active}/${sessions.limit} in use`;
}

function printDiagnostics(diag: Record<string, any>): void {
  const env = diag.environment;
  console.log("CloakBrowser diagnostics");
  console.log(`Wrapper:   ${env.wrapper}`);
  console.log(`Node:      ${env.node}`);
  console.log(`OS:        ${env.os} ${env.arch}`);
  console.log(`Platform:  ${env.platform_tag ?? "unknown"}`);

  const binary = diag.binary;
  if (binary.error) {
    console.log(`Binary:    unavailable (${binary.error})`);
  } else {
    if (binary.tier === "override") {
      console.log("Version:   set via CLOAKBROWSER_BINARY_PATH (see Launch line)");
    } else {
      if (binary.channel_fallback) {
        console.log("Channel:   Preview → Stable fallback");
      } else {
        const channel = binary.resolved_channel ?? binary.requested_channel ?? "stable";
        console.log(`Channel:   ${channel.charAt(0).toUpperCase()}${channel.slice(1)}`);
      }
      if (binary.latest_version) {
      // Pro: show what launches now AND the server's latest, so the two can't diverge.
      console.log(`Version:   ${binary.version} (${binary.tier}) — next launch`);
      if (binary.latest_version === binary.version && binary.installed) {
        console.log(`Latest:    ${binary.latest_version} (up to date)`);
      } else if (binary.latest_version === binary.version) {
        console.log(`Latest:    ${binary.latest_version} (downloads on next launch)`);
      } else if (binary.pinned) {
        console.log(
          `Latest:    ${binary.latest_version} (available — pinned; unset CLOAKBROWSER_VERSION to upgrade)`
        );
      } else {
        console.log(`Latest:    ${binary.latest_version} (server-resolved; installed build retained)`);
      }
      if (binary.installed_version && binary.installed_version !== binary.version) {
        console.log(`Installed: ${binary.installed_version}`);
      }
      } else if (binary.version === null) {
        // Pro with no cached build and no server answer (e.g. offline).
        console.log(
          `Version:   not downloaded yet (${binary.tier}) — next launch downloads the latest`
        );
      } else {
        console.log(`Version:   ${binary.version} (${binary.tier})`);
      }
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
    // Windows prints nothing, so say it ran rather than show an empty version.
    console.log(`Launch:    ✓ ${launch.version || "runs (no version reported on Windows)"}`);
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
  if (lic.tier === "free" && lic.valid) {
    // Validated free-tier key (GitHub login): the latest binary, 1 session.
    console.log("License:   Free (latest binary, 1 concurrent session)");
    console.log(`           ${UPGRADE_HINT}`);
  } else if (lic.tier === "free") {
    // Keyless: running the older free binary — invite the free-latest login.
    console.log("License:   Free (no key)");
    console.log(`           ${FREE_LATEST_HINT}`);
    console.log(`           ${UPGRADE_HINT}`);
  } else if (lic.error) {
    console.log(`License:   ${lic.tier} (${lic.error})`);
  } else {
    console.log(`License:   ${lic.tier}`);
  }

  if (lic.sessions) {
    console.log(`Sessions:  ${formatSeats(lic.sessions as SeatSection)}`);
  }

  const resolved = diag.geoip.resolved;
  let dbLine = diag.geoip.db_present ? "present" : "not downloaded (optional)";
  if (resolved === undefined) {
    dbLine += "  (pass --proxy <url> to resolve exit IP + timezone/locale)";
  }
  console.log(`GeoIP DB:  ${dbLine}`);
  if (resolved !== undefined) {
    if (resolved.error) {
      console.log(`Exit IP:   (could not resolve — ${resolved.error})`);
    } else {
      console.log(`Exit IP:   ${resolved.exit_ip ?? "(unknown)"}`);
      console.log(`Timezone:  ${resolved.timezone ?? "(unknown)"}`);
      console.log(`Locale:    ${resolved.locale ?? "(unknown)"}`);
    }
  }

  console.log("Modules:");
  for (const [label, available] of Object.entries(diag.modules)) {
    console.log(`  ${label}: ${available ? "ok" : "missing"}`);
  }
}

function getFlagValue(args: string[], flag: string): string | undefined {
  const eq = args.find((a) => a.startsWith(`${flag}=`));
  if (eq) return eq.slice(flag.length + 1);
  const i = args.indexOf(flag);
  if (i !== -1 && i + 1 < args.length) return args[i + 1];
  return undefined;
}

async function cmdInfo(args: string[]): Promise<void> {
  const quick = args.includes("--quick") || args.includes("--no-launch");
  const asJson = args.includes("--json");
  const proxy = getFlagValue(args, "--proxy");
  const diag = await collectDiagnostics(quick, proxy);
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

/** Persist a validated key to <cacheDir>/license.key (0600). */
function saveLicenseKey(key: string): void {
  const cacheDir = getCacheDir();
  fs.mkdirSync(cacheDir, { recursive: true });
  const keyFile = path.join(cacheDir, "license.key");
  fs.writeFileSync(keyFile, key.trim() + "\n");
  try {
    fs.chmodSync(keyFile, 0o600);
  } catch {
    // Non-fatal
  }
}

/** Prompt for a single line of input, resolving "" on EOF. */
function promptLine(question: string): Promise<string> {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return new Promise<string>((resolve) => {
    rl.question(question, (answer) => {
      rl.close();
      resolve(answer.trim());
    });
    rl.on("close", () => resolve(""));
  });
}

/** Best-effort open a URL in the platform browser (silent on failure). */
function openUrl(url: string): void {
  try {
    const cmd =
      process.platform === "darwin"
        ? "open"
        : process.platform === "win32"
          ? "start"
          : "xdg-open";
    spawn(cmd, [url], {
      stdio: "ignore",
      detached: true,
      shell: process.platform === "win32",
    }).unref();
  } catch {
    // Non-fatal
  }
}

/** Open the GitHub free-key page and read back the emailed key. */
async function promptFreeGithubLogin(): Promise<string> {
  console.log(`Opening GitHub sign-in: ${FREE_LOGIN_URL}`);
  openUrl(FREE_LOGIN_URL);
  console.log("If your browser did not open, visit the URL above and authorize with GitHub.");
  console.log("We'll email your free CloakBrowser key to your GitHub email.");
  return promptLine("Paste the key from that email here: ");
}

/**
 * Activate any key. `login <key>` saves a pasted key; bare `login` prompts to
 * paste a key or press ENTER to get a free key via GitHub.
 */
async function cmdLogin(rest: string[]): Promise<void> {
  let key = (rest[0] ?? "").trim();

  if (!key) {
    if (!process.stdin.isTTY) {
      console.error(
        "Usage: cloakbrowser login <key>  (or run it interactively for a free key)."
      );
      process.exit(2);
    }
    const entered = await promptLine(
      "Paste your license key, or press ENTER to get a free key via GitHub: "
    );
    key = entered || (await promptFreeGithubLogin());
  }

  if (!key) {
    console.error("No key entered. Nothing saved.");
    process.exit(1);
  }

  const info = await validateLicense(key);
  if (info === null) {
    console.error(
      "Could not reach the license server to verify the key. Check your connection and retry."
    );
    process.exit(1);
  }
  if (!info.valid) {
    console.error("That license key is invalid or expired. Nothing was saved.");
    process.exit(1);
  }

  saveLicenseKey(key);
  if (info.plan === "free") {
    console.log(
      "Saved. Free tier active: latest binary, 1 concurrent session (one browser at a time)."
    );
    console.log("Need to run more at once? See the plans at https://cloakbrowser.dev");
  } else {
    const plan = info.plan.charAt(0).toUpperCase() + info.plan.slice(1);
    console.log(`Saved. ${plan} key active: latest binary, full plan limits.`);
  }
}

/** Remove the saved license key (revert to the free binary). */
function cmdLogout(): void {
  const keyFile = path.join(getCacheDir(), "license.key");
  if (fs.existsSync(keyFile)) {
    try {
      fs.unlinkSync(keyFile);
    } catch (err) {
      console.error(`Could not remove ${keyFile}: ${(err as Error).message}`);
      process.exit(1);
    }
    console.log("Logged out. Removed the saved key; launches revert to the free binary.");
  } else {
    console.log("No saved license key found.");
  }
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
      case "login":
        await cmdLogin(rest);
        break;
      case "logout":
        cmdLogout();
        break;
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
// import.meta.url is resolved through symlinks by Node's ESM loader, but
// process.argv[1] is left exactly as invoked — so realpath both sides before
// comparing, otherwise every symlinked bin (npm/pnpm/npx) fails the check silently.
const invokedPath = process.argv[1];
if (invokedPath && import.meta.url === pathToFileURL(fs.realpathSync(invokedPath)).href) {
  main();
}
