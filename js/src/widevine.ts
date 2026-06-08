/**
 * Widevine CDM hint-file seeding for persistent contexts.
 * Mirrors Python cloakbrowser/widevine.py.
 *
 * CloakBrowser's binary supports Widevine but ships no CDM (proprietary, can't
 * redistribute). Users sideload it by copying a `WidevineCdm/` directory from a
 * real Chrome install next to the binary (see issue #96). Chromium reads a
 * "hint file" from the user-data-dir at early startup to register the CDM, but
 * on a fresh profile it doesn't exist yet, and Playwright disables the component
 * updater that would write it. This seeds the hint file before launch so a
 * sideloaded CDM works on the first run. It never bundles, downloads, or copies
 * the CDM — only writes the hint when a user-provided CDM is already present.
 *
 * Linux only: Chromium's hint-file mechanism is Linux/ChromeOS-specific.
 */

import fs from "node:fs";
import path from "node:path";

const HINT_FILENAME = "latest-component-updated-widevine-cdm";

/** True if `file` exists and is a regular file (mirrors Python's Path.is_file()). */
function isFile(file: string): boolean {
  try {
    return fs.statSync(file).isFile();
  } catch {
    return false;
  }
}

/** Absolute, symlink-resolved path (mirrors Python's Path.resolve()). */
function realPath(p: string): string {
  try {
    return fs.realpathSync(p);
  } catch {
    return path.resolve(p);
  }
}

function seedingDisabled(): boolean {
  const val = (process.env.CLOAKBROWSER_WIDEVINE ?? "").trim().toLowerCase();
  return val === "0" || val === "false" || val === "off" || val === "no";
}

/**
 * Locate a sideloaded Widevine CDM directory, or null if absent.
 *
 * Resolution:
 *   - If CLOAKBROWSER_WIDEVINE_CDM is set, it is used exclusively (overrides
 *     auto-detection). An invalid value (no `manifest.json`) skips seeding.
 *   - Otherwise, `<dir of the chrome binary>/WidevineCdm` — where a user naturally
 *     drops it, and where it lives for both downloaded and CLOAKBROWSER_BINARY_PATH binaries.
 *
 * A directory counts only if it contains `manifest.json`. The returned path is
 * absolute and symlink-resolved (mirrors Python's Path.resolve()).
 * @internal Exported for testing.
 */
export function resolveWidevineCdmDir(binaryPath: string): string | null {
  const custom = process.env.CLOAKBROWSER_WIDEVINE_CDM;
  // `!== undefined` (not truthiness): a present-but-empty env var is "set" and
  // used exclusively — it resolves to an invalid path and skips seeding.
  const cdmDir = custom !== undefined ? custom : path.join(path.dirname(binaryPath), "WidevineCdm");
  return isFile(path.join(cdmDir, "manifest.json")) ? realPath(cdmDir) : null;
}

/**
 * Write the Widevine CDM hint file into a persistent profile before launch.
 * `binaryPath` is the resolved chrome executable; the CDM is looked for next to
 * it. No-op on non-Linux, when disabled via CLOAKBROWSER_WIDEVINE, or when no
 * sideloaded CDM is present. Never throws — a failure must not break launch.
 */
export function seedWidevineHint(userDataDir: string, binaryPath: string): void {
  if (process.platform !== "linux") return;
  if (seedingDisabled()) return;
  // Empty userDataDir = Playwright's ephemeral profile (its own temp dir);
  // a persistent hint can't be placed there, and "" would pollute the CWD.
  if (!userDataDir) return;

  // Everything below is best-effort and must never break the browser launch,
  // so the whole body (resolution + write) is guarded.
  try {
    const cdmDir = resolveWidevineCdmDir(binaryPath);
    if (cdmDir === null) {
      if (process.env.CLOAKBROWSER_WIDEVINE_CDM !== undefined) {
        console.warn(
          "[cloakbrowser] CLOAKBROWSER_WIDEVINE_CDM is set but has no manifest.json; " +
            "skipping Widevine hint seeding",
        );
      }
      return;
    }

    const hintDir = path.join(userDataDir, "WidevineCdm");
    fs.mkdirSync(hintDir, { recursive: true });
    const hintFile = path.join(hintDir, HINT_FILENAME);
    // cdmDir is already absolute/resolved.
    const content = JSON.stringify({ Path: cdmDir });

    try {
      if (isFile(hintFile) && fs.readFileSync(hintFile, "utf-8") === content) {
        return; // already seeded correctly
      }
    } catch {
      console.warn("[cloakbrowser] Existing Widevine hint unreadable; rewriting");
    }
    fs.writeFileSync(hintFile, content);
  } catch (e) {
    // Best-effort: never break the launch, but surface the failure.
    console.warn("[cloakbrowser] Failed to seed Widevine CDM hint file:", e);
  }
}
