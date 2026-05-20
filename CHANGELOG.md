# Changelog

All notable changes to CloakBrowser — wrapper and binary — are documented here.

Changes are tagged: **[wrapper]** for Python/JS wrapper, **[binary]** for Chromium patches.

---

## [Unreleased]

- **[wrapper]** **New**: agent-friendly CLI subcommands — `doctor`, `profile list/path`, `screenshot`, `dump`, `eval`, `open` with `--json` output for automation workflows (#274, #275)

## [0.3.30] — 2026-05-21

- **[binary]** New build 146.0.7680.177.5 for Linux x64 + Windows x64 — 58 source-level fingerprint patches (up from 57)
- **[binary]** Rendering consistency improvements across Linux and Windows — corrected GPU, display, and graphics parameters to match stock Chrome 146 profiles
- **[binary]** Windows: native GPU/rendering values now pass through directly instead of being spoofed, matching real hardware behavior
- **[binary]** Storage normalization fix for Windows
- **[binary]** HTTP proxy inline credential support at the network layer
- **[wrapper]** Update `PLATFORM_CHROMIUM_VERSIONS` for linux-x64 and windows-x64 to 146.0.7680.177.5

## [0.3.29] — 2026-05-20

- **[wrapper]** **Security**: `cloakserve` — guard WebSocket origins to prevent browser-origin CSRF via CDP proxy (thanks [@0xlally](https://github.com/0xlally) for the report, [@honor2030](https://github.com/honor2030) for the fix, #239, #240)
- **[wrapper]** **Security**: Lambda example — add URL scheme validation, SSRF protection, post-navigation re-validation, remove unsafe caller-controlled options (#233)
- **[wrapper]** **Security**: CI — isolate `workflow_dispatch` input to avoid shell injection in attest-release (thanks [@aaronjmars](https://github.com/aaronjmars), #223)
- **[wrapper]** **Security**: JS — bump tar + transitive deps via npm audit fix (thanks [@aaronjmars](https://github.com/aaronjmars), #222)
- **[wrapper]** Add `extension_paths` parameter for loading Chrome extensions in all launch functions (thanks [@zackycodes](https://github.com/zackycodes), #210)
- **[wrapper]** Humanize: add Playwright-style actionability checks — auto-wait for visible, enabled, stable elements before humanized actions (#228)
- **[wrapper]** JS: export composable launch helpers — `buildLaunchOptions()` and `humanizeBrowser()` for custom Playwright integrations (thanks [@honor2030](https://github.com/honor2030), #244)
- **[wrapper]** JS: add `launchPersistentContext()` to Puppeteer wrapper (#261)
- **[wrapper]** Add `flake.nix` for Nix/NixOS (thanks [@Seryiza](https://github.com/Seryiza), #220)
- **[meta]** JS: sync package-lock metadata (thanks [@245678000000](https://github.com/245678000000), #219)

## [0.3.28] — 2026-05-11

- **[wrapper]** **Security**: `cloakserve` — sanitize fingerprint seed to prevent path traversal, bind to `127.0.0.1` on bare metal, detect Podman containers (#217)
- **[wrapper]** Fix GeoIP resolution hanging indefinitely — bounded with 10s timeout so `launch()` cannot stall (thanks [@manaskarra](https://github.com/manaskarra), #213)
- **[wrapper]** JS: preserve iframe scope in humanized frame actions — `check()`, `uncheck()`, `selectOption()` now execute in the correct frame (thanks [@manaskarra](https://github.com/manaskarra), #201)
- **[wrapper]** JS: add TypeScript types to humanized method options — `HumanActionOptions` type for `human_config` and `timeout` overrides (thanks [@eofreternal](https://github.com/eofreternal), #205)
- **[wrapper]** Log when SOCKS5 credential auto-encoding rewrites a proxy URL (thanks [@Youhai020616](https://github.com/Youhai020616), #209)
- **[wrapper]** JS: bump `playwright-core` peer dependency minimum to >=1.53.0 (#200)
- **[meta]** Bump sigstore/cosign-installer in CI (#214)

## [0.3.27] — 2026-05-06

- **[wrapper]** Per-call `human_config` override — pass `human_config={...}` to individual humanized methods to override global HumanConfig on a per-action basis (#183)
- **[wrapper]** Humanized `scrollIntoViewIfNeeded` — auto-scrolls with human-like behavior when `humanize=True` (#183)
- **[wrapper]** Forward `timeout` parameter through humanized Playwright methods (#183)
- **[wrapper]** Fix humanize timeout default to align with Playwright's 30s auto-retry instead of custom 2s (#172)

## [0.3.26] — 2026-04-28

- **[binary]** Windows x64 upgraded to Chromium 146.0.7680.177.4 — 57 source-level fingerprint patches (up from 33 on 145.0.7632.159.7), now matches Linux. Includes all binary improvements from 0.3.18–0.3.25: native SOCKS5 proxy with UDP ASSOCIATE (QUIC/HTTP3), WebRTC IP spoofing, proxy signal removal, CDP input stealth, storage quota normalization, WebAuthn/AAC/window position patches, WebGL and canvas consistency fixes, expanded GPU model database
- **[wrapper]** Auto URL-encode SOCKS5 credentials containing special characters in string URLs (#157)
- **[wrapper]** AWS Lambda integration example with cold-start hardening and handler-side retry orchestration (#177, thanks [@AlexTech314](https://github.com/AlexTech314))
- **[docker]** Add emoji and extended font packages to resolve Kasada/Akamai canvas fingerprint blocks (#179)
- **[docs]** Add Font Setup on Linux section to README (#179)
- **[docs]** Add Deployment Integrations section to README (#177)
- **[meta]** Bump GitHub Actions dependencies (#178)

## [0.3.25] — 2026-04-16

- **[wrapper]** Python: add `launch_context_async()` — async counterpart to `launch_context()`. Returns a BrowserContext with all kwargs forwarded to `browser.new_context()`, enabling `storage_state`, `permissions`, `extra_http_headers`, etc. without a persistent profile folder. Closes #141.
- **[wrapper]** JS: `launchContext()` and `launchPersistentContext()` silently dropped unknown options (including `storageState`). New `contextOptions` escape hatch forwards arbitrary options to Playwright's `newContext()`.
- **[wrapper]** Fix `humanConfig` TypeScript typing (#151).
- **[binary]** New build 146.0.7680.177.3 for Linux x64 + arm64 — 57 source-level fingerprint patches (up from 49): WebAuthn capabilities, AAC audio encoder, and window position spoofing; WebGL and canvas format consistency fixes; SOCKS5 warm connection pool auth fix for credentialed proxies.
- **[docs]** Add recommended anti-bot config and SOCKS5 tips to troubleshooting.

## [0.3.24] — 2026-04-10

- **[wrapper]** Native SOCKS5 proxy support — pass `proxy="socks5://user:pass@host:port"` directly. Credentials handled natively by Chrome. Works across all launch functions, Python + JS.
- **[wrapper]** Add Playwright ElementHandle humanize support — `element_handle.click()`, `.fill()`, `.type()` now use human-like behavior when `humanize=True` (thanks [@evelaa123](https://github.com/evelaa123), #133)
- **[binary]** Upgrade Linux arm64 to Chromium 146.0.7680.177.2 (49 patches) — now matches Linux x64
- **[binary]** New build 146.0.7680.177.2 for both Linux platforms: native SOCKS5 proxy with UDP ASSOCIATE (QUIC/HTTP3 over SOCKS5)
- **[docs]** Clarify humanize requires wrapper import over CDP (#126)

## [0.3.23] — 2026-04-09

- **[wrapper]** Add full Puppeteer humanize support — human-like mouse, keyboard, and scroll behavior for `puppeteer-core` users (thanks [@evelaa123](https://github.com/evelaa123), #129)
- **[wrapper]** Fix Playwright humanize gaps — `pressSequentially`, `tap`, `clear` on pages and frames now use human-like behavior (#129)
- **[wrapper]** Expose humanize module for CDP-connected browsers — `import from 'cloakbrowser/human'` for manual patching of external Playwright instances (#126)
- **[docker]** Fix `cloakserve` locale/timezone mismatch — CLI args now route through `build_args()` so the companion `--lang` flag is added automatically (#130)
- **[meta]** Use Node 24 in CI publish workflow to work around broken npm in Node 22.22.2

## [0.3.22] — 2026-04-09

- **[binary]** Upgrade Linux x64 build to Chromium 146.0.7680.177.1 — 49 source-level C++ patches (up from 48), rebased from 145.0.7632.x

## [0.3.21] — 2026-04-07

- **[wrapper]** Remove dead `--disable-blink-features=AutomationControlled` flag -- binary patch 009 already handles `navigator.webdriver` at source level
- **[wrapper]** Remove hardcoded GPU vendor/renderer flags -- binary auto-generates diverse, realistic GPU profiles from the fingerprint seed. Each seed gets a unique GPU instead of every user sharing the same one
- **[wrapper]** Allow `viewport=None` to disable viewport emulation in both Python and JS wrappers (thanks [@kitiho](https://github.com/kitiho), #107)
- **[wrapper]** Enable `geoip=True` in stealth test example to fix FingerprintJS detection
- **[meta]** Remove npm self-upgrade step in CI -- Node 22 ships with compatible npm
- **[docker]** Install `geoip2` in Docker image for GeoIP auto-detection support

## [0.3.20] — 2026-04-06

- **[binary]** Upgrade Linux x64 build to 145.0.7632.159.9 — 48 source-level C++ patches (up from 42)
- **[binary]** 6 new patches: WebRTC IP spoofing, proxy signal removal, network timing normalization, WebGL accuracy improvements
- **[binary]** New `--fingerprint-webrtc-ip` flag — spoof WebRTC ICE candidate IPs to match your proxy exit IP
- **[binary]** Proxy detection signals eliminated — timing, headers, and network metadata normalized when proxy is active
- **[binary]** WebGL rendering accuracy improvements for headed mode
- **[wrapper]** Auto-inject `--fingerprint-webrtc-ip` when `geoip=True` — uses resolved exit IP from GeoIP lookup
- **[wrapper]** Rewrite `cloakserve` as CDP multiplexer with per-connection fingerprint seeds and connection tracking
- **[wrapper]** Humanize keyboard improvements — better behavioral stealth for typing interactions (thanks [@evelaa123](https://github.com/evelaa123))
- **[meta]** Bump GitHub Actions dependencies

## [0.3.19] — 2026-03-30

- **[binary]** Upgrade Linux x64 build to 145.0.7632.159.8 — 42 source-level C++ patches (up from 33)
- **[binary]** 9 new fingerprint patches covering additional browser APIs and cross-platform consistency
- **[binary]** New `--fingerprint-noise` flag — disable noise injection while keeping deterministic fingerprint seed active
- **[binary]** Improved fingerprint noise reliability and determinism across all patched APIs
- **[binary]** Expanded platform-aware fingerprint spoofing for more realistic cross-platform profiles
- **[binary]** Font rendering and detection accuracy improvements for Windows profiles
- **[binary]** Removed experimental patches that caused compatibility issues with certain anti-bot systems
- **[binary]** Docker/VNC environment compatibility improvements
- **[wrapper]** Fix Playwright cleanup — `pw.stop()` now runs even if `browser.close()` raises or is cancelled (fixes #60, thanks [@dgtlmoon](https://github.com/dgtlmoon))
- **[meta]** Pin GitHub Actions to commit SHAs, add Dependabot for automated dependency updates

## [0.3.18] — 2026-03-15

- **[wrapper]** Fix welcome banner printing to stdout — now writes to stderr so it won't corrupt JSON output in programmatic usage (fixes #59)
- **[wrapper]** Fix `cloakserve` Docker WebGL by adding `--ignore-gpu-blocklist` flag
- **[docs]** Add Crawlee integration example
- **[meta]** Add GitHub issue template for bug reports

## [0.3.17] — 2026-03-15

- **[binary]** Windows x64 build upgraded to 145.0.7632.159.7 — 33 source-level C++ patches, matching Linux
- **[wrapper]** Auto-inject GPU blocklist bypass for headed mode and Windows — fixes WebGL/WebGPU on software GPUs in Docker/VNC (fixes #56)
- **[wrapper]** Add 8 framework integration examples (Scrapy, Crawlee, BrowserBase, etc.) and README integrations section

## [0.3.16] — 2026-03-14

- **[binary]** Linux arm64 build available — Raspberry Pi, AWS Graviton, Oracle Ampere now supported
- **[wrapper]** Add donate link to first-launch welcome banner

## [0.3.15] — 2026-03-13

- **[binary]** Upgrade Linux build to 145.0.7632.159.7 — 33 source-level C++ patches
- **[binary]** StorageBuckets API quota normalization — closes the last storage-based incognito detection vector
- **[wrapper]** Fix non-ASCII character support in humanized typing — Cyrillic, CJK, and emoji now type correctly (thanks [@evelaa123](https://github.com/evelaa123))

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
