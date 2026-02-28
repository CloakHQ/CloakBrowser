"""Windows example: launch stealth browser with custom binary path.

This example demonstrates how to use CloakBrowser on Windows 10/11
with a custom (self-built) Chromium binary.
"""

import os

# Option 1: Set environment variable before importing cloakbrowser
# Replace with your actual Chrome path
os.environ["CLOAKBROWSER_BINARY_PATH"] = r"C:\path\to\your\chromium\build\chrome.exe"

# Option 2: Alternatively, you can check platform first:
# import platform
# if platform.system() == "Windows":
#     os.environ["CLOAKBROWSER_BINARY_PATH"] = r"C:\path\to\chrome.exe"

from cloakbrowser import launch, binary_info

# Print binary info to verify
info = binary_info()
print(f"Binary: {info['binary_path']}")
print(f"Installed: {info['installed']}")

# Launch the browser
browser = launch(headless=False)
page = browser.new_page()

# Navigate to a test page
page.goto("https://example.com")
print(f"Title: {page.title()}")
print(f"URL: {page.url}")

# Close browser
browser.close()
print("Done!")
