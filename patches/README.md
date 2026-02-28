# Stealth Patches for Chromium

This directory should contain the C++ source patches applied to Chromium for stealth functionality.

## Required Patches

The stealth patches modify Chromium source code to:
- Patch `navigator.webdriver` to return `false`
- Modify canvas fingerprint generation
- Patch WebGL renderer strings
- Modify audio context fingerprinting
- Adjust font enumeration
- Hide headless detection signals

## Patch Format

Patches should be in standard `git apply` format:
```bash
git diff > stealth.patch
```

## Building Without Patches

For CI testing, the workflow can skip patches if this directory is empty or contains only this README.

## Obtaining Patches

Contact the CloakBrowser team or check the official build infrastructure for the patch files.
