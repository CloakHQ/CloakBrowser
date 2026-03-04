"""Persistent context example: cookies and localStorage survive across sessions."""

from cloakbrowser import launch_persistent_context

PROFILE_DIR = "./my-profile"

# Session 1 — set some state
print("=== Session 1: Setting state ===")
ctx = launch_persistent_context(PROFILE_DIR, headless=False)
page = ctx.new_page()
page.goto("https://example.com")
page.evaluate("document.cookie = 'session=abc123; path=/; max-age=3600'")
page.evaluate("localStorage.setItem('user', 'returning')")
print(f"Cookie: {page.evaluate('document.cookie')}")
ls_val = page.evaluate("localStorage.getItem('user')")
print(f"localStorage: {ls_val}")
ctx.close()

# Session 2 — state is restored
print("\n=== Session 2: Verifying persistence ===")
ctx = launch_persistent_context(PROFILE_DIR, headless=False)
page = ctx.new_page()
page.goto("https://example.com")
print(f"Cookie: {page.evaluate('document.cookie')}")
ls_val = page.evaluate("localStorage.getItem('user')")
print(f"localStorage: {ls_val}")
ctx.close()

print("\nDone!")
