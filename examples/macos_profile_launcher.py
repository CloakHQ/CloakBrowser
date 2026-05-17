"""Per-profile macOS desktop launcher: one .app shortcut per CloakBrowser profile.

Use this when you want native macOS double-click launchers for each profile
(e.g. ``Cloak Profile A.app``, ``Cloak Profile B.app``) that open the browser
directly with a fixed fingerprint seed and persistent profile dir — bypassing
the Manager web UI.

Setup (per profile):

  1. Copy this file to e.g. ``~/cloak-profiles/launch-profile-a.py`` and edit
     PROFILE_NAME / PROFILE_SEED below.
  2. Open Automator → New → "Application" → search "Run Shell Script" and add::

         cd ~/cloak-profiles && /usr/bin/env python3 launch-profile-a.py

  3. Save to Desktop as ``Cloak Profile A.app``.
  4. Double-click the .app to launch this profile.

The fixed PROFILE_SEED makes the fingerprint deterministic across runs — the
same ``--fingerprint=<seed>`` value is rebuilt every launch — and the
persistent profile dir keeps cookies, localStorage, and cache between sessions.
"""

from cloakbrowser import launch_persistent_context

PROFILE_NAME = "profile-a"
PROFILE_SEED = 12345  # stable across runs; change per profile for a distinct identity

PROFILE_DIR = f"./cloak-{PROFILE_NAME}"

print(f"Launching CloakBrowser profile '{PROFILE_NAME}' (seed={PROFILE_SEED})...", flush=True)
ctx = launch_persistent_context(
    PROFILE_DIR,
    headless=False,
    args=[f"--fingerprint={PROFILE_SEED}"],
)
page = ctx.pages[0] if ctx.pages else ctx.new_page()
page.goto("https://example.com")

# Keep the browser open until the user closes it.
page.wait_for_event("close", timeout=0)
ctx.close()
