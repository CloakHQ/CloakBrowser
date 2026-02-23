"""cloakbrowser — Stealth Chromium that passes every bot detection test.

Drop-in Playwright replacement with source-level fingerprint patches.

Usage:
    from cloakbrowser import launch

    browser = launch()
    page = browser.new_page()
    page.goto("https://protected-site.com")
    browser.close()
"""

from .browser import launch, launch_async, launch_context
from .config import CHROMIUM_VERSION, get_default_stealth_args
from .download import binary_info, clear_cache, ensure_binary
from ._version import __version__

__all__ = [
    "launch",
    "launch_async",
    "launch_context",
    "ensure_binary",
    "clear_cache",
    "binary_info",
    "CHROMIUM_VERSION",
    "get_default_stealth_args",
    "__version__",
]
