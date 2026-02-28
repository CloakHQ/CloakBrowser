# Windows CDP Support - Learnings

## Research Findings (Task 1)

### Platform Detection Implementation

**Python (cloakbrowser/config.py):**
- Lines 53-58: SUPPORTED_PLATFORMS dict - maps (system, machine) to platform tag
- Line 62: AVAILABLE_PLATFORMS set - only linux-x64, darwin-arm64, darwin-x64
- Lines 65-75: get_platform_tag() - uses platform.system() + platform.machine()
- Lines 99-108: get_binary_path() - handles Darwin vs else (Linux)
- Lines 111-127: check_platform_available() - shows "Windows builds are coming soon"

**JavaScript (js/src/config.ts):**
- Lines 18-23: SUPPORTED_PLATFORMS Record
- Line 27: AVAILABLE_PLATFORMS Set
- Lines 29-47: getPlatformTag() - uses process.platform + process.arch
- Lines 62-68: getBinaryPath() - handles darwin vs else

### CDP Implementation
- No explicit CDP setup needed - Playwright handles implicitly
- Browser launch uses playwright.chromium.launch() with executable_path
- Stealth flags passed via args parameter

### Key Modification Points
| File | Line | Change |
|------|------|--------|
| config.py | 53-58 | Add Windows to SUPPORTED_PLATFORMS |
| config.py | 62 | Add win32-x64 to AVAILABLE_PLATFORMS |
| config.py | 103-108 | Add Windows branch for .exe |
| config.ts | 18-23 | Add Windows to SUPPORTED_PLATFORMS |
| config.ts | 27 | Add win32-x64 to AVAILABLE_PLATFORMS |
| config.ts | 64-67 | Add Windows branch for .exe |

## Decisions Made
- Keep AVAILABLE_PLATFORMS with win32-x64 since we want users to be able to use it (with their own binary or after building)
- CDP works via Playwright's built-in CDP handling - no special changes needed
- Binary naming: cloakbrowser-win32-x64.tar.gz

## Issues/Gotchas
- Windows requires .exe extension in binary path
- Need to handle Windows cache directory properly (~/.cloakbrowser works)
- Platform.system() returns "Windows" not "win32" in Python
- process.platform returns "win32" in Node.js


## Implementation Changes (Task 2 - js/src/config.ts)

### Changes Made

1. **SUPPORTED_PLATFORMS** (lines 16-23): Added `win32-x64` and `win32-arm64`
2. **AVAILABLE_PLATFORMS** (line 27): Added `win32-x64`
3. **getPlatformTag()** (lines 39-48): Added Windows detection with else clause for unsupported platforms
4. **getBinaryPath()** (lines 68-70): Added Windows branch to return `chrome.exe`
5. **checkPlatformAvailable()** (lines 74-87): Updated error message to remove "Windows builds are coming soon"
6. **getDefaultStealthArgs()** (lines 145-176): Added `isWindows` detection and Windows-specific fingerprint platform

### Technical Notes
- `process.platform` returns `"win32"` on Windows (both x64 and ARM64)
- `process.arch` returns `"x64"` or `"arm64"` on Windows
- Binary should be `chrome.exe` on Windows
- Windows fingerprint platform set to `"windows"` (native, no spoofing needed)

### Build Verification
- TypeScript build passes for config.ts syntax
- Remaining errors are environment issues (missing @types/node, playwright-core, puppeteer-core dependencies)
