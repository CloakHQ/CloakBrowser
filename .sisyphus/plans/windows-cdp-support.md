# Plan: Windows 10/11 Support + CDP for CloakBrowser

> **Objective**:## TL;DR

 Add Windows 10/11 native support to CloakBrowser so users can build/run stealth Chromium with full CDP functionality on Windows.
> 
> **Deliverables**:
> - Updated platform detection for Windows (win32, x64, arm64)
> - Modified binary path resolver for Windows paths
> - CDP integration tests
> - Build script/guidance for patched Chromium on Windows
> - Windows-specific examples
> 
> **Estimated Effort**: Medium-Large
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Platform detection → Binary paths → CDP tests → Documentation

---

## Context

### Original Request
User wants to build and run CloakBrowser on Windows 10/11 with CDP (Chrome DevTools Protocol) support for debugging, network monitoring, and remote control.

### Current State
- **Supported platforms**: Linux (x64, arm64), macOS (x64, arm64)
- **Windows**: Not supported - platform detection blocks it
- **CDP**: Works on existing platforms but needs verification on Windows

### Technical Requirements
1. **Platform detection**: Add Windows (win32) support in `config.py` (Python) and `config.ts` (JS)
2. **Binary paths**: Windows uses different path structure (`chrome.exe` not `chrome`, no `.app` bundle)
3. **CDP**: Ensure Playwright/Puppeteer CDP connections work on Windows
4. **Build**: Document or script the process to build patched Chromium for Windows

---

## Work Objectives

### Core Objective
Enable CloakBrowser to:
1. Run natively on Windows 10/11 (x64/arm64)
2. Support full CDP functionality
3. Allow users to build their own patched Chromium for Windows

### Concrete Deliverables
- [ ] Updated `cloakbrowser/config.py` with Windows platform support
- [ ] Updated `js/src/config.ts` with Windows platform support
- [ ] Modified binary path resolver for Windows (.exe paths)
- [ ] CDP integration tests (network, console, runtime)
- [ ] Build guide/script for patched Chromium on Windows
- [ ] Windows-specific examples

### Definition of Done
- [ ] `python -c "from cloakbrowser import launch; b=launch(); print(b.new_page().goto('https://example.com')); b.close()"` works on Windows
- [ ] CDP connection test passes on Windows
- [ ] Unit tests for Windows path detection pass
- [ ] Documentation for building patched Chromium on Windows

### Must Have
- Windows platform detection (win32-x64, win32-arm64)
- Correct binary path resolution for Windows
- CDP functionality preserved/enhanced

### Must NOT Have
- Breaking changes to existing Linux/macOS functionality
- Hardcoded paths that break other platforms

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES (pytest for Python, vitest for JS)
- **Automated tests**: YES (TDD approach)
- **Framework**: pytest (Python), vitest (JS)
- **Agent-Executed QA**: YES - each task includes verification scenarios

### QA Policy
Every task includes agent-executed QA scenarios saved to `.sisyphus/evidence/`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation - can run in parallel):
├── Task 1: Research current platform detection + CDP implementation
├── Task 2: Update Python config.py for Windows detection
├── Task 3: Update JS config.ts for Windows detection  
├── Task 4: Add Windows binary path resolver
└── Task 5: Add unit tests for Windows platform detection

Wave 2 (Core implementation):
├── Task 6: Update Python browser.py for Windows CDP
├── Task 7: Update JS playwright.ts for Windows CDP
├── Task 8: Add CDP integration tests (Python)
├── Task 9: Add CDP integration tests (JS)
└── Task 10: Test existing functionality not broken

Wave 3 (Documentation & build):
├── Task 11: Create Windows build guide for patched Chromium
├── Task 12: Add Windows examples
├── Task 13: Update README with Windows status
└── Task 14: Final integration verification
```

### Dependency Matrix
- **1**: — — 2-5
- **2**: 1 — 6, 10, 5
- **3**: 1 — 7, 10, 5
- **4**: 1, 2 — 6, 7
- **5**: 2, 3 — 14
- **6**: 2, 4 — 8, 10
- **7**: 3, 4 — 9, 10
- **8**: 6 — 14
- **9**: 7 — 14
- **10**: 2, 3, 4, 6, 7 — 14
- **11**: 5 — 12, 13
- **12**: 11 — 14
- **13**: 11 — 14
- **14**: 5, 8, 9, 10, 12, 13 — —

---

## TODOs

- [ ] 1. **Research current platform detection + CDP implementation**

  **What to do**:
  - Analyze `cloakbrowser/config.py` platform detection logic
  - Analyze `js/src/config.ts` platform detection logic
  - Research how CDP connects in current implementation
  - Find where binary paths are resolved

  **Recommended Agent Profile**:
  - **Category**: `explore`
  - **Skills**: None needed
  - Reason: Need to understand current implementation before modifying

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 2, 3, 4, 5
  - **Blocked By**: None (can start immediately)

  **References**:
  - `cloakbrowser/config.py` - Platform detection (lines 53-75)
  - `js/src/config.ts` - Platform detection (lines 18-47)
  - `cloakbrowser/browser.py` - Browser launch + CDP setup

  **Acceptance Criteria**:
  - [ ] Document current platform detection flow
  - [ ] Document how CDP is configured in launch

  **QA Scenarios**:
  - N/A (research task)

  **Commit**: NO

---

- [x] 2. **Update Python config.py for Windows detection**

  **What to do**:
  - Add Windows to SUPPORTED_PLATFORMS dict
  - Add win32-x64, win32-arm64 to AVAILABLE_PLATFORMS (or mark as "build required")
  - Update get_platform_tag() for Windows
  - Update get_binary_path() for Windows (.exe extension)

  **Must NOT do**:
  - Remove existing Linux/macOS support
  - Change existing function signatures

  **Recommended Agent Profile**:
  - **Category**: `ultrabrain`
  - **Skills**: None needed
  - Reason: Straightforward platform addition, similar to existing patterns

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 3)
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 6, 10, 5
  - **Blocked By**: Task 1

  **References**:
  - `cloakbrowser/config.py:53-108` - Platform detection pattern

  **Acceptance Criteria**:
  - [ ] `get_platform_tag()` returns "win32-x64" on Windows x64
  - [ ] `get_binary_path()` returns correct Windows path
  - [ ] Existing tests still pass

  **QA Scenarios**:
  ```
  Scenario: Platform detection on Windows
    Tool: Bash
    Preconditions: Running on Windows 10/11 x64
    Steps:
      1. Run: python -c "from cloakbrowser.config import get_platform_tag; print(get_platform_tag())"
    Expected Result: "win32-x64"
    Failure Indicators: RuntimeError about unsupported platform
    Evidence: .sisyphus/evidence/task2-platform-windows.png

  Scenario: Binary path on Windows
    Tool: Bash  
    Preconditions: Running on Windows 10/11 x64
    Steps:
      1. Run: python -c "from cloakbrowser.config import get_binary_path; print(get_binary_path())"
    Expected Result: Path ending with "chrome.exe"
    Failure Indicators: Path ends with "chrome" (Linux style)
    Evidence: .sisyphus/evidence/task2-path-windows.png
  ```

  **Evidence to Capture**:
  - [ ] Screenshot of platform tag output
  - [ ] Screenshot of binary path output

  **Commit**: YES
  - Message: `feat(windows): add Windows platform detection`
  - Files: `cloakbrowser/config.py`

---

- [x] 3. **Update JS config.ts for Windows detection**

  **What to do**:
  - Add Windows to SUPPORTED_PLATFORMS in JS
  - Add win32-x64 to AVAILABLE_PLATFORMS
  - Update getPlatformTag() for Windows
  - Update getBinaryPath() for Windows

  **Must NOT do**:
  - Remove existing platform support

  **Recommended Agent Profile**:
  - **Category**: `ultrabrain`
  - **Skills**: None needed

  **Parallelization**:
  - **Can Run In Parallel**: YES (with Task 2)
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 7, 10, 5
  - **Blocked By**: Task 1

  **References**:
  - `js/src/config.ts:18-68` - JS platform detection pattern

  **Acceptance Criteria**:
  - [ ] `getPlatformTag()` returns "win32-x64" on Windows x64
  - [ ] `getBinaryPath()` returns correct Windows path

  **QA Scenarios**:
  ```
  Scenario: JS platform detection on Windows
    Tool: Bash
    Preconditions: Running on Windows 10/11 x64
    Steps:
      1. Run: node -e "const {getPlatformTag}=require('./js/dist/config.js'); console.log(getPlatformTag())"
    Expected Result: "win32-x64"
    Failure Indicators: Error about unsupported platform
    Evidence: .sisyphus/evidence/task3-platform-js.png
  ```

  **Commit**: YES
  - Message: `feat(windows): add Windows platform detection (JS)`
  - Files: `js/src/config.ts`

---

- [ ] 4. **Add Windows binary path resolver**

  **What to do**:
  - Update binary path logic for Windows-specific directory structure
  - Handle Windows cache directory (~/.cloakbrowser/)
  - Update download URL generation for Windows

  **Must NOT do**:
  - Break Linux/macOS path resolution

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: None needed

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Tasks 6, 7
  - **Blocked By**: Tasks 1, 2, 3

  **References**:
  - `cloakbrowser/config.py:93-108` - Binary path functions
  - `js/src/config.ts:52-68` - JS binary path functions

  **Acceptance Criteria**:
  - [ ] Binary paths work on Windows
  - [ ] Download URLs generated correctly for Windows

  **Commit**: YES
  - Message: `feat(windows): add Windows binary path resolution`
  - Files: `cloakbrowser/config.py`, `js/src/config.ts`

---

- [x] 5. **Add unit tests for Windows platform detection**

  **What to do**:
  - Add pytest tests for Windows platform detection
  - Add vitest tests for Windows in JS
  - Mock Windows environment for testing

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: None needed

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1
  - **Blocks**: Task 14
  - **Blocked By**: Tasks 2, 3

  **References**:
  - `tests/test_update.py` - Existing test patterns
  - `js/tests/config.test.ts` - JS test patterns

  **Acceptance Criteria**:
  - [ ] Tests pass for Windows detection
  - [ ] Tests don't break existing platforms

  **Commit**: YES
  - Message: `test(windows): add Windows platform detection tests`
  - Files: `tests/test_platform.py` (new), `js/tests/platform.test.ts` (new)

---

- [x] 6. **Update Python browser.py for Windows CDP**

  **What to do**:
  - Verify CDP connection works with Windows paths
  - Check proxy handling for Windows
  - Ensure ignore_default_args works on Windows

  **Must  - Change Linux NOT do**:
/macOS behavior

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: None needed

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: Tasks 8, 10
  - **Blocked By**: Tasks 2, 4

  **References**:
  - `cloakbrowser/browser.py:27-81` - Launch function

  **Acceptance Criteria**:
  - [ ] CDP can connect on Windows
  - [ ] Browser launches without errors

  **Commit**: YES
  - Message: `feat(windows): ensure CDP works on Windows`
  - Files: `cloakbrowser/browser.py`

---

- [x] 7. **Update JS playwright.ts for Windows CDP**

  **What to do**:
  - Verify CDP works with Windows paths in JS
  - Check proxy handling for Windows

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: Tasks 9, 10
  - **Blocked By**: Tasks 3, 4

  **Commit**: YES
  - Message: `feat(windows): ensure CDP works on Windows (JS)`
  - Files: `js/src/playwright.ts`

---

- [x] 8. **Add CDP integration tests (Python)**

  **What to do**:
  - Write tests for CDP functionality:
    - Network request interception
    - Console log capture
    - Runtime evaluation
  - Test on Windows if possible, or mock

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: None needed

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 14
  - **Blocked By**: Task 6

  **References**:
  - `tests/test_stealth.py` - Test patterns with live pages

  **Acceptance Criteria**:
  - [ ] CDP network test passes
  - [ ] CDP console test passes

  **QA Scenarios**:
  ```
  Scenario: CDP Network monitoring
    Tool: Python (pytest)
    Preconditions: Windows with binary installed
    Steps:
      1. Launch browser with CDP enabled
      2. Create page, navigate to example.com
      3. Capture network requests via CDP
    Expected Result: Network requests captured
    Evidence: .sisyphus/evidence/task8-cdp-network.png

  Scenario: CDP Console capture
    Tool: Python (pytest)
    Preconditions: Windows with binary installed
    Steps:
      1. Launch browser with CDP
      2. Execute JS that logs to console
      3. Capture console messages via CDP
    Expected Result: Console logs captured
    Evidence: .sisyphus/evidence/task8-cdp-console.png
  ```

  **Commit**: YES
  - Message: `test(cdp): add CDP integration tests for Windows`
  - Files: `tests/test_cdp.py` (new)

---

- [x] 9. **Add CDP integration tests (JS)**

  **What to do**:
  - Write CDP tests for JS/TypeScript
  - Test network, console, runtime

  **Recommended Agent Profile**:
  - **Category**: `deep`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 14
  - **Blocked By**: Task 7

  **Commit**: YES
  - Message: `test(cdp): add CDP integration tests (JS)`
  - Files: `js/tests/cdp.test.ts` (new)

---

- [x] 10. **Test existing functionality not broken**

  **What to do**:
  - Run full Python test suite
  - Run full JS test suite
  - Verify Linux/macOS still work

  **Recommended Agent Profile**:
  - **Category**: `quick`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2
  - **Blocks**: Task 14
  - **Blocked By**: Tasks 2, 3, 4, 6, 7

  **Acceptance Criteria**:
  - [ ] All Python tests pass
  - [ ] All JS tests pass
  - [ ] No regressions

  **Commit**: NO (verification only)

---

- [x] 11. **Create Windows build guide for patched Chromium**

  **What to do**:
  - Document how to build patched Chromium on Windows
  - Include prerequisites (VS Build Tools, depot_tools)
  - Document the patch process
  - Document how to integrate with CloakBrowser

  **Recommended Agent Profile**:
  - **Category**: `writing`
  - **Skills**: None needed

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: Tasks 12, 13
  - **Blocked By**: Task 5

  **Acceptance Criteria**:
  - [ ] Guide covers full build process
  - [ ] Guide includes integration steps with CloakBrowser

  **Commit**: YES
  - Message: `docs(windows): add Windows build guide`
  - Files: `docs/WINDOWS_BUILD.md` (new)

---

- [x] 12. **Add Windows examples**

  **What to do**:
  - Create Windows-specific examples
  - Include CDP examples
  - Include proxy examples for Windows

  **Recommended Agent Profile**:
  - **Category**: `writing`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 14
  - **Blocked By**: Task 11

  **Commit**: YES
  - Message: `feat(windows): add Windows examples`
  - Files: `examples/windows_*.py`, `js/examples/windows_*.ts`

---

- [x] 13. **Update README with Windows status**

  **What to do**:
  - Mark Windows as supported
  - Add Windows to platform table
  - Link to build guide

  **Recommended Agent Profile**:
  - **Category**: `writing`

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3
  - **Blocks**: Task 14
  - **Blocked By**: Task 11

  **Commit**: YES
  - Message: `docs: update Windows support status`
  - Files: `README.md`, `js/README.md`

---

- [x] 14. **Final integration verification**

  **What to do**:
  - Run all verification scenarios
  - Confirm all acceptance criteria met
  - Final review of changes

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`

  **Parallelization**:
  - **Can Run In Parallel**: NO (final verification)
  - **Parallel Group**: Wave FINAL
  - **Blocked By**: Tasks 5, 8, 9, 10, 12, 13

  **Acceptance Criteria**:
  - [ ] All tasks complete
  - [ ] All tests pass
  - [ ] Documentation complete

---

## Final Verification Wave

- [ ] F1. **Platform detection audit** — Verify Windows detection works in both Python and JS
- [ ] F2. **CDP functionality test** — Verify CDP connections work on Windows
- [ ] F3. **Regression test** — Verify Linux/macOS still work
- [ ] F4. **Documentation completeness** — Verify all docs are present and accurate

---

## Commit Strategy

Batch commits by wave:
- Wave 1: `feat(windows): add Windows platform support (config layer)`
- Wave 2: `feat(windows): add CDP support for Windows`
- Wave 3: `docs(windows): add Windows build guide and examples`

---

## Success Criteria

### Verification Commands
```bash
# Python
python -c "from cloakbrowser import launch; b=launch(); print(b.new_page().goto('https://example.com')); b.close()"

# JS
cd js && npx tsx examples/basic-playwright.ts
```

### Final Checklist
- [ ] Windows platform detection works
- [ ] Binary paths resolve correctly on Windows
- [ ] CDP functionality verified
- [ ] All tests pass
- [ ] Build guide complete
- [ ] README updated
