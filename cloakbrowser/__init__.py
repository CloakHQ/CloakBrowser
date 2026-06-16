"""cloakbrowser — Stealth Chromium that passes every bot detection test.

Drop-in Playwright replacement with source-level fingerprint patches.

Usage:
    from cloakbrowser import launch

    browser = launch()
    page = browser.new_page()
    page.goto("https://protected-site.com")
    browser.close()
"""

from .browser import launch, launch_async, launch_context, launch_context_async, launch_persistent_context, launch_persistent_context_async, ProxySettings, build_args, maybe_resolve_geoip
from .config import CHROMIUM_VERSION, get_default_stealth_args
from .download import binary_info, check_for_update, clear_cache, ensure_binary
from ._version import __version__

# Lazy-loaded optional modules (human + pxbypass)
def __getattr__(name):
    if name == "HumanConfig":
        from .human.config import HumanConfig
        globals()["HumanConfig"] = HumanConfig
        return HumanConfig
    if name == "resolve_human_config":
        from .human.config import resolve_config
        globals()["resolve_human_config"] = resolve_config
        return resolve_config
    if name == "PxConfig":
        from .pxbypass.config import PxConfig
        globals()["PxConfig"] = PxConfig
        return PxConfig
    if name == "detect_px":
        from .pxbypass import detect_px
        globals()["detect_px"] = detect_px
        return detect_px
    if name == "solve_px":
        from .pxbypass import solve_px
        globals()["solve_px"] = solve_px
        return solve_px
    raise AttributeError(f"module 'cloakbrowser' has no attribute {name}")

__all__ = [
    "launch",
    "launch_async",
    "launch_context",
    "launch_context_async",
    "launch_persistent_context",
    "launch_persistent_context_async",
    "ensure_binary",
    "clear_cache",
    "binary_info",
    "check_for_update",
    "CHROMIUM_VERSION",
    "get_default_stealth_args",
    "build_args",
    "maybe_resolve_geoip",
    "ProxySettings",
    "HumanConfig",
    "resolve_human_config",
    "PxConfig",
    "detect_px",
    "solve_px",
    "__version__",
]