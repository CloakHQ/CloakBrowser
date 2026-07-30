/**
 * Keep the suite away from the developer's real ~/.cloakbrowser.
 *
 * A license.key (or a cached Pro version marker) there resolves the machine as
 * Pro, which flips version-gated defaults such as the headless no-viewport shim
 * — tests then assert against whatever the developer happens to have installed.
 * A fixed path (not mkdtemp) so parallel workers share one dir instead of each
 * stranding its own.
 */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

const cacheDir = path.join(os.tmpdir(), "cloakbrowser-test-cache");
fs.mkdirSync(cacheDir, { recursive: true });
process.env.CLOAKBROWSER_CACHE_DIR = cacheDir;

/**
 * Keep GeoIP off the network for the whole suite.
 *
 * geoip defaults to on, so any test that builds launch options without mocking
 * the resolver would hit the IP echo services and, on a cold cache dir, block on
 * the ~70 MB GeoLite2 download. tests/geoip.test.ts exercises resolution itself
 * and opts back in by deleting this variable.
 */
process.env.CLOAKBROWSER_GEOIP = "0";
