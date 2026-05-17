"""Example: Installing and using Chrome extensions with CloakBrowser.

This example demonstrates how to automatically install and inject Chrome extensions
when launching a persistent profile, similar to anti-detect browsers like GoLogin.

The extensions are downloaded from the Chrome Web Store and stored in the profile,
so they persist across sessions.

Note: Extensions only run in headed mode (headless=False), which is set automatically
when extensions are provided.

This example downloads MetaMask extension (~10MB) and navigates to example.com.
First run may take 2-3 minutes (downloads Chromium binary on first use).
Subsequent runs are instant with cached extensions.
"""

from cloakbrowser import launch_persistent_context

# Chrome extension IDs
METAMASK_ID = "nkbihfbeogaeaoehlefnkodbefgpgknn"

PROFILE_DIR = "./profile-with-extensions"

try:
    print("[1] Launching stealth browser with MetaMask extension...")
    print(f"    Profile: {PROFILE_DIR}")
    print(f"    Extension: MetaMask ({METAMASK_ID})")
    print("    (First run downloads Chromium ~535MB, takes 1-3 minutes)\n")
    
    ctx = launch_persistent_context(
        PROFILE_DIR,
        extensions=[METAMASK_ID],
        headless=False,  # Extensions require headed mode
    )
    print("    ✓ Browser launched successfully!")
    print("    ✓ MetaMask extension installed and loaded\n")

    print("[2] Creating new page and navigating to example.com...")
    page = ctx.new_page()
    page.goto("https://example.com", wait_until="load")
    title = page.title()
    print(f"    ✓ Page loaded. Title: '{title}'\n")

    print("[3] Checking if MetaMask extension is available...")
    has_metamask = page.evaluate(
        "typeof window.ethereum !== 'undefined'"
    )
    print(f"    MetaMask window.ethereum available: {has_metamask}\n")

    print("[4] Gathering extension info...")
    # List files in the profile's extensions directory
    from pathlib import Path
    ext_dir = Path(PROFILE_DIR) / "extensions" / METAMASK_ID
    if ext_dir.exists():
        files = list(ext_dir.glob("*"))[:3]  # Show first 3 files
        print(f"    Extension cached at: {ext_dir}")
        print(f"    Number of files: {len(list(ext_dir.glob('**/*')))}")
        print(f"    Sample files: {[f.name for f in files]}\n")

    print("[5] Closing browser...")
    ctx.close()
    print("    ✓ Browser closed\n")

    print("=" * 60)
    print("SUCCESS! Extension workflow complete.\n")
    print("On next launch with the same profile:")
    print("- Extensions are loaded from cache (instant)")
    print("- No re-download needed")
    print("- All profile state (cookies, localStorage) persists\n")
    
    print("Run the example again to see instant startup!")
    print("=" * 60)

except Exception as e:
    print(f"\nERROR: {e}\n")
    print("Troubleshooting:")
    print("- Internet connection: Required for first-run Chromium download")
    print("- Extension download: Required first time, then cached")
    print("- Disk space: Needs ~550MB for Chromium + extension files")
    print("- Valid IDs: Extensions must be from Chrome Web Store")
    import traceback
    traceback.print_exc()

