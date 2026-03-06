"""cloakbrowser — Stealth Chromium that passes every bot detection test.

Drop-in Playwright replacement with source-level fingerprint patches.

Usage:
    from cloakbrowser import launch

    browser = launch()
    page = browser.new_page()
    page.goto("https://protected-site.com")
    browser.close()
"""

from .browser import launch, launch_async, launch_context, launch_persistent_context, launch_persistent_context_async, ProxySettings
from .config import CHROMIUM_VERSION, get_default_stealth_args
from .download import binary_info, check_for_update, clear_cache, ensure_binary
from ._version import __version__

# Human-like behavioral layer (optional)
from .human.config import HumanConfig, resolve_config as resolve_human_config

__all__ = [
    "launch",
    "launch_async",
    "launch_context",
    "launch_persistent_context",
    "launch_persistent_context_async",
    "ensure_binary",
    "clear_cache",
    "binary_info",
    "check_for_update",
    "CHROMIUM_VERSION",
    "get_default_stealth_args",
    "ProxySettings",
    "HumanConfig",
    "resolve_human_config",
    "__version__",
]

