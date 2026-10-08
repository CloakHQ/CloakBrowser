/**
 * Playwright's own selector / actionability engine, run inside OUR isolated world.
 *
 * Playwright ships its InjectedScript (selector engines for role, label, text,
 * test-id, `>>` chains, `has` / `has-text` filters, `nth`, `visible`, plus
 * `checkElementStates` / `expectHitTarget` / `fill` rules) as a string literal
 * inside playwright-core. Playwright installs it in the page's main world or
 * its utility world -- both leave page-visible traces (capture listeners,
 * `__playwright_*` CustomEvents).
 *
 * Here the very same source is evaluated in a CDP isolated world that only the
 * humanize layer uses, with the two constructor hooks that touch `window`
 * (hit-target interceptors and global-listener-removal detection) disabled.
 * The page cannot observe the installation or any query made through it.
 *
 * The literal is extracted from the installed playwright-core, so selector
 * syntax always matches the client that produced the selector string.
 * Mirrors cloakbrowser/human/injected.py.
 */

import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

/** Global name inside the isolated world (invisible to page scripts). */
export const GLOBAL = '__cloakInjected';

const LITERAL_START = /\bsource\d*\s*[=:]\s*(['"`])/g;
const cache = new Map<string, string>();

function libDirs(): string[] {
  const require = createRequire(import.meta.url);
  try {
    const pkg = require.resolve('playwright-core/package.json');
    const lib = path.join(path.dirname(pkg), 'lib');
    return fs.existsSync(lib) ? [lib] : [];
  } catch {
    return [];
  }
}

/** The JS string literal starting at `text[start]` (quotes included). */
export function readLiteral(text: string, start: number): string {
  const quote = text[start];
  let i = start + 1;
  while (text[i] !== quote) i += text[i] === '\\' ? 2 : 1;
  return text.slice(start, i + 1);
}

function literalAfter(text: string, from: number): string | null {
  LITERAL_START.lastIndex = from;
  const m = LITERAL_START.exec(text);
  if (!m) return null;
  return readLiteral(text, m.index + m[0].length - 1);
}

function* walk(dir: string): Generator<string> {
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) yield* walk(p);
    else if (ent.name === 'injectedScriptSource.js') yield p;
  }
}

/**
 * Locate the InjectedScript source literal in playwright-core. Supports the
 * bundled layout (`coreBundle.js`, >= 1.55) and the older per-file layout
 * (`generated/injectedScriptSource.js`).
 */
export function findInjectedLiteral(dirs: string[] = libDirs()): string {
  const key = dirs.join('|');
  const hit = cache.get(key);
  if (hit) return hit;
  for (const d of dirs) {
    const bundle = path.join(d, 'coreBundle.js');
    if (fs.existsSync(bundle)) {
      const text = fs.readFileSync(bundle, 'utf-8');
      const pos = text.indexOf('generated/injectedScriptSource.ts');
      if (pos >= 0) {
        const lit = literalAfter(text, pos);
        if (lit) { cache.set(key, lit); return lit; }
      }
    }
    for (const f of [...walk(d)].sort()) {
      const lit = literalAfter(fs.readFileSync(f, 'utf-8'), 0);
      if (lit) { cache.set(key, lit); return lit; }
    }
  }
  throw new Error(
    `cloakbrowser humanize: Playwright's InjectedScript source was not found in ${JSON.stringify(dirs)}; ` +
    'the installed playwright-core layout is not supported',
  );
}

/**
 * Expression that installs the engine in the current (isolated) world.
 * `source` is the *decoded* InjectedScript module text. Idempotent.
 */
export function buildInstallJs(source: string, sdkLanguage = 'javascript', testIdAttribute = 'data-testid'): string {
  const opts = JSON.stringify({
    isUnderTest: false,
    sdkLanguage,
    testIdAttributeName: testIdAttribute,
    stableRafCount: 1,
    browserName: 'chromium',
    isUtilityWorld: true,
    customEngines: [],
  });
  return '(() => {\n' +
    `if (globalThis.${GLOBAL}) return true;\n` +
    'const module = { exports: {} }; const exports = module.exports;\n' +
    `${source}\n` +
    ';const exp = module.exports.InjectedScript;\n' +
    'const C = (exp && exp.prototype && exp.prototype.querySelectorAll) ? exp : exp();\n' +
    // Both hooks register listeners / dispatch events on the shared window.
    'C.prototype._setupGlobalListenersRemovalDetection = function () {};\n' +
    'C.prototype._setupHitTargetInterceptors = function () {};\n' +
    `const o = ${opts};\n` +
    'const inj = C.length > 2\n' +
    '  ? new C(globalThis, o.isUnderTest, o.sdkLanguage, o.testIdAttributeName, o.stableRafCount, o.browserName, o.customEngines)\n' +
    '  : new C(globalThis, o);\n' +
    `Object.defineProperty(globalThis, ${JSON.stringify(GLOBAL)}, { value: inj });\n` +
    'return true; })()';
}
