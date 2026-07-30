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
import { ensureGeoipDb, geoipEnabled, getGeoipDir, resolveProxyGeo } from "./geoip.js";
import { ensureProxyScheme } from "./proxy.js";
import { resolveLicenseKey, validateLicense, getProLatestRelease, getActiveSessionCount, type LicenseInfo } from "./license.js";
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
  info         Environment + binary diagnostics (--quick, --proxy URL, --json)
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
  // --quick skips the optional lookups (server latest version, seat count,
  // GeoIP resolution). It is not fully network-free: the license itself is
  // still validated, behind a 24h cache.
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

/**
 * Best-effort IANA name for the host/container timezone.
 *
 * This is the zone the browser would report if GeoIP resolved nothing, so it is
 * the thing worth comparing against — a UTC container behind a foreign exit IP
 * is the failure this check exists to surface.
 */
function systemTimezone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? null;
  } catch {
    return null;
  }
}

/** Current UTC offset of `zone` in minutes, or null if unresolvable. */
function utcOffsetMinutes(zone: string): number | null {
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: zone,
      timeZoneName: "longOffset",
    }).formatToParts(new Date());
    const name = parts.find((p) => p.type === "timeZoneName")?.value ?? "";
    if (name === "GMT" || name === "UTC") return 0;
    const m = /^(?:GMT|UTC)([+-])(\d{1,2}):?(\d{2})?$/.exec(name);
    if (!m) return null;
    return (m[1] === "-" ? -1 : 1) * (Number(m[2]) * 60 + Number(m[3] ?? 0));
  } catch {
    // RangeError for an unknown zone.
    return null;
  }
}

/**
 * Whether the browser's clock would contradict the exit IP.
 *
 * Compared by current UTC offset rather than by name: IANA aliases
 * (Europe/Kiev vs Europe/Kyiv) would otherwise report a mismatch that no
 * detector would ever see.
 */
export function timezonesDisagree(resolved: string, system: string | null): boolean {
  if (!system || resolved === system) return false;
  const a = utcOffsetMinutes(resolved);
  const b = utcOffsetMinutes(system);
  if (a === null || b === null) return false;
  return a !== b;
}

export interface GeoipDiagnostic {
  db_present: boolean;
  path: string;
  checked: boolean;
  reason?: string;
  via_proxy?: boolean;
  system_timezone?: string | null;
  exit_ip?: string | null;
  timezone?: string | null;
  locale?: string | null;
  mismatch?: boolean;
  error?: string | null;
}

/**
 * Resolve GeoIP for real and report what a launch would actually apply.
 *
 * Presence of the database says nothing about whether resolution works: the
 * egress IP can be unreachable, the lookup can miss, and both paths leave the
 * browser on the container clock while the launch continues. So resolve.
 *
 * Never throws — a diagnostic that dies on the condition it diagnoses is worse
 * than useless, and the missing-dependency error is one of those conditions.
 */
export async function checkGeoip(proxy: string | null): Promise<GeoipDiagnostic> {
  const dbPath = path.join(getGeoipDir(), "GeoLite2-City.mmdb");
  const result: GeoipDiagnostic = {
    db_present: fs.existsSync(dbPath),
    path: dbPath,
    checked: true,
    via_proxy: Boolean(proxy),
    system_timezone: systemTimezone(),
    exit_ip: null,
    timezone: null,
    locale: null,
    mismatch: false,
    error: null,
  };

  // Report the switch rather than resolving past it: if the user turned GeoIP
  // off, "it resolves fine" would be a true statement about something launches
  // are not going to do.
  if (!geoipEnabled(undefined)) {
    result.checked = false;
    result.reason = "disabled by CLOAKBROWSER_GEOIP";
    return result;
  }

  try {
    // force: the user explicitly asked to verify, so a recent-failure cooldown
    // marker must not make the report claim GeoIP is unavailable.
    if ((await ensureGeoipDb(true)) === null) {
      result.error = "GeoIP database unavailable (download failed)";
    }
    result.db_present = fs.existsSync(dbPath);
    // A CLI-supplied proxy may omit the scheme ("host:port"), which the HTTP
    // client rejects outright.
    const proxyUrl = proxy ? ensureProxyScheme(proxy) : null;
    const geo = await resolveProxyGeo(proxyUrl);
    result.exit_ip = geo.exitIp;
    result.timezone = geo.timezone;
    result.locale = geo.locale;
  } catch (err) {
    result.error = (err as Error).message;
    return result;
  }

  if (result.exit_ip === null) {
    result.error = result.error ?? "could not resolve the egress IP";
  } else if (result.timezone === null && result.error === null) {
    result.error = `no timezone for ${result.exit_ip} in the database`;
  }
  if (result.timezone) {
    result.mismatch = timezonesDisagree(result.timezone, result.system_timezone ?? null);
  }
  return result;
}

export async function collectDiagnostics(
  quick: boolean,
  proxy: string | null = null,
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

  // GeoIP — resolved for real, because presence of the database says nothing
  // about whether resolution works. Under --quick, presence only (a ~70 MB
  // first-use download is not something a "quick" flag should trigger).
  if (quick) {
    const dbPath = path.join(getCacheDir(), "geoip", "GeoLite2-City.mmdb");
    diag.geoip = {
      db_present: fs.existsSync(dbPath),
      path: dbPath,
      checked: false,
      reason: "skipped (--quick)",
    };
  } else {
    diag.geoip = await checkGeoip(proxy);
  }

  // Optional peer deps.
  diag.modules = {
    "playwright-core": moduleAvailable("playwright-core"),
    "puppeteer-core": moduleAvailable("puppeteer-core"),
    "mmdb-lib": moduleAvailable("mmdb-lib"),
  };

  return diag;
}

/** Render the GeoIP section: what a launch would actually apply. */
function printGeoip(geoip: GeoipDiagnostic): void {
  if (!geoip.checked) {
    const state = geoip.db_present ? "present" : "not downloaded";
    console.log(`GeoIP DB:  ${state} — ${geoip.reason ?? "not checked"}`);
    return;
  }

  const source = geoip.via_proxy ? "proxy exit" : "this machine";
  if (geoip.error) {
    const system = geoip.system_timezone ?? "the system zone";
    console.log(`GeoIP:     ✗ ${geoip.error}`);
    // This is the shape that goes unnoticed: the launch does not fail, it just
    // keeps the local clock, which is what gets scored.
    console.log(`           → launches will keep the system clock (${system})`);
    if (!geoip.via_proxy) {
      console.log("           → pass --proxy URL to check the timezone your exit IP would give");
    }
    return;
  }

  console.log(`GeoIP:     ✓ ${geoip.exit_ip} (${source})`);
  console.log(`           applies tz ${geoip.timezone}, locale ${geoip.locale}`);
  const system = geoip.system_timezone ?? "unknown";
  console.log(
    geoip.mismatch
      // Expected and good with a proxy: this is GeoIP doing its job.
      ? `System tz: ${system} — differs; GeoIP will correct it`
      : `System tz: ${system} — already matches`,
  );
  if (!geoip.via_proxy) {
    console.log("           → pass --proxy URL to check a proxied launch too");
  }
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
      console.log("Win fonts: unknown (fc-match unavailable)");
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
    const active = (lic.sessions as { active: number | null }).active;
    console.log(
      active === null
        ? "Sessions:  unavailable"
        : `Sessions:  ${active} seat${active === 1 ? "" : "s"} in use`
    );
  }

  printGeoip(diag.geoip);

  console.log("Modules:");
  for (const [label, available] of Object.entries(diag.modules)) {
    console.log(`  ${label}: ${available ? "ok" : "missing"}`);
  }
}

/** Read `--proxy URL` or `--proxy=URL` from argv. */
function parseProxyArg(args: string[]): string | null {
  const idx = args.indexOf("--proxy");
  if (idx !== -1 && idx + 1 < args.length) return args[idx + 1];
  const inline = args.find((a) => a.startsWith("--proxy="));
  return inline ? inline.slice("--proxy=".length) : null;
}

async function cmdInfo(args: string[]): Promise<void> {
  const quick = args.includes("--quick") || args.includes("--no-launch");
  const asJson = args.includes("--json");
  const diag = await collectDiagnostics(quick, parseProxyArg(args));
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
