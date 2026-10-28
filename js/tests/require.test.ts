import { describe, it, expect } from "vitest";
import { execFile } from "node:child_process";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

// Loads the built dist/ (npm run build first, as CI does) through the package's
// own exports map, the way a consumer's require() or import resolves it.
const PKG_DIR = fileURLToPath(new URL("..", import.meta.url));
const SUBPATHS = ["cloakbrowser", "cloakbrowser/puppeteer", "cloakbrowser/human"];

async function run(args: string[]): Promise<string> {
  const { stdout } = await promisify(execFile)(process.execPath, args, { cwd: PKG_DIR });
  return stdout.trim();
}

describe("package entry points", () => {
  it.skipIf(!process.features.require_module)("CommonJS require() loads every subpath", async () => {
    const script = `console.log(JSON.stringify(${JSON.stringify(SUBPATHS)}.map((m) => Object.keys(require(m)).length)));`;
    const counts = JSON.parse(await run(["-e", script])) as number[];
    expect(counts.every((n) => n > 0)).toBe(true);
    expect(await run(["-e", `console.log(typeof require("cloakbrowser").launch)`])).toBe("function");
  });

  it("ESM import loads every subpath", async () => {
    const script =
      `const mods = await Promise.all(${JSON.stringify(SUBPATHS)}.map((m) => import(m)));` +
      `console.log(JSON.stringify(mods.map((m) => Object.keys(m).length)));`;
    const counts = JSON.parse(await run(["--input-type=module", "-e", script])) as number[];
    expect(counts.every((n) => n > 0)).toBe(true);
  });
});
