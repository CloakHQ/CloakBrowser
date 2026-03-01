"""Check reCAPTCHA v3 score with stealth browser.

Visits Google's reCAPTCHA demo page and extracts the score.
Expected: 0.9 (human-level) with cloakbrowser.
Default Playwright typically scores 0.1-0.3.
"""

import time

from cloakbrowser import launch

browser = launch(headless=True)
page = browser.new_page()

# Google's official reCAPTCHA v3 demo
page.goto("https://recaptcha-demo.appspot.com/recaptcha-v3-request-scores.php")
page.wait_for_load_state("networkidle")

# Click to trigger reCAPTCHA scoring
button = page.query_selector("button")
if button:
    button.click()
    time.sleep(3)

# Extract score from page
content = page.content()
print("Page loaded. Check the score in the response.")
print(f"URL: {page.url}")

# Take screenshot as proof
page.screenshot(path="recaptcha_score.png")
print("Screenshot saved: recaptcha_score.png")

browser.close()
