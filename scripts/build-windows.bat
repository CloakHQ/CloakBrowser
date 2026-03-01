@echo off
REM CloakBrowser Windows Build - Run as Administrator
REM Requirements: 100GB disk space, VS 2022 Build Tools

echo ========================================
echo CloakBrowser Windows Build Script
echo ========================================

REM STEP 1: Install Prerequisites
echo [1/7] Installing prerequisites...
choco install visualstudio2022buildtools -y
choco install git -y

REM STEP 2: Setup depot_tools
echo [2/7] Setting up depot_tools...
cd C:\
git clone https://chromium.googlesource.com/chromium/tools/depot_tools.git C:\depot_tools
set PATH=%PATH%;C:\depot_tools

REM STEP 3: Fetch Chromium
echo [3/7] Fetching Chromium source (30-60 min)...
cd C:\CloakBrowserBuild
set DEPOT_TOOLS_WIN_TOOLCHAIN=0
fetch --no-history chromium

REM STEP 4: Apply patches
echo [4/7] Applying stealth patches...
cd chromium\src
git apply ..\patches\*.patch

REM STEP 5: Configure
echo [5/7] Configuring build...
gn gen out\Release --args="is_official_build=true is_debug=false target_os=""win"" target_cpu=""x64"""

REM STEP 6: Build
echo [6/7] Building Chromium (2-4 hours)...
autoninja -C out\Release chrome

REM STEP 7: Package
echo [7/7] Packaging...
cd out\Release
powershell -Command "Compress-Archive -Path chrome.exe -DestinationPath cloakbrowser-win32-x64.tar.gz"

echo Done! Output: out\Release\cloakbrowser-win32-x64.tar.gz
pause
