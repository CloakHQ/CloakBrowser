# Plan: Add GitHub Actions Build/Deploy Workflow for Windows & macOS

## TL;DR
Add CI/CD workflow to automatically build stealth Chromium binaries on Windows and macOS, test packages, and deploy to PyPI/npm.

## Context
- Current state: Manual release process for pre-built binaries only
- **Requirement**: Build stealth Chromium on **Windows (win32-x64)** and **macOS (darwin-arm64, darwin-x64)**

## Work Objectives

### Core Objective
Create GitHub Actions workflow that:
1. Builds stealth Chromium on **Windows runner** → uploads win32-x64 binary
2. Builds stealth Chromium on **macOS runners** → uploads darwin-arm64, darwin-x64 binaries
3. Runs tests on Python (3.10, 3.11, 3.12) and Node.js (20)
4. Lints code
5. Publishes packages to PyPI and npm on tag

### Must Have
- **Windows build job**: `runs-on: windows-latest`, builds stealth Chromium
- **macOS build jobs**: `runs-on: macos-latest` and `runs-on: macos-13` (arm64 + x64)
- Test matrix: Ubuntu, macOS, Windows
- Python version matrix: 3.10, 3.11, 3.12
- Lint checks

### Must NOT Have
- Breaking existing release-binary.yml workflow

---

## TODOs

- [x] 1. **Create build-deploy.yml with Windows & macOS builds**

  **What to do**:
  - Create `.github/workflows/build-deploy.yml`
  - Add **Windows build** (`windows-latest`):
    - Install build dependencies (VS Build Tools, depot_tools)
    - Fetch Chromium source
    - Apply stealth patches
    - Build chromium
    - Upload as artifact: `cloakbrowser-win32-x64.tar.gz`
  - Add **macOS arm64 build** (`macos-latest` - Apple Silicon):
    - Build stealth Chromium
    - Upload as artifact: `cloakbrowser-darwin-arm64.tar.gz`
  - Add **macOS x64 build** (`macos-13` - Intel):
    - Build stealth Chromium
    - Upload as artifact: `cloakbrowser-darwin-x64.tar.gz`
  - Add Python test matrix (ubuntu, macos, windows; python 3.10-3.12)
  - Add JS test (node 20)
  - Add lint
  - Add PyPI publish (on tag v*)
  - Add npm publish (on tag v*)

  **Acceptance Criteria**:
  - [ ] Workflow runs on Windows and builds binary
  - [ ] Workflow runs on macOS (both arm64 and x64) and builds binaries
  - [ ] Artifacts uploaded with correct platform tags

  **Commit**: YES
  - Message: `ci: add Windows & macOS build workflow`
  - Files: `.github/workflows/build-deploy.yml`
