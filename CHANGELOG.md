# Changelog

All notable changes to CloakBrowser — wrapper and binary — are documented here.

Changes are tagged: **[wrapper]** for Python/JS wrapper, **[binary]** for Chromium patches.

---

## [0.3.14] — 2026-03-12

- **[binary]** Upgrade Linux build to 145.0.7632.159.6 — fix persistent context detection by FingerprintJS
- **[binary]** Storage quota normalization for persistent context profiles
- **[binary]** Fix outerHeight calculation for non-incognito contexts
- **[wrapper]** Add CLI for binary management — `python -m cloakbrowser install` / `npx cloakbrowser install` with visible download progress (closes #43)

## [0.3.13] — 2026-03-10

- **[wrapper]** Suppress Playwright's `--enable-unsafe-swiftshader` default arg — eliminates SwiftShader software renderer detection signal, letting the binary's GPU spoofing work cleanly
- **[binary]** Upgrade Linux build to 145.0.7632.159.5 — fix WebGPU adapter limits and features for NVIDIA profiles

## [0.3.12] — 2026-03-10

- **[binary]** Upgrade Linux build to 145.0.7632.159.4
- **[binary]** Native locale spoofing — new C++ patch replaces detectable CDP-level locale emulation
- **[binary]** WebGPU fingerprint hardening — spoof adapter features, limits, device ID, and subgroup sizes for cross-API consistency
- **[binary]** Restore WebGPU blocklist bypass auto-injection (safe now with full adapter spoofing)
- **[binary]** Fix WebGL renderer suffix — remove driver version string flagged by BrowserLeaks
- **[wrapper]** Use binary flags for timezone/locale instead of CDP emulation — eliminates a detection vector
- **[wrapper]** Support bare proxy format (`user:pass@host:port`) without scheme prefix
- **[wrapper]** Use ANGLE-wrapped GPU strings in default stealth args for realistic WebGL fingerprint

## [0.3.11] — 2026-03-08

- **[wrapper]** `humanize=True` — human-like mouse (Bézier curves, overshoot), keyboard (per-character timing, thinking pauses), scroll (accelerate/cruise/decelerate), and click behavior. Two presets: `default` and `careful`. Works in Python and JS. (thanks [@evelaa123](https://github.com/evelaa123))
- **[binary]** CDP input stealth — 4 new source-level C++ patches removing automation signals from input events
- **[binary]** Support `--remote-debugging-address` flag for CDP bind address — eliminates the socat workaround in `cloakserve` Docker mode
- **[wrapper]** `cloakserve` updated to use `--remote-debugging-address=0.0.0.0` directly — socat dependency removed from Docker image
- **[binary]** GPU fingerprint accuracy improvements — renderer suffix strings now match real Chrome output across Windows and Linux profiles
- **[binary]** GPU capability accuracy fix for NVIDIA profiles — spoofed values now reflect actual hardware limits
- **[binary]** macOS GPU accuracy fix — GPU model database reference corrected for Apple Silicon profiles
- **[binary]** Fix CDP input synthesis — a guard condition prevented the patch from activating; now fires correctly on all input events
- **[binary]** Code quality hardening across patches — correctness and reliability fixes

## [0.3.10] — 2026-03-07

- **[binary]** Upgrade Linux build to 145.0.7632.159.2
- **[binary]** Fix detection regression caused by unnecessary browser flag (fixes #16)
- **[binary]** Fix fingerprint consistency in offline audio rendering
- **[wrapper]** Add `cloakserve` CDP server mode for Docker — exposes Chrome DevTools Protocol on `0.0.0.0:9222` for external tool integration
- **[wrapper]** Add wrapper regression tests: page.goto timing with stealth init (#9), add_init_script compatibility with proxy auth (#27)

## [0.3.9] — 2026-03-05

- **[binary]** Upgrade Chromium base to 145.0.7632.159 (Linux x64). macOS and Windows remain on 145.0.7632.109.2
- **[binary]** WebGPU adapter spoofing for headless/Docker, timezone multi-context fix, stealth audit phase 2 (6 detection vector fixes), font auto-hide for cross-platform fingerprints
- **[wrapper]** Default Playwright backend switched from `patchright` to stock `playwright`. Patchright broke proxy auth and `add_init_script` (#27) and is redundant since the binary handles stealth at C++ level. Opt in with `launch(backend="patchright")` or `CLOAKBROWSER_BACKEND=patchright` env var. Install: `pip install cloakbrowser[patchright]`
- **[wrapper]** Deduplicate CLI flags when user args overlap with stealth defaults — user values win cleanly instead of passing both to Chromium
- **[wrapper]** Extract shared `buildArgs` into `js/src/args.ts` (JS DRY fix), guard debug logging behind `DEBUG=cloakbrowser` env var

## [0.3.7] — 2026-03-05

- **[wrapper]** Unify timezone parameter: rename `timezone_id` to `timezone` in `launch_context()`, `launch_persistent_context()`, and `launch_persistent_context_async()` (Python). Old `timezone_id` still works with a deprecation warning. JS: deprecate `timezoneId` on `LaunchContextOptions` — use `timezone` (inherited from `LaunchOptions`)
- **[wrapper]** Docker Hub image (`cloakhq/cloakbrowser`) — pre-built with Python + JS wrappers, Xvfb for headed mode, and `cloaktest` CLI shortcut. One-liner: `docker run --rm cloakhq/cloakbrowser cloaktest`
- **[wrapper]** Add "Launching stealth browser..." feedback to all examples for better UX in Docker/CI
- **[wrapper]** Comprehensive unit tests: 169 Python + 88 JS (up from 59 + 47)
- **[docs]** Streamline READMEs for launch — reorder for conversion, collapse fingerprint flags, update Docker section

## [0.3.6] — 2026-03-04

- **[wrapper]** `proxy` parameter now accepts a Playwright proxy dict (`{server, bypass, username, password}`) in addition to URL strings — enables bypass lists and separate auth fields (PR #24). **TS note:** type changed from `string` to `string | object` — code that assumed `proxy` is always a string may need a `typeof` narrowing check

## [0.3.5] — 2026-03-04

- **[wrapper]** Add `launch_persistent_context()` and `launch_persistent_context_async()` (Python) — persistent browser profiles with cookie/localStorage persistence across sessions, avoids incognito detection (thanks [@evelaa123](https://github.com/evelaa123), [@yahooguntu](https://github.com/yahooguntu) — PRs #22, #17)
- **[wrapper]** Add `launchPersistentContext()` (JS/TS) — same feature for JavaScript with full type support
- **[wrapper]** Fix Windows zip extraction failure when primary download server is down — file handle leak caused `ERROR_SHARING_VIOLATION` on fallback download (thanks [@evelaa123](https://github.com/evelaa123) — PR #23)

## [0.3.4] — 2026-03-04

Binary v14: auto-spoof restored with seed, wrapper simplified to match.

- **[binary]** Restore full auto-spoof when `--fingerprint=seed` is set — all randomized properties now derive from the seed consistently
- **[binary]** Auto-inject random fingerprint seed at startup if none provided. Binary is stealthy with zero flags
- **[binary]** 26 source-level C++ patches (up from 25)
- **[wrapper]** Simplify default stealth args — remove flags the binary now auto-generates. Wrapper still sets platform profile on Linux and `--no-sandbox`
- **[wrapper]** Fix timezone in `launch_context()` — use Playwright's per-context timezone instead of binary flag, fixing mismatch when creating new browser contexts with geoip
- **[wrapper]** Clarify README platform detection behavior

## [0.3.3] — 2026-03-03

All platforms now run Chromium 145 v2 with 25 patches. Windows x64 added.

- **[binary]** Auto-spoof by default — binary is stealthy with zero flags. Random fingerprint seed auto-generated at startup, no wrapper or configuration required
- **[binary]** Platform-aware auto-detection — GPU, screen dimensions, and User-Agent automatically match the real OS (macOS, Linux, Windows) without explicit flags
- **[binary]** Expanded GPU model database for realistic per-session diversity
- **[binary]** First macOS v145 builds (arm64 + x64) — 25 patches, up from 16 on v142
- **[binary]** First Windows x64 v145 build — 25 patches
- **[wrapper]** Add Windows x64 platform support — auto-download, binary path resolution, and platform detection
- **[wrapper]** Upgrade macOS (arm64 + x64) from Chromium 142 to 145 — all platforms now ship the same 25-patch build
- **[wrapper]** Add explicit Mac GPU flags (`Apple M3 Metal` renderer) to default stealth args for consistent WebGL fingerprints
- **[wrapper]** Improve reCAPTCHA stealth test — wait for score element instead of blind sleep
- **[wrapper]** JS: add `win32-x64` platform mapping, Windows binary path (`chrome.exe`)

## [0.3.1] — 2026-03-03

- **[wrapper]** Auto-check for wrapper updates on startup (PyPI/npm). Notifies users when a newer wrapper version is available. Runs once per process, respects `CLOAKBROWSER_AUTO_UPDATE=false`.

---

## [0.3.0] — 2026-03-02

Chromium v145 upgrade. 25 fingerprint patches (up from 16). New download verification and fallback system. macOS v145 binary builds pending.

### Breaking

- **[wrapper]** Python dependency changed from `playwright` to `patchright` (CDP stealth fork). Patchright is API-compatible, but if you import `playwright` directly elsewhere, add it as a separate dependency. Replace `from playwright.sync_api` with `from patchright.sync_api` (or keep using `cloakbrowser.launch()` which handles this automatically).
- **[wrapper]** `launch_context()` / `launchContext()` now defaults viewport to 1920×947 (realistic maximized Chrome on 1080p Windows with 48px taskbar) instead of Playwright's default 1280×720. Pass `viewport={"width": 1280, "height": 720}` explicitly to restore old behavior.

### 2026-03-02

- **[binary]** Full stealth audit — multiple detection vectors eliminated, improved cross-API consistency
- **[binary]** Platform-aware fingerprint defaults: screen dimensions, taskbar, and layout auto-adjust per spoofed platform
- **[binary]** Stability and performance improvements across fingerprint patches
- **[binary]** New optional flags: `--fingerprint-fonts-dir`, `--fingerprint-taskbar-height`
- **[wrapper]** Sync wrapper with latest binary changes: updated flag names, viewport, and defaults
- **[wrapper]** Per-platform Chromium versioning — Linux and macOS can track different binary versions independently
- **[wrapper]** Improved SHA-256 checksum verification and version marker migration

### 2026-03-01

- **[wrapper]** Upgrade wrapper to Chromium v145.0.7632.109
- **[wrapper]** Add GitHub Releases fallback when primary download mirror is unavailable
- **[wrapper]** Add SHA-256 checksum verification for binary downloads
- **[wrapper]** Wire timezone and locale params to Chromium binary flags
- **[wrapper]** Add device memory to default stealth args
- **[wrapper]** JS: add `colorScheme` support, guard download fallback against partial failures

### 2026-02-28

- **[binary]** Enforce strict flag discipline — patches only activate when explicitly configured via command-line flags
- **[binary]** Improved fingerprint consistency across multiple browser APIs
- **[binary]** 3 new fingerprint patches + bug fixes in existing patches
- **[binary]** New command-line flag for device memory spoofing
- **[infra]** Automated test matrix: 8 groups, 41+ tests across core stealth, fingerprint noise, bot detection, reCAPTCHA, TLS, Turnstile, residential proxy, and enterprise reCAPTCHA
- **[infra]** Docker-based test runner with subprocess isolation per test group

### 2026-02-25

- **[binary]** Reduced automation markers visible to detection scripts
- **[binary]** Added browser API support at build time
- **[binary]** Improved screen property consistency

### 2026-02-24

- **[binary]** Comprehensive fingerprint audit and hardening pass
- **[binary]** Fixed font rendering edge case on cross-platform spoofing
- **[binary]** 4 new fingerprint patches

### 2026-02-22

- **[binary]** Start Chromium v145 build (v145.0.7632.109)
- **[binary]** 24 fingerprint patches ported and adapted

---

## [0.2.2] — 2026-03-01

### 2026-03-01

- **[wrapper]** Fix: replace `page.wait_for_timeout()` with `time.sleep()` to avoid timing leak
- **[wrapper]** Add auto-detect timezone and locale from proxy IP via GeoIP lookup
- **[binary]** CDP detection vector audit and hardening

---

## [0.2.0] — 2026-02-27

macOS platform release. JavaScript/TypeScript wrapper. Self-hosted binary mirror.

### 2026-02-27

- **[wrapper]** Add macOS support: Apple Silicon (arm64) and Intel (x64) binary downloads
- **[wrapper]** Add GPG-signed release workflow via GitHub Actions
- **[wrapper]** Fix macOS binary download: preserve `.app` symlinks, remove quarantine xattrs
- **[wrapper]** Add real bot detection assertions to stealth tests
- **[wrapper]** Bump version to 0.2.0

### 2026-02-26

- **[wrapper]** Switch binary downloads to self-hosted mirror (`cloakbrowser.dev`) as GitHub backup
- **[wrapper]** Set up GitLab mirror at `gitlab.com/CloakHQ/cloakbrowser`

### 2026-02-25

- **[wrapper]** Move binary releases from separate repo to wrapper repo
- **[wrapper]** Add auto-update check on launch
- **[infra]** Initial Docker test infrastructure + matrix test runner

### 2026-02-24

- **[wrapper]** Add JavaScript/TypeScript wrapper with Playwright + Puppeteer support (`npm install cloakbrowser`)
- **[wrapper]** Fix proxy authentication credentials support in URL (closes #4)

---

## [0.1.4] — 2026-02-23

### 2026-02-23

- **[wrapper]** Stealth hardening: additional launch args and detection evasion improvements
- **[wrapper]** Full test suite rewrite with real detection site assertions
- **[wrapper]** Add Docker support with Dockerfile and compose config
- **[wrapper]** Add headed mode documentation

---

## [0.1.0] — 2026-02-22

Initial release. Chromium v142 with 16 fingerprint patches.

### 2026-02-22

- **[binary]** Chromium v142.0.7444.175 with 16 source-level fingerprint patches
- **[binary]** Fix browser brand string to match Chrome 142 format
- **[wrapper]** `launch()` and `launch_async()` — drop-in Playwright replacements
- **[wrapper]** Auto-download binary from GitHub Releases, cached in `~/.cloakbrowser/`
- **[wrapper]** Linux x64 platform support
- **[wrapper]** Passes 14/14 bot detection tests
- **[wrapper]** reCAPTCHA v3: 0.9 (server-verified), Cloudflare Turnstile: pass
