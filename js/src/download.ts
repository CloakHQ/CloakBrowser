/**
 * Binary download and cache management for cloakbrowser.
 * Downloads the patched Chromium binary on first use, caches it locally.
 * Mirrors Python cloakbrowser/download.py.
 */

import { execFileSync, spawn } from "node:child_process";
import { createHash, createPublicKey, randomUUID, verify as cryptoVerify } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { isMainThread } from "node:worker_threads";
import { createWriteStream } from "node:fs";
import { extract as tarExtract } from "tar";

import type { BinaryInfo } from "./types.js";
import {
  BINARY_SIGNING_PUBKEYS,
  DOWNLOAD_BASE_URL,
  WRAPPER_VERSION,
  getArchiveExt,
  getArchiveName,
  getBinaryDir,
  getBinaryPath,
  getCacheDir,
  getEffectiveVersion,
  getLocalBinaryOverride,
  getPlatformTag,
  normalizeReleaseChannel,
  normalizeRequestedVersion,
  versionNewer,
} from "./config.js";
import {
  CloakBrowserLicenseError,
  FreeKeyAlreadyHeld,
  KEY_RE,
  checkClaim,
  claimLink,
  getClaimCode,
  pollClaim,
  resolveLicenseKey,
  saveLicenseKey,
  validateLicense,
  getProLatestVersion,
  getProLatestRelease,
} from "./license.js";

const DOWNLOAD_TIMEOUT_MS = 600_000; // 10 minutes
// How long a background claim poll keeps checking for the key (see claimFreeKey).
const CLAIM_POLL_WINDOW_MS = 600_000;
// Free-key welcome banner re-show interval (1 day, in seconds). Free users see
// the upsell again after this gap; Pro users see it only once (see showWelcome).
// Seconds (not ms) so the shared marker is consistent with the Python/.NET wrappers.
// @internal Exported for testing only.
export const WELCOME_FREE_INTERVAL_SEC = 1 * 24 * 60 * 60;
// Attempts to rename an extraction into place while concurrent callers are
// replacing the same partial install (see extractArchive).
const INSTALL_RENAME_ATTEMPTS = 5;
// Retries for a directory rename that Windows transiently denies (see
// renameDirWithRetry): about 2.5 seconds in total.
const TRANSIENT_RENAME_ATTEMPTS = 10;
const TRANSIENT_RENAME_DELAY_MS = 250;

/**
 * A downloaded binary could not be authenticated (bad/missing signature,
 * version mismatch, or checksum failure). Distinct from transient
 * download/network errors: a verification failure is a tampering signal and
 * MUST surface, never silently fall back to another binary. The routing in
 * ensureBinary re-throws this rather than falling back to a cached build.
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
export async function ensureBinary(
  licenseKey?: string,
  browserVersion?: string,
  releaseChannel?: string,
): Promise<string> {
  // Check for local override
  const localOverride = getLocalBinaryOverride();
  if (localOverride) {
    if (!fs.existsSync(localOverride)) {
      throw new Error(
        `CLOAKBROWSER_BINARY_PATH set to '${localOverride}' but file does not exist`
      );
    }
    console.error(`[cloakbrowser] Using local binary override: ${localOverride}`);
    return localOverride;
  }

  const requestedVersion = normalizeRequestedVersion(browserVersion);

  // No key anywhere (param, env, license.key) -> get a free one first.
  const key = resolveLicenseKey(licenseKey) ?? (await claimFreeKey());
  const info = await validateLicense(key);
  if (info?.valid) {
    maybeTriggerUpdateCheck();
    // A free key always gets the latest build. Drop any version pin: the server
    // force-serves latest to free keys, so fetching a pinned version's signed
    // manifest would mismatch the served bytes and fail checksum verification.
    // Paid keys keep pinning/rollback.
    const pinned = info.plan === "free" ? undefined : requestedVersion;
    // (A blip during a routine update never reaches the error below:
    // ensureProBinary returns the cached build and retries next launch.)
    try {
      return await ensureProBinary(key, pinned, info.plan, releaseChannel);
    } catch (e) {
      // Authenticity could not be confirmed — surface verbatim.
      if (e instanceof BinaryVerificationError) throw e;
      throw new Error(
        `CloakBrowser binary unavailable: ${e}. Your license is valid but the ` +
          `binary could not be downloaded right now. Retry in a moment.`,
        { cause: e }
      );
    }
  }
  if (info) {
    throw new CloakBrowserLicenseError(
      `CloakBrowser: license key is invalid or expired (plan=${info.plan}). ` +
        `Check CLOAKBROWSER_LICENSE_KEY or ~/.cloakbrowser/license.key, or get ` +
        `a free key with: cloakbrowser login`,
    );
  }
  throw new CloakBrowserLicenseError(
    "CloakBrowser: license could not be validated (server unreachable and " +
      "no cached validation). Retry in a moment.",
  );
}

// ---------------------------------------------------------------------------
// No key: the free-key menu and claim flow (mirrors Python download.py)
// ---------------------------------------------------------------------------

export const HAS_KEY_MSG =
  "This email already has a free key. It's in the email we sent when you " +
  "first got it (search your mail for CloakBrowser).";

/** stdin closed before the menu got an answer (EOF). */
export class PromptClosedError extends Error {
  constructor() {
    super("stdin closed");
    this.name = "PromptClosedError";
  }
}

/** Cosmetic stderr output that can never break a launch. */
function emit(text: string): void {
  try {
    process.stderr.write(text);
  } catch {
    // A banner or prompt line must never be able to kill a launch.
  }
}

/** A person is at this terminal (and we're on the main thread). */
export function canPrompt(): boolean {
  return isMainThread && Boolean(process.stdin.isTTY) && Boolean(process.stderr.isTTY);
}

/** Ask one line on stderr (a script's stdout may be its data). */
function ask(question: string): Promise<string> {
  const rl = readline.createInterface({ input: process.stdin, output: process.stderr });
  return new Promise<string>((resolve, reject) => {
    let answered = false;
    // Closed without an answer (EOF). close() also pauses stdin, so the
    // interface never keeps the process alive.
    rl.on("close", () => {
      if (!answered) reject(new PromptClosedError());
    });
    // Ctrl+C means stop, like it does everywhere else. Without this listener
    // readline just closes, which would read as EOF and print the link + error.
    rl.on("SIGINT", () => {
      emit("\n");
      process.exit(130);
    });
    rl.question(question, (answer) => {
      answered = true;
      rl.close();
      resolve(answer.trim());
    });
  });
}

/** Best-effort open a URL in the platform browser. */
function openUrl(url: string): boolean {
  try {
    // Windows: `start` is a cmd builtin; call cmd directly (no shell: true, which
    // Node 24 deprecates with args). The empty "" is start's window title.
    const [cmd, args]: [string, string[]] =
      process.platform === "darwin" ? ["open", [url]]
      : process.platform === "win32" ? ["cmd", ["/c", "start", "", url]]
      : ["xdg-open", [url]];
    const child = spawn(cmd, args, { stdio: "ignore", detached: true, windowsHide: true });
    child.on("error", () => { }); // no opener installed: the printed link is enough
    child.unref();
    return true;
  } catch {
    return false;
  }
}

function emitWelcome(): void {
  emit("\n  Welcome to CloakBrowser - stealth Chromium for automation\n");
  emit("  https://github.com/CloakHQ/CloakBrowser\n\n");
  emit("  CloakBrowser needs a license key.\n\n");
}

/**
 * Terminal menu shared by a no-key launch and `cloakbrowser login`: get a free
 * key by email or paste one. Returns a valid key, already saved.
 * Throws PromptClosedError if stdin closes.
 */
export async function promptLicenseKey(): Promise<string> {
  emitWelcome();
  emit("    1) Get a free key (by email: the latest build, 1 concurrent session)\n");
  emit("    2) Paste a key I already have\n\n");
  for (;;) {
    const choice = await ask("  Choose 1 or 2 [1]: ");
    if (choice === "" || choice === "1") {
      const key = await getFreeKey();
      if (key) return key;
      emit(`\n  ${HAS_KEY_MSG}\n`);
    } else if (choice !== "2") {
      emit("  Please type 1 or 2.\n");
      continue;
    }
    const key = await pasteKey();
    if (key) return key;
  }
}

/** Ask until a valid key is pasted (saved, returned) or the answer is empty. */
async function pasteKey(): Promise<string | undefined> {
  for (;;) {
    const key = await ask("  Paste your key (empty to go back): ");
    if (!key) return undefined;
    if (!KEY_RE.test(key)) {
      emit("  That is not a CloakBrowser key (they start with cb_).\n");
      continue;
    }
    const info = await validateLicense(key);
    if (info === null) {
      emit("  Could not reach the license server. Check your connection and retry.\n");
    } else if (!info.valid) {
      emit("  That key is invalid or expired.\n");
    } else {
      saveLicenseKey(key);
      emit("  Key saved.\n\n");
      // The menu was the welcome; a paid key keeps its one-time Pro banner.
      if (info.plan === "free") markWelcomeShown();
      return key;
    }
  }
}

/**
 * Open the claim link and wait for the key (saved, returned). undefined if the
 * email already has a key, which the server never sends to a claim.
 */
async function getFreeKey(): Promise<string | undefined> {
  const code = getClaimCode();
  const link = claimLink(code);
  emit(`\n  Open this link and enter your email:\n  ${link}\n`);
  if (openUrl(link)) emit("  (opened in your browser)\n");
  emit("\n  Waiting for you to confirm your email... (Ctrl+C to stop)\n");
  let key: string | undefined;
  try {
    key = await pollClaim(code, { overwrite: true });
  } catch (e) {
    if (e instanceof FreeKeyAlreadyHeld) return undefined;
    throw e;
  }
  emit("  Free key saved.\n\n");
  markWelcomeShown(); // the menu was the welcome: no second banner this launch
  return key;
}

let claimPollStarted = false;

/** @internal Exported for testing only. */
export function resetClaimPollStarted(): void {
  claimPollStarted = false;
}

/**
 * No key anywhere: get one before launching. A person at a terminal gets the
 * menu (promptLicenseKey). Anything else (CI, Docker, an MCP server, a worker
 * thread) throws with the claim link and keeps polling in the background, so a
 * long-lived process picks the key up and its next launch works.
 */
async function claimFreeKey(): Promise<string> {
  let code = getClaimCode();
  let key: string | undefined;
  try {
    key = await checkClaim(code);
  } catch (e) {
    if (!(e instanceof FreeKeyAlreadyHeld)) throw e;
    if (!canPrompt()) {
      throw new CloakBrowserLicenseError(
        `${HAS_KEY_MSG} Set CLOAKBROWSER_LICENSE_KEY or run: cloakbrowser login`,
      );
    }
    // the menu below starts over with a fresh code
  }
  if (key) {
    // confirmed since an earlier launch printed the link
    saveLicenseKey(key, { overwrite: false });
    return key;
  }
  if (canPrompt()) {
    try {
      return await promptLicenseKey();
    } catch (e) {
      if (!(e instanceof PromptClosedError)) throw e;
      // stdin closed mid-menu: fall through to the link + error
    }
  }
  code = getClaimCode(); // fresh if the old one was retired
  const link = claimLink(code);
  emitWelcome();
  emit(`  Get one free (the latest build, 1 concurrent session):\n  ${link}\n` +
    "  After you confirm, the key is also emailed to you.\n\n");
  startClaimPoll(code);
  throw new CloakBrowserLicenseError(
    `No CloakBrowser license key. Get one free: ${link} ` +
      "(or run: cloakbrowser login), then launch again.",
  );
}

/** Poll for the claimed key in the background, once per process (timers unref'd). */
function startClaimPoll(code: string): void {
  if (claimPollStarted) return;
  claimPollStarted = true;
  pollClaim(code, { deadline: Date.now() + CLAIM_POLL_WINDOW_MS })
    .then((key) => {
      if (key) emit("\n  CloakBrowser: free key saved. The next launch uses it.\n");
    })
    .catch((e) => {
      if (e instanceof FreeKeyAlreadyHeld) {
        emit(`\n  CloakBrowser: ${HAS_KEY_MSG}\n  Set CLOAKBROWSER_LICENSE_KEY or run: cloakbrowser login\n`);
      } else {
        console.warn(`[cloakbrowser] Could not save the claimed free key: ${e}`);
      }
    });
}

/** Remove all cached binaries. Forces re-download on next launch. */
export function clearCache(): void {
  const cacheDir = getCacheDir();
  if (fs.existsSync(cacheDir)) {
    fs.rmSync(cacheDir, { recursive: true, force: true });
    console.error(`[cloakbrowser] Cache cleared: ${cacheDir}`);
  }
}

/**
 * Return info about the cached binary installation. browserVersion (or
 * CLOAKBROWSER_VERSION) pins the reported version so the info matches what a
 * pinned launch actually runs, instead of latest. version is null until a
 * build has been downloaded.
 */
export function binaryInfo(
  browserVersion?: string,
  releaseChannel?: string,
): BinaryInfo {
  const version = normalizeRequestedVersion(browserVersion) ?? getEffectiveVersion(releaseChannel);
  const preview = normalizeReleaseChannel(releaseChannel) === "preview";
  return {
    version,
    platform: getPlatformTag(),
    binaryPath: version ? getBinaryPath(version) : null,
    installed: proBinaryReady(version),
    cacheDir: version ? getBinaryDir(version) : null,
    downloadUrl: `${DOWNLOAD_BASE_URL}/api/download/latest${preview ? "?channel=preview" : ""}`,
  };
}

/**
 * Move a Pro install to the selected channel's latest. Blocks until complete.
 * Returns the new version when a newer Pro build is downloaded or an
 * already-cached newer build is activated, else null (already up to date or the
 * server could not be reached). Requires a valid Pro license key.
 */
export async function checkForProUpdate(
  licenseKey: string,
  releaseChannel?: string,
): Promise<string | null> {
  const latest = await getProLatestVersion(releaseChannel);
  if (!latest) return null;

  const effective = getEffectiveVersion(releaseChannel);
  if (effective && !versionNewer(latest, effective) && proBinaryReady(effective)) {
    // Already on the latest cached Pro build.
    return null;
  }

  if (!proBinaryReady(latest)) {
    console.error(`[cloakbrowser] Downloading Pro Chromium ${latest}...`);
    await downloadProBinary(latest, licenseKey);
    if (!fs.existsSync(getBinaryPath(latest))) {
      throw new Error(
        `Pro download completed but binary not found at: ${getBinaryPath(latest)}`
      );
    }
  }

  writeProVersionMarker(latest, releaseChannel);
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

let previewFallbackWarned = false;

/** @internal Exported for testing only. */
export function resetPreviewFallbackWarned(): void {
  previewFallbackWarned = false;
}

/**
 * Tell the user, once per process, that a requested Preview build does not exist
 * for this platform and the Stable build is being used instead.
 */
function warnPreviewFallback(): void {
  if (previewFallbackWarned) return;
  previewFallbackWarned = true;
  console.error(
    `[cloakbrowser] Preview channel requested, but no preview build is available for ${getPlatformTag()}; using the stable build.`,
  );
}

/**
 * Show welcome message on launch. A marker file gates the cadence: a paid (Pro)
 * key shows once ever; a free key re-shows every WELCOME_FREE_INTERVAL_SEC.
 *
 * tier:
 *   "pro"  — a paid license key (Pro banner + support address)
 *   "free" — a free key (latest binary, one concurrent session)
 *
 * Exported for tests only; not re-exported from the package index.
 */
export function showWelcome(tier: "pro" | "free"): void {
  const marker = path.join(getCacheDir(), ".welcome_shown");
  if (!welcomeDue(marker, tier === "pro")) return;
  // ASCII-only banner: on a legacy Windows console a non-ASCII glyph can
  // crash or mojibake the write, and this runs on the binary-download path
  // Keep the three wrappers byte-parallel.
  console.error();
  console.error("  CloakBrowser - stealth Chromium for automation");
  if (tier === "pro") {
    console.error("  CloakBrowser Pro active.");
    console.error();
    console.error("  Pro support -> support@cloakbrowser.dev");
    console.error("  Site -> https://cloakbrowser.dev");
  } else {
    console.error("  CloakBrowser free: 1 concurrent session.");
    console.error();
    console.error("  For more than one concurrent session -> https://cloakbrowser.dev");
  }
  console.error("  Docs -> https://github.com/CloakHQ/CloakBrowser");
  console.error("  Star us if CloakBrowser helps your project!");
  console.error();
  markWelcomeShown();
}

function markWelcomeShown(): void {
  try {
    fs.mkdirSync(getCacheDir(), { recursive: true });
    fs.writeFileSync(
      path.join(getCacheDir(), ".welcome_shown"),
      String(Math.floor(Date.now() / 1000)),
    );
  } catch {
    // Non-fatal
  }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

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
        console.error("[cloakbrowser] SHA256SUMS signature verified: Ed25519 OK");
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
  console.error("[cloakbrowser] Checksum verified: SHA-256 OK");
}

async function downloadFile(url: string, dest: string, headers?: Record<string, string>): Promise<void> {
  console.error(`[cloakbrowser] Downloading from ${url}`);

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
          console.error(
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
    console.error(`[cloakbrowser] Download complete: ${sizeMB} MB`);
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
  const p = getBinaryPath(version);
  return fs.existsSync(p) && isExecutable(p);
}

/** Atomically write the selected channel's Pro version marker for this platform. */
function writeProVersionMarker(version: string, releaseChannel?: string): void {
  const cacheDir = getCacheDir();
  fs.mkdirSync(cacheDir, { recursive: true });
  const channel = normalizeReleaseChannel(releaseChannel);
  const markerPrefix = channel === "preview"
    ? "latest_pro_version_preview"
    : "latest_pro_version";
  const marker = path.join(cacheDir, `${markerPrefix}_${getPlatformTag()}`);
  const tmp = `${marker}.tmp`;
  fs.writeFileSync(tmp, version);
  fs.renameSync(tmp, marker);
}

// Used for free keys (plan "free") and paid keys alike — both fetch the same
// latest build; the server enforces the concurrency cap. If the latest build
// cannot be resolved or downloaded and none is cached, the error is thrown.
async function ensureProBinary(
  licenseKey: string,
  requestedVersion?: string,
  plan?: string,
  releaseChannel?: string,
): Promise<string> {
  // Banner tier: a free key gets the free banner, paid keys the Pro one.
  const welcomeTier = plan === "free" ? "free" : "pro";

  // Pinned: launch the exact requested version, no server cross-check, no marker
  // write (a rollback pin must not stick future unpinned launches).
  if (requestedVersion) {
    if (proBinaryReady(requestedVersion)) {
      showWelcome(welcomeTier);
      return getBinaryPath(requestedVersion);
    }
    console.error(
      `[cloakbrowser] Downloading Pro Chromium ${requestedVersion} for ${getPlatformTag()}...`
    );
    await downloadProBinary(requestedVersion, licenseKey);
    const p = getBinaryPath(requestedVersion);
    if (!fs.existsSync(p)) {
      throw new Error(`Pro download completed but binary not found at: ${p}`);
    }
    showWelcome(welcomeTier);
    return p;
  }

  // Unpinned: track the server's latest selected channel.
  const effective = getEffectiveVersion(releaseChannel);

  // Honor CLOAKBROWSER_AUTO_UPDATE=false: frozen AND a cached build present →
  // keep it, skip the server check. With no cached build we must still fetch one.
  // (The `update` CLI ignores this and always acts.)
  const frozen =
    (process.env.CLOAKBROWSER_AUTO_UPDATE ?? "").toLowerCase() === "false";
  if (frozen && proBinaryReady(effective)) {
    showWelcome(welcomeTier);
    return getBinaryPath(effective);
  }

  // getProLatestVersion() is rate-limited to one network call per hour and returns
  // a cached string in between, so this foreground check stays cheap steady-state.
  const latest = await getProLatestVersion(releaseChannel);

  // Tell the user when they asked for Preview but the server has no preview build
  // for this platform, so the Stable build is used instead. The lookup is a cache
  // hit (getProLatestVersion above already populated it), so this only touches the
  // network on the once-an-hour refresh.
  if (normalizeReleaseChannel(releaseChannel) === "preview") {
    const release = await getProLatestRelease(releaseChannel);
    if (release?.fallback) warnPreviewFallback();
  }

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
    // Valid license but nothing resolvable (server unreachable AND no cached
    // build) — fail loudly.
    throw new Error("Could not determine latest Pro version from server");
  }

  if (proBinaryReady(version)) {
    // Advance the marker if this cached build is newer than what the marker names,
    // so `info` (and a later server-outage launch) reflect the build we actually
    // launch — never a stale marker.
    if (version !== effective) {
      try {
        writeProVersionMarker(version, releaseChannel);
      } catch {
        // Non-fatal
      }
    }
    showWelcome(welcomeTier);
    return getBinaryPath(version);
  }

  // `version` (the server latest) needs downloading. On failure, fall back to a
  // cached build if we have one.
  try {
    console.error(
      `[cloakbrowser] Downloading Pro Chromium ${version} for ${getPlatformTag()}...`
    );
    await downloadProBinary(version, licenseKey);
  } catch (err) {
    // A tampering signal must surface verbatim — never mask it behind the
    // cached-Pro fallback, which is only for transient download failures.
    if (err instanceof BinaryVerificationError) throw err;
    if (proBinaryReady(effective)) {
      console.error(
        `[cloakbrowser] Pro update to ${version} failed; launching cached Pro binary ${effective}`
      );
      showWelcome(welcomeTier);
      return getBinaryPath(effective);
    }
    throw err;
  }

  const downloadedPath = getBinaryPath(version);
  if (!fs.existsSync(downloadedPath)) {
    throw new Error(
      `Pro download completed but binary not found at: ${downloadedPath}`
    );
  }

  // Advance the marker so future unpinned launches use this build.
  try {
    writeProVersionMarker(version, releaseChannel);
  } catch {
    // Non-fatal
  }

  showWelcome(welcomeTier);
  return downloadedPath;
}

/** @internal Exported for testing only. */
export async function downloadProBinary(version: string, licenseKey: string): Promise<void> {
  // Request the explicit version so the served archive matches the signed
  // manifest verified in verifyProDownload.
  const downloadUrl = `${DOWNLOAD_BASE_URL}/api/download/${version}`;
  const binaryDir = getBinaryDir(version);
  const binaryPath = getBinaryPath(version);
  const platformTag = getPlatformTag();

  fs.mkdirSync(path.dirname(binaryDir), { recursive: true });

  const tmpPath = path.join(
    path.dirname(binaryDir),
    `_download_${randomUUID()}${getArchiveExt()}`
  );

  try {
    await downloadFile(downloadUrl, tmpPath, {
      Authorization: `Bearer ${licenseKey}`,
      "X-Platform": platformTag,
    });

    // Non-bypassable Ed25519 signature check (M1 defense); no env var skips it.
    await verifyProDownload(tmpPath, version);

    await extractArchive(tmpPath, binaryDir, binaryPath);
  } finally {
    if (fs.existsSync(tmpPath)) {
      fs.unlinkSync(tmpPath);
    }
  }
}

/**
 * Verify a downloaded archive with a non-bypassable Ed25519 signature check.
 * A tampered same-origin SHA256SUMS could otherwise certify a tampered
 * binary (M1, #308). Fetch the Pro SHA256SUMS +
 * detached SHA256SUMS.sig, verify the signature against the pinned keys FIRST,
 * bind the manifest to the requested version, then verify the archive's
 * SHA-256.
 *
 * An invalid signature, checksum, or version mismatch throws
 * BinaryVerificationError (a tampering signal the router surfaces verbatim);
 * nothing can bypass it. A failed manifest FETCH is transient — nothing was
 * validated — and throws a plain Error.
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
  binaryPath: string
): Promise<void> {
  console.error(`[cloakbrowser] Extracting to ${destDir}`);
  const bp = binaryPath;

  // Extract into a private sibling dir, then rename it into place. Concurrent
  // first runs (in this process or others) each get their own staging dir, so
  // none of them can see or delete another's half-written install.
  const stagingDir = `${destDir}.partial-${randomUUID()}`;
  fs.mkdirSync(stagingDir);
  const staleDirs: string[] = [];
  try {
    if (archivePath.endsWith(".zip")) {
      await extractZip(archivePath, stagingDir);
    } else {
      // Signature-verified before extraction, so unpack as-is.
      await tarExtract({ file: archivePath, cwd: stagingDir, strip: 0 });
    }

    // Flatten single subdirectory if needed
    flattenSingleSubdir(stagingDir);

    // Make binary executable (skip on Windows: no-op / AV lock risk)
    const stagedBinaryPath = path.join(stagingDir, path.relative(destDir, bp));
    if (process.platform !== "win32" && fs.existsSync(stagedBinaryPath)) {
      fs.chmodSync(stagedBinaryPath, 0o755);
    }

    // macOS: remove quarantine/provenance xattrs to prevent Gatekeeper prompts
    if (process.platform === "darwin") {
      removeQuarantine(stagingDir);
    }

    for (let attempt = 1; attempt <= INSTALL_RENAME_ATTEMPTS; attempt++) {
      try {
        await renameDirWithRetry(stagingDir, destDir);
        break;
      } catch (err) {
        // destDir is in the way. Keep it if another caller finished a complete
        // install; replace it if it is an incomplete leftover, such as an
        // interrupted in-place extraction from an older release.
        if (fs.existsSync(bp) && isExecutable(bp)) break;
        if (attempt === INSTALL_RENAME_ATTEMPTS) throw err;
      }
      // Rename the leftover aside before deleting it. Deleting it in place races
      // other callers renaming their extraction into destDir.
      const staleDir = `${destDir}.stale-${randomUUID()}`;
      try {
        await renameDirWithRetry(destDir, staleDir);
      } catch (err) {
        if ((err as NodeJS.ErrnoException).code === "ENOENT") continue; // another caller moved it aside first
        throw err;
      }
      staleDirs.push(staleDir);
    }
  } finally {
    for (const leftoverDir of [stagingDir, ...staleDirs]) {
      try {
        fs.rmSync(leftoverDir, { recursive: true, force: true });
      } catch {
        // Best effort, so a cleanup failure never masks the error being thrown.
      }
    }
  }

  if (fs.existsSync(bp)) {
    console.error(`[cloakbrowser] Binary ready: ${bp}`);
  }
}

/** Rename a directory, retrying while Windows reports it as in use. */
async function renameDirWithRetry(source: string, destination: string): Promise<void> {
  for (let attempt = 1; attempt <= TRANSIENT_RENAME_ATTEMPTS; attempt++) {
    try {
      fs.renameSync(source, destination);
      return;
    } catch (err) {
      // Windows antivirus briefly holds freshly written files open, which fails the
      // rename with EPERM/EACCES/EBUSY. An existing destination is not transient.
      const code = (err as NodeJS.ErrnoException).code;
      if (
        process.platform !== "win32" ||
        !(code === "EPERM" || code === "EACCES" || code === "EBUSY") ||
        attempt === TRANSIENT_RENAME_ATTEMPTS ||
        fs.existsSync(destination)
      ) {
        throw err;
      }
      await new Promise((resolve) => setTimeout(resolve, TRANSIENT_RENAME_DELAY_MS));
    }
  }
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
// Wrapper update check (the binary updates on the launch path, ensureProBinary)
// ---------------------------------------------------------------------------

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
  try {
    const resp = await fetch("https://registry.npmjs.org/cloakbrowser/latest", {
      signal: AbortSignal.timeout(5_000),
    });
    if (!resp.ok) return;
    const data = (await resp.json()) as { version: string };
    if (data.version && versionNewer(data.version, WRAPPER_VERSION)) {
      console.warn(
        `[cloakbrowser] Update available: ${WRAPPER_VERSION} -> ${data.version}. ` +
        `Run: npm install cloakbrowser@latest`
      );
    }
  } catch {
    // Non-fatal — never block binary update check
  }
}

/** Fire-and-forget wrapper update check, once per process. */
function maybeTriggerUpdateCheck(): void {
  if (!wrapperUpdateChecked) {
    checkWrapperUpdate().catch(() => { });
  }
}

