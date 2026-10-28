/**
 * Fingerprint seed persistence for persistent profiles.
 * Mirrors Python cloakbrowser/config.py::persistent_seed_args.
 *
 * The first launch of a profile stores its seed in `<userDataDir>/.cloakbrowser-seed`
 * (decimal + newline, same file in all wrappers); later launches reuse it, so the
 * profile keeps one fingerprint identity across sessions.
 */

import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";

import { SEED_MAX, SEED_MIN, randomSeed } from "./config.js";

export const PROFILE_SEED_FILE = ".cloakbrowser-seed";

/** Stored seed, or null if the file is missing or corrupt (corrupt is removed). */
function readProfileSeed(file: string): number | null {
  let data: Buffer;
  try {
    data = fs.readFileSync(file);
    // Empty = a concurrent launch's exclusive create (no-hard-link fallback)
    // hasn't written yet; give it ~1s before calling the file corrupt.
    for (let i = 0; i < 20 && data.length === 0; i++) {
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 50); // sync sleep
      data = fs.readFileSync(file);
    }
  } catch (e: any) {
    if (e?.code === "ENOENT") return null;
    throw e;
  }
  const text = data.toString("latin1").trim();
  if (/^[0-9]+$/.test(text) && Number(text) >= SEED_MIN && Number(text) <= SEED_MAX) {
    return Number(text);
  }
  // A corrupt file gets a fresh seed (= new identity), so say so loudly.
  console.warn(
    `[cloakbrowser] Corrupt fingerprint seed file ${file} (${JSON.stringify(text.slice(0, 32))}); generating a new seed`,
  );
  try {
    fs.unlinkSync(file);
  } catch (e: any) {
    if (e?.code !== "ENOENT") throw e; // ENOENT: a concurrent launch already removed it
  }
  return null;
}

/** Create `file` exclusively (EEXIST if present), write `content`, fsync. */
function writeSynced(file: string, content: string): void {
  const fd = fs.openSync(file, "wx");
  try {
    fs.writeSync(fd, content);
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
}

/**
 * Prepend the profile's stored `--fingerprint=<seed>` to `args`, creating it on
 * first launch. It is a user arg, so it overrides the random stealth default via
 * buildArgs dedup. An explicit `--fingerprint` (including `=off`) or
 * `stealthArgs: false` leaves the file alone.
 */
export function persistentSeedArgs(
  userDataDir: string | undefined,
  stealthArgs: boolean | undefined,
  args: string[] | undefined,
): string[] | undefined {
  if (stealthArgs === false || !userDataDir) return args;
  if ((args ?? []).some((a) => a.split("=")[0] === "--fingerprint")) return args;

  const file = path.join(userDataDir, PROFILE_SEED_FILE);
  let seed = readProfileSeed(file);
  if (seed === null) {
    fs.mkdirSync(userDataDir, { recursive: true });
    const tmp = path.join(userDataDir, `${PROFILE_SEED_FILE}.${randomUUID()}.tmp`);
    const content = `${randomSeed()}\n`;
    try {
      writeSynced(tmp, content);
      // Publish without replacing: concurrent first launches all end up with
      // whichever seed was linked first.
      try {
        fs.linkSync(tmp, file);
      } catch (e: any) {
        if (e?.code !== "EEXIST") {
          // No hard links (FAT/exFAT, some network mounts): exclusive create
          // still never overwrites. ponytail: a concurrent reader can catch the
          // file empty here and regenerate; link() avoids that window.
          try {
            writeSynced(file, content);
          } catch (e2: any) {
            if (e2?.code !== "EEXIST") throw e2;
          }
        }
      }
    } finally {
      try {
        fs.unlinkSync(tmp);
      } catch (e) {
        console.warn(`[cloakbrowser] Failed to remove temp seed file ${tmp}:`, e);
      }
    }
    seed = readProfileSeed(file);
    if (seed === null) throw new Error(`Could not create fingerprint seed file ${file}`);
  }
  return [`--fingerprint=${seed}`, ...(args ?? [])];
}
