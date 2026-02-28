# CloakBrowser Implementation Workflow

This document explains how to implement changes in this repository and how to verify they work.

## 1) Project map (what lives where)

- Python package: `cloakbrowser/`
  - Public API export: `cloakbrowser/__init__.py`
  - Browser launch layer: `cloakbrowser/browser.py`
  - Binary download/update/cache: `cloakbrowser/download.py`
  - Platform/config/stealth args: `cloakbrowser/config.py`
- Python tests: `tests/`
- JavaScript package: `js/`
  - Public exports: `js/src/index.ts`
  - Playwright launcher: `js/src/playwright.ts`
  - Puppeteer launcher: `js/src/puppeteer.ts`
  - Binary download/update/cache: `js/src/download.ts`
  - Platform/config/stealth args: `js/src/config.ts`
- JavaScript tests: `js/tests/`
- Binary release workflow: `.github/workflows/release-binary.yml`

## 2) Core architecture (how it works)

1. User calls `launch()` (Python or JS).
2. `ensure_binary()` runs first to resolve a usable Chromium binary:
   - Uses `CLOAKBROWSER_BINARY_PATH` when set.
   - Otherwise checks cache under `~/.cloakbrowser/`.
   - Otherwise downloads archive from `https://cloakbrowser.dev/chromium-v<version>/cloakbrowser-<platform>.tar.gz`.
3. Launcher passes default stealth flags (`--fingerprint=...` and platform-specific flags).
4. Browser starts with automation defaults reduced (for example `--enable-automation` is removed in launcher options).
5. Background update check may run (if enabled) and can prepare a newer binary for next launches.

## 3) Implementation workflow

Use this flow for every change.

### Step A: Locate affected surface

- Python-only API/behavior change: edit `cloakbrowser/*.py` and `tests/*.py`.
- JS-only API/behavior change: edit `js/src/*.ts` and `js/tests/*.ts`.
- Shared behavior change (download/version/proxy/flags): apply equivalent logic in both Python and JS implementations.

### Step B: Keep parity across Python and JS

When changing one side, check the matching module on the other side:

- `cloakbrowser/browser.py` <-> `js/src/playwright.ts` and/or `js/src/puppeteer.ts`
- `cloakbrowser/download.py` <-> `js/src/download.ts`
- `cloakbrowser/config.py` <-> `js/src/config.ts`

If parity intentionally differs, document the reason in README/docs.

### Step C: Update tests with behavior changes

- Python tests:
  - Launch behavior: `tests/test_launch.py`
  - Proxy parsing: `tests/test_proxy.py`
  - Update/version logic: `tests/test_update.py`
  - Live stealth checks: `tests/test_stealth.py` (`@pytest.mark.slow`)
- JS tests:
  - Config behavior: `js/tests/config.test.ts`
  - Launch info/integration gate: `js/tests/launch.test.ts`
  - Proxy parsing: `js/tests/proxy.test.ts`
  - Update/version logic: `js/tests/update.test.ts`

### Step D: Update docs/examples when API changes

Check and update:

- Root docs: `README.md`
- JS docs: `js/README.md`
- Examples: `examples/` and `js/examples/`

## 4) Verification workflow (how to know it works)

Run the smallest useful set first, then full checks.

### Python checks

```bash
python -m pytest tests/test_update.py tests/test_proxy.py tests/test_launch.py
```

Optional live checks (network/proxy sensitive, slower):

```bash
python -m pytest tests/test_stealth.py -m slow
```

Skip live tests in normal CI/local fast loop:

```bash
python -m pytest -m "not slow"
```

### JavaScript checks

```bash
cd js
npm run typecheck
npm run test
npm run build
```

Note: `js/tests/launch.test.ts` integration block is skipped unless `CLOAKBROWSER_BINARY_PATH` is set.

### Smoke checks (manual)

- Python smoke:

```bash
python examples/basic.py
```

- JS smoke:

```bash
cd js
npx tsx examples/basic-playwright.ts
```

## 5) Binary/version update workflow

When moving to a new Chromium build:

1. Update version constants:
   - `cloakbrowser/config.py` -> `CHROMIUM_VERSION`
   - `js/src/config.ts` -> `CHROMIUM_VERSION`
2. Verify URL format still resolves in both implementations (`get_download_url` / `getDownloadUrl`).
3. Run update/version tests:
   - `tests/test_update.py`
   - `js/tests/update.test.ts`
4. Validate download + launch on supported platforms.
5. Trigger binary release workflow `.github/workflows/release-binary.yml` with:
   - `tag` (example: `chromium-v145.0.7718.0`)
   - `title`
   - `patch_count`

## 6) Done criteria (definition of done)

A change is done when all are true:

- Behavior is implemented in the correct module(s).
- Python and JS parity is maintained (or intentionally documented).
- Tests are updated and passing for affected areas.
- Build/typecheck passes for JS changes.
- README/examples updated for any user-facing API change.
- Smoke run succeeds on at least one path (Python or JS, ideally both).
