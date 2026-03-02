# Changelog

All notable changes to CloakBrowser — wrapper and binary — are documented here.

Changes are tagged: **[wrapper]** for Python/JS wrapper, **[binary]** for Chromium patches.

---

## [0.3.0] — Unreleased

Chromium v145 upgrade. 26 fingerprint patches (up from 16). New download verification and fallback system. Pending: macOS v145 binary builds.

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
