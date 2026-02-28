# Plan: Fix CI Lint Errors and Windows Test Failures

## TL;DR
Fix ruff lint errors (unused imports) and investigate Windows test failures in the CI workflow.

## Context
- CI workflow ran but failed on:
  1. **Lint**: 7 ruff errors - unused imports in Python files
  2. **Windows tests**: Failed - need investigation

## Work Objectives

### Must Fix
- Remove unused imports causing ruff failures
- Fix unused variable assignments in tests
- Investigate and fix Windows test failures

### Must NOT Have
- Break existing functionality
- Introduce new lint errors

---

## TODOs

- [ ] 1. **Fix ruff lint errors**

  What to do:
  - Run `ruff check cloakbrowser/ tests/ --fix`
  - Commit fixes

  Acceptance Criteria:
  - [ ] ruff passes with no errors

- [ ] 2. **Investigate Windows test failures**

  What to do:
  - Check what failed in Windows tests
  - Fix platform-specific issues

  Acceptance Criteria:
  - [ ] Windows tests pass

- [ ] 3. **Re-run CI**

  What to do:
  - Push fixes
  - Verify CI passes

  Acceptance Criteria:
  - [ ] All CI jobs pass
