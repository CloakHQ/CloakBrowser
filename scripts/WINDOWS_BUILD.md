# Building CloakBrowser on Windows

## Requirements

- **Windows 10/11 64-bit**
- **100GB free disk space** (Chromium source + build artifacts)
- **Visual Studio 2022 Build Tools** with C++ workload
- **Git for Windows**

## Quick Start

### Option 1: PowerShell Script

```powershell
# Run PowerShell as Administrator
cd C:\
git clone https://github.com/CloakHQ/CloakBrowser.git
cd CloakBrowser\scripts
.\build-windows.ps1
```

### Option 2: Batch Script

```cmd
# Run Command Prompt as Administrator
cd C:\CloakBrowser\scripts
build-windows.bat
```

## Manual Build Steps

### 1. Install Visual Studio Build Tools 2022

Download from: https://visualstudio.microsoft.com/downloads/

Select:
- Visual Studio Build Tools 2022
- Individual components: Microsoft.VisualStudio.Workload.VCTools

### 2. Install depot_tools

```cmd
cd C:\
git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git
set PATH=%PATH%;C:\depot_tools
```

### 3. Fetch Chromium

```cmd
cd C:\
mkdir CloakBrowserBuild
cd CloakBrowserBuild
set DEPOT_TOOLS_WIN_TOOLCHAIN=0
fetch --no-history chromium
```

### 4. Apply Stealth Patches

Copy your `.patch` files to `chromium\src\patches\` folder, then:

```cmd
cd chromium\src
git apply patches\*.patch
```

### 5. Configure Build

```cmd
cd chromium\src
gn gen out\Release --args="is_official_build=true is_debug=false target_os=""win"" target_cpu=""x64"""
```

### 6. Build

```cmd
autoninja -C out\Release chrome
```

**Expected time: 2-4 hours** (depending on hardware)

### 7. Package

```cmd
cd out\Release
tar -czvf cloakbrowser-win32-x64.tar.gz chrome.exe
```

## Output

Binary: `chromium\src\out\Release\cloakbrowser-win32-x64.tar.gz`

## Notes

- Build time depends on CPU/RAM. Recommended: 32GB RAM, 16+ cores
- Disable antivirus during build for faster compilation
- Use `--jobs` flag with autoninja for parallel builds: `autoninja -C out\Release chrome -j 16`
