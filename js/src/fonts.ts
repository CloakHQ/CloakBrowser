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

let fontWarningChecked = false;

/**
 * Whether `family` actually resolves, via `fc-match`. Null when undeterminable.
 *
 * Resolution, not presence in a listing. `fc-list` output was the old signal and
 * it over-counts two ways: it prints file paths as well as family names, so
 * `/usr/share/fonts/consolas.ttf` looked like Consolas even when the family
 * failed to resolve; and a substring match makes any longer family satisfy a
 * shorter one, so "Franklin Gothic" matched the line for "Franklin Gothic
 * Medium" while `fc-match "Franklin Gothic"` fell through to NimbusSans. A
 * family the renderer cannot resolve is one no font-fingerprinting script will
 * ever detect, so it must not be counted.
 */
export function fontFamilyResolves(family: string, timeoutMs = 5000): boolean | null {
  if (timeoutMs <= 0) return null;
  let out: string;
  try {
    out = execFileSync("fc-match", ["--format=%{family}", family], {
      encoding: "utf8",
      timeout: timeoutMs,
    });
  } catch {
    return null;
  }
  // fc-match always answers with *something* (the default font when it cannot
  // match), so the returned family has to be compared against what we asked for.
  // It may carry comma-separated aliases, e.g. "Segoe UI,Segoe UI Light".
  const wanted = family.toLowerCase();
  // Exact match only: a request for "Segoe UI" must not be satisfied by "Segoe
  // UI Emoji", a different family with different metrics that is commonly
  // present on its own.
  return out.split(",").some((name) => name.trim().toLowerCase() === wanted);
}

// One fc-match per family, so the ceiling has to bound the WHOLE probe. A
// per-call timeout would multiply by the number of families and a wedged
// fontconfig could stall a launch for 8x that.
const FONT_PROBE_TIMEOUT_MS = 5000;

/**
 * Count how many tell-tale font families actually resolve.
 *
 * Returns the number present (0..tells.length), or null if it can't be
 * determined (fc-match missing, errored, or the probe ran out of time).
 * Callers must NOT treat null as zero — null means "unknown", 0 means
 * "genuinely none installed".
 */
export function countFontsPresent(tells: string[]): number | null {
  const deadline = Date.now() + FONT_PROBE_TIMEOUT_MS;
  const resolved = tells.map((family) =>
    fontFamilyResolves(family, Math.max(deadline - Date.now(), 0)),
  );
  // A partial answer cannot be reported as a count: an unresolved family is
  // indistinguishable from a missing one, and under-reporting would nag about
  // fonts that are actually installed.
  if (resolved.some((state) => state === null)) return null;
  return resolved.filter(Boolean).length;
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
