# Persistent Context, Extensions & Viewports

CloakBrowser supports persistent contexts (for reusing cookies, localStorage, IndexedDB, and extensions across runs) as well as light-weight ephemeral contexts.

---

## 1. Persistent Context (`launch_persistent_context`)

Persistent profiles save all browser data directly to a local directory on disk. This is highly useful for **staying logged in**, accumulating service worker caches, and **bypassing incognito detection** (which reduces BrowserScan trust scores by 10%).

```python
from cloakbrowser import launch_persistent_context

# Browser session details will be saved inside the "./my-profile" folder
ctx = launch_persistent_context(
    "./my-profile",
    headless=True,
    proxy="http://user:pass@proxy:8080"
)

page = ctx.new_page()
page.goto("https://example.com/login")
# ... perform login ...
ctx.close()  # Cookies, cache, and session variables are saved.

# Next run: Reuses session data seamlessly (no login required)
ctx = launch_persistent_context("./my-profile", headless=True)
page = ctx.new_page()
page.goto("https://example.com/dashboard")  # Already authenticated!
ctx.close()
```

---

## 2. Ephemeral Context & Storage State

For lightweight scraping tasks where a full profile directory is not needed, you can use `launch_context()` to spin up an in-memory browser and manually save/restore state files:

```python
from cloakbrowser import launch_context

# Save cookies + localStorage to JSON
context = launch_context()
page = context.new_page()
page.goto("https://example.com/login")
# ... log in ...
context.storage_state(path="session_state.json")
context.close()

# Restore session in a new instance
context2 = launch_context(storage_state="session_state.json")
page2 = context2.new_page()
page2.goto("https://example.com/dashboard")  # Already logged in
context2.close()
```

---

## 3. Chrome Extensions

Loading Chrome extensions requires **headed mode** (`headless=False`) due to a native Chromium design limitation:

```python
from cloakbrowser import launch_persistent_context

ctx = launch_persistent_context(
    "./profile-with-extensions",
    headless=False,  # Extensions must run in headed mode!
    extension_paths=[
        "./extensions/my-unpacked-adblocker",  # Path to folder containing manifest.json
        "./extensions/another-plugin",
    ]
)
page = ctx.new_page()
page.goto("https://example.com")
```

---

## 4. Viewport & Color Scheme Stealth

Standard Playwright uses CDP commands to emulate viewport resolutions and color schemes. These emulation commands generate detectable JavaScript quirks that anti-bots track.

CloakBrowser solves this by configuring viewport and color scheme parameters at the native launch level, ensuring zero leaks.

### Bypassing Emulation (Use Native Resolution)
Real desktop users rarely run emulated viewports. For maximum stealth (especially against Akamai and DataDome), disable viewport emulation. This causes the browser window to match the exact OS size:

```python
from cloakbrowser import launch_context

context = launch_context(
    viewport=None,  # Disables emulation entirely, window inherits native OS size
)
```

### Color Scheme Control
Force light or dark color schemes to match your system preferences:

```python
context = launch_context(
    color_scheme="dark",  # Forces light/dark modes natively
)
```
