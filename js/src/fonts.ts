// ---------------------------------------------------------------------------
// Windows-font mismatch warning (Linux only)
//
// On Linux the binary spoofs the Windows platform by default, but fonts come
// from the host OS. A font-less Linux box contradicts the Windows claim and
// font-fingerprinting anti-bot systems flag the mismatch. Warn once per
// environment. See docs/chrome40-fpjs-font-minimum-set-investigation.md.
// ---------------------------------------------------------------------------

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { getCacheDir } from "./config.js";

// Windows OS fonts — ship with Windows itself, so their absence on a
// Windows-spoofing Linux host degrades results. The two monospace fonts
// (Consolas + Courier New) are part of the recommended set so the generic
// `monospace` family resolves to a Windows font. See issue #395.
export const WINDOWS_FONT_TELLS = [
  "Segoe UI",
  "Segoe UI Light",
  "Calibri",
  "Marlett",
  "MS UI Gothic",
  "Franklin Gothic",
  "Consolas",
  "Courier New",
];

// MS Office supplemental fonts, installed as one atomic block by every Office
// install. Roughly half of real Windows machines have this pack and half do
// not, so its absence is a perfectly normal Windows setup, NOT a problem —
// reported as an informational signal only, never a warning.
export const OFFICE_FONT_TELLS = [
  "MT Extra",
  "Century",
  "Century Gothic",
  "MS Reference Specialty",
  "Wingdings 2",
  "Wingdings 3",
  "Book Antiqua",
  "Bookshelf Symbol 7",
  "Monotype Corsiva",
  "Bookman Old Style",
];

// macOS OS fonts — the core set present on essentially every real Mac. Their
// absence on a macOS-spoofing Linux host degrades results, just as a Windows-
// spoofing host needs the Windows set above. Several entries (Arial, Georgia,
// Times New Roman, Courier New, Tahoma) also ship on a Windows box, so a partial
// count off-Mac is normal.
export const MACOS_FONT_TELLS = [
  "Apple Color Emoji",
  "Arial",
  "Arial Narrow",
  "Arial Unicode MS",
  "Comic Sans MS",
  "Courier",
  "Courier New",
  "Georgia",
  "Gill Sans",
  "Helvetica",
  "Helvetica Neue",
  "Impact",
  "Menlo",
  "Microsoft Sans Serif",
  "Monaco",
  "Tahoma",
  "Times New Roman",
  "Trebuchet MS",
  "Webdings",
  "Wingdings",
];

let fontWarningChecked = false;

/**
 * Count how many tell-tale fonts are installed, via fc-list.
 *
 * Returns the number present (0..tells.length), or null if it can't be
 * determined (fc-list missing or errored). Callers must NOT treat null as
 * zero — null means "unknown", 0 means "genuinely none installed".
 */
export function countFontsPresent(tells: string[]): number | null {
  let listing: string;
  try {
    // maxBuffer 16 MB: a host with a large font set can produce an fc-list
    // listing well over Node's 1 MB default, which would otherwise throw and
    // skip the warning (Python/.NET have no such cap).
    listing = execFileSync("fc-list", { encoding: "utf8", timeout: 5000, maxBuffer: 16 * 1024 * 1024 }).toLowerCase();
  } catch {
    return null;
  }
  return tells.filter((f) => listing.includes(f.toLowerCase())).length;
}

/**
 * True if ALL Windows OS fonts are installed, false if any are missing, null
 * if unknown. Strict: a partial set is treated as incomplete, since the font
 * install is atomic and a missing font degrades the Windows persona.
 */
export function windowsFontsPresent(): boolean | null {
  const n = countFontsPresent(WINDOWS_FONT_TELLS);
  return n === null ? null : n === WINDOWS_FONT_TELLS.length;
}

/**
 * Warn once when spoofing Windows on a Linux host without the full Windows
 * font set.
 *
 * Best-effort and silent on error — never throws. Gated by an in-process flag
 * plus a cache-dir marker so it fires at most once per environment. Suppress
 * entirely with CLOAKBROWSER_SUPPRESS_FONT_WARNING.
 */
export function maybeWarnWindowsFonts(chromeArgs: string[]): void {
  if (fontWarningChecked) return;
  fontWarningChecked = true;
  try {
    if (process.env.CLOAKBROWSER_SUPPRESS_FONT_WARNING) return;
    if (os.platform() !== "linux") return;
    // Effective platform = the last --fingerprint-platform in the final argv
    // (buildArgs dedups, so at most one). undefined => no Windows spoof.
    let effectivePlatform: string | undefined;
    const prefix = "--fingerprint-platform=";
    for (const arg of chromeArgs) {
      if (arg.startsWith(prefix)) {
        effectivePlatform = arg.slice(prefix.length).trim().toLowerCase();
      }
    }
    if (effectivePlatform !== "windows") return;
    const marker = path.join(getCacheDir(), ".font_warning_shown");
    if (fs.existsSync(marker)) return;
    const present = windowsFontsPresent();
    if (present === null || present === true) return; // full set present or undeterminable
    console.warn(
      "[cloakbrowser] Incomplete Windows font set — installing the full set " +
        "is strongly advised for best results when spoofing Windows on Linux. " +
        "https://github.com/CloakHQ/cloakbrowser#font-setup-on-linux " +
        "(silence: CLOAKBROWSER_SUPPRESS_FONT_WARNING=1)",
    );
    try {
      fs.mkdirSync(getCacheDir(), { recursive: true });
      fs.writeFileSync(marker, "");
    } catch {
      // Non-fatal
    }
  } catch {
    // Best-effort — never throw from a warning.
  }
}
