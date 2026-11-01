"""undetected-chromedriver + CloakBrowser: double stealth layer.

undetected-chromedriver patches ChromeDriver detection signals,
CloakBrowser patches the browser fingerprints at the C++ level.

Requires: pip install undetected-chromedriver cloakbrowser
"""

import undetected_chromedriver as uc

from cloakbrowser import binary_info
from cloakbrowser.config import get_default_stealth_args
from cloakbrowser.download import ensure_binary

binary_path = ensure_binary()
stealth_args = get_default_stealth_args()
chromium_major = int(binary_info()["version"].split(".")[0])  # the build just ensured

options = uc.ChromeOptions()
options.binary_location = binary_path
options.add_argument("--headless")
for arg in stealth_args:
    options.add_argument(arg)

driver = uc.Chrome(options=options, version_main=chromium_major)

driver.get("https://example.com")
print(f"undetected-chromedriver + CloakBrowser: {driver.title}")

# Verify stealth
result = driver.execute_script("""
    return {
        webdriver: navigator.webdriver,
        plugins: navigator.plugins.length,
        platform: navigator.platform,
        hardwareConcurrency: navigator.hardwareConcurrency,
    }
""")
print(f"Stealth checks: {result}")

driver.quit()
