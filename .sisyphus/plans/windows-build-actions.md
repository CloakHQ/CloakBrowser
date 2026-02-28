# Plan: Implement Windows Binary Build in GitHub Actions

## TL;DR
Implement full Windows (win32-x64) binary build pipeline in GitHub Actions to produce stealth Chromium.

## Context
- Current workflow has Windows build job but it's incomplete
- Need to build stealth Chromium from source with patches
- Binary will be used by CloakBrowser on Windows

## Work Objectives

### Core Objective
Create a working Windows binary build that:
1. Fetches Chromium source code
2. Applies stealth patches
3. Builds Chromium with Visual Studio
4. Packages the binary as tar.gz
5. Uploads as artifact

### Must Have
- Complete Windows build job in workflow
- Proper VS Build Tools setup
- Depot tools installation
- Chromium source fetch
- Stealth patch application (placeholder)
- Build and package
- Artifact upload

### Must NOT Have
- Break existing CI (lint, tests)

---

## TODOs

- [ ] 1. **Fix Windows build workflow job**

  What to do:
  - Fix YAML syntax errors in build-windows job
  - Add proper depot_tools setup for Windows
  - Add VS Build Tools configuration
  - Add Chromium source fetch
  - Add stealth patch placeholder
  - Add build commands
  - Add packaging

  Acceptance Criteria:
  - [ ] Workflow runs without syntax errors
  - [ ] Depot tools installed
  - [ ] Chromium source fetched

- [ ] 2. **Test Windows build manually**

  What to do:
  - Trigger workflow dispatch
  - Monitor build progress
  - Fix any issues

  Acceptance Criteria:
  - [ ] Binary built successfully
  - [ ] Artifact uploaded
