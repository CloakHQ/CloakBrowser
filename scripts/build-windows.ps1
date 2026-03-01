# CloakBrowser Windows Build Script
# Run this on Windows 10/11 with admin privileges

# Requirements:
# - Windows 10/11 64-bit
# - 100GB free disk space (for Chromium source + build)
# - Visual Studio 2022 Build Tools
# - Git for Windows

# ============================================================================
# STEP 1: Install Prerequisites
# ============================================================================

# Install Chocolatey (if not installed)
# Run PowerShell as Administrator:
Set-ExecutionPolicy Bypass -Scope Process -Force
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))

# Install Visual Studio Build Tools 2022
choco install visualstudio2022buildtools -y
choco install visualstudio2022-workload-vctools -y

# Install Git
choco install git -y

# Restart PowerShell after VS installation

# ============================================================================
# STEP 2: Setup depot_tools
# ============================================================================

# Clone depot_tools
cd C:\
git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git C:\depot_tools

# Add to PATH (permanent)
[Environment]::SetEnvironmentVariable(
    "Path",
    $env:Path + ";C:\depot_tools",
    [EnvironmentVariableTarget]::User
)

# Restart PowerShell, then verify:
# gclient --version

# ============================================================================
# STEP 3: Fetch Chromium Source
# ============================================================================

# Create workspace
cd C:\
mkdir CloakBrowserBuild
cd CloakBrowserBuild

# Set environment
$env:DEPOT_TOOLS_WIN_TOOLCHAIN = 0

# Fetch Chromium (this takes 30-60 minutes)
fetch --no-history chromium

# ============================================================================
# STEP 4: Apply Stealth Patches
# ============================================================================

cd chromium\src

# List your patches here (copy .patch files to patches\ folder)
# git apply ..\patches\*.patch

# ============================================================================
# STEP 5: Configure Build
# ============================================================================

# Generate build configuration
gn gen out\Release --args="
is_official_build = true
is_debug = false
target_os = `""win`""
target_cpu = `""x64`""
chrome_pgo_phase = 1
use_thin_lto = true
"

# ============================================================================
# STEP 6: Build (takes 2-4 hours)
# ============================================================================

# Build Chrome
autoninja -C out\Release chrome

# ============================================================================
# STEP 7: Package
# ============================================================================

cd out\Release
tar -czvf cloakbrowser-win32-x64.tar.gz chrome.exe *.dll *.bin *.pak *.dat locales\

# Output: C:\CloakBrowserBuild\chromium\src\out\Release\cloakbrowser-win32-x64.tar.gz
