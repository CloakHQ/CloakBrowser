"""Core browser launch functions for cloakbrowser.

Provides launch() and launch_async() — thin wrappers around Playwright
that use our patched stealth Chromium binary instead of stock Chromium.

Usage:
    from cloakbrowser import launch

    browser = launch()
    page = browser.new_page()
    page.goto("https://protected-site.com")
    browser.close()
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Literal, TypedDict
from urllib.parse import quote, unquote, urlparse, urlunparse

from .config import (
    DEFAULT_VIEWPORT,
    IGNORE_DEFAULT_ARGS,
    get_default_stealth_args,
    normalize_requested_version,
)
from .download import ensure_binary
from .human.config import HumanConfigOverrides, HumanPreset
from .widevine import seed_widevine_hint

logger = logging.getLogger("cloakbrowser")


# Sentinel to distinguish "viewport not provided" from "viewport=None" (disable emulation)
_VIEWPORT_UNSET = object()


def _default_no_viewport(browser: Any) -> None:
    """Default ``new_page()``/``new_context()`` to ``no_viewport=True``.

    ``launch()`` returns a raw Playwright ``Browser``; a bare ``browser.new_page()``
    would otherwise inherit Playwright's emulated 1280x720 viewport, producing
    ``outerWidth < innerWidth`` — a physically impossible window (bot tell). We wrap
    the two factory methods so pages track the real OS window instead. ``setdefault``
    only: an explicit ``viewport`` or ``no_viewport`` from the caller is never
    overridden (Playwright rejects passing both). Applied for headed launches only.
    Composes under humanize's ``patch_browser`` (apply this first).
    """
    orig_new_context = browser.new_context
    orig_new_page = browser.new_page

    def _patched_new_context(**kwargs: Any) -> Any:
        if "viewport" not in kwargs:
            kwargs.setdefault("no_viewport", True)
        return orig_new_context(**kwargs)

    def _patched_new_page(**kwargs: Any) -> Any:
        if "viewport" not in kwargs:
            kwargs.setdefault("no_viewport", True)
        return orig_new_page(**kwargs)

    browser.new_context = _patched_new_context
    browser.new_page = _patched_new_page


def _default_no_viewport_async(browser: Any) -> None:
    """Async variant of :func:`_default_no_viewport`."""
    orig_new_context = browser.new_context
    orig_new_page = browser.new_page

    async def _patched_new_context(**kwargs: Any) -> Any:
        if "viewport" not in kwargs:
            kwargs.setdefault("no_viewport", True)
        return await orig_new_context(**kwargs)

    async def _patched_new_page(**kwargs: Any) -> Any:
        if "viewport" not in kwargs:
            kwargs.setdefault("no_viewport", True)
        return await orig_new_page(**kwargs)

    browser.new_context = _patched_new_context
    browser.new_page = _patched_new_page


def _resolve_context_viewport(viewport: Any, headless: bool) -> dict[str, Any]:
    """Return the viewport kwarg for a context.

    Headed: no emulated viewport so the page tracks the real window (CDP viewport
    emulation forces outerWidth < innerWidth = a physically impossible window =
    bot tell). Headless: a fixed ``DEFAULT_VIEWPORT`` stays coherent (outer == inner)
    and keeps dimensions deterministic. Explicit ``viewport`` / ``None`` honored.
    """
    if viewport is _VIEWPORT_UNSET:
        return {"viewport": DEFAULT_VIEWPORT} if headless else {"no_viewport": True}
    if viewport is None:
        return {"no_viewport": True}
    return {"viewport": viewport}


def _drop_conflicting_viewport(context_kwargs: dict[str, Any], kwargs: dict[str, Any]) -> None:
    """Playwright rejects passing both ``viewport`` and ``no_viewport``. ``viewport`` is a
    named parameter (never in ``**kwargs``), so the only conflict is a caller passing
    ``no_viewport`` via ``**kwargs`` alongside an explicit ``viewport`` — the explicit
    ``no_viewport`` wins; drop the viewport so Playwright doesn't error.
    """
    if "no_viewport" in kwargs and "viewport" in context_kwargs:
        logger.debug("Both viewport and no_viewport requested; no_viewport (kwargs) wins")
        context_kwargs.pop("viewport", None)


def _resolve_timezone(timezone: str | None, kwargs: dict[str, Any]) -> str | None:
    """Accept both timezone and timezone_id — either works, no warning."""
    if "timezone_id" in kwargs:
        if timezone is None:
            timezone = kwargs.pop("timezone_id")
        else:
            kwargs.pop("timezone_id")
    return timezone


def _check_removed_kwargs(kwargs: dict[str, Any]) -> None:
    """Raise a clear error for removed parameters that now fall into **kwargs."""
    if "backend" in kwargs:
        raise TypeError(
            "The 'backend' parameter has been removed — patchright is no longer "
            "supported and stock Playwright is the only backend. Remove the argument."
        )


class _ProxySettingsRequired(TypedDict):
    server: str


class ProxySettings(_ProxySettingsRequired, total=False):
    """Playwright-compatible proxy configuration."""

    bypass: str
    username: str
    password: str


def launch(
    headless: bool = True,
    proxy: str | ProxySettings | None = None,
    args: list[str] | None = None,
    stealth_args: bool = True,
    timezone: str | None = None,
    locale: str | None = None,
    geoip: bool = False,
    humanize: bool = False,
    human_preset: HumanPreset = "default",
    human_config: HumanConfigOverrides | None = None,
    extension_paths: list[str] | None = None,
    license_key: str | None = None,
    browser_version: str | None = None,
    **kwargs: Any,
) -> Any:
    """Launch stealth Chromium browser. Returns a Playwright Browser object.

    Args:
        headless: Run in headless mode (default True).
        proxy: Proxy URL string or Playwright proxy dict.
            String: 'http://user:pass@proxy:8080' (credentials auto-extracted).
            Dict: {"server": "http://proxy:8080", "bypass": ".google.com", ...}
            — passed directly to Playwright.
        args: Additional Chromium CLI arguments to pass.
        extension_paths: List of Chrome extension paths to load.
        stealth_args: Include default stealth fingerprint args (default True).
            Set to False if you want to pass your own --fingerprint flags.
        timezone: IANA timezone (e.g. 'America/New_York'). Sets --fingerprint-timezone binary flag.
        locale: BCP 47 locale (e.g. 'en-US'). Sets --lang binary flag.
        geoip: Auto-detect timezone/locale from proxy IP (default False).
            Requires ``pip install cloakbrowser[geoip]``. Downloads ~70 MB
            GeoLite2-City database on first use.  Explicit timezone/locale
            always override geoip results.
        humanize: Enable human-like mouse, keyboard, scroll behavior (default False).
        human_preset: Humanize preset — 'default' or 'careful' (default 'default').
        human_config: Custom humanize config mapping to override preset values.
        **kwargs: Passed directly to playwright.chromium.launch().

    Returns:
        Playwright Browser object — use same API as playwright.chromium.launch().

    Example:
        >>> from cloakbrowser import launch
        >>> browser = launch()
        >>> page = browser.new_page()
        >>> page.goto("https://bot.incolumitas.com")
        >>> print(page.title())
        >>> browser.close()
    """
    _check_removed_kwargs(kwargs)

    from playwright.sync_api import sync_playwright

    binary_path = ensure_binary(license_key=license_key, browser_version=browser_version)
    timezone, locale, exit_ip = maybe_resolve_geoip(geoip, proxy, timezone, locale)
    proxy_kwargs, proxy_extra_args = _resolve_proxy_config(proxy, browser_version)
    args = _resolve_webrtc_args(args, proxy)
    if exit_ip and not (args and any(a.startswith("--fingerprint-webrtc-ip") for a in args)):
        args = list(args or [])
        args.append(f"--fingerprint-webrtc-ip={exit_ip}")

    chrome_args = build_args(stealth_args, (args or []) + proxy_extra_args, timezone=timezone, locale=locale, headless=headless, extension_paths=extension_paths)
    _maybe_warn_windows_fonts(chrome_args)

    logger.debug("Launching stealth Chromium (headless=%s, args=%d)", headless, len(chrome_args))

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path=binary_path,
        headless=headless,
        args=chrome_args,
        ignore_default_args=IGNORE_DEFAULT_ARGS,
        **proxy_kwargs,
        **kwargs,
    )

    # Patch close() to also stop the Playwright instance
    _original_close = browser.close

    def _close_with_cleanup() -> None:
        try:
            _original_close()
        finally:
            pw.stop()

    browser.close = _close_with_cleanup

    # Headed: default new_page()/new_context() to no_viewport so the page tracks the
    # real window (avoids the impossible-window tell). Headless keeps Playwright's
    # default viewport (coherent there). Apply before humanize so the wraps compose.
    if not headless:
        _default_no_viewport(browser)

    # Human-like behavioral patching
    if humanize:
        from .human import patch_browser
        from .human.config import resolve_config
        cfg = resolve_config(human_preset, human_config)
        patch_browser(browser, cfg)

    return browser


async def launch_async(  # noqa: C901
    headless: bool = True,
    proxy: str | ProxySettings | None = None,
    args: list[str] | None = None,
    stealth_args: bool = True,
    timezone: str | None = None,
    locale: str | None = None,
    geoip: bool = False,
    humanize: bool = False,
    human_preset: HumanPreset = "default",
    human_config: HumanConfigOverrides | None = None,
    extension_paths: list[str] | None = None,
    license_key: str | None = None,
    browser_version: str | None = None,
    **kwargs: Any,
) -> Any:
    """Async version of launch(). Returns a Playwright Browser object.

    Args:
        headless: Run in headless mode (default True).
        proxy: Proxy URL string or Playwright proxy dict (see launch() for details).
        args: Additional Chromium CLI arguments to pass.
        extension_paths: List of Chrome extension paths to load.
        stealth_args: Include default stealth fingerprint args (default True).
        timezone: IANA timezone (e.g. 'America/New_York'). Sets --fingerprint-timezone binary flag.
        locale: BCP 47 locale (e.g. 'en-US'). Sets --lang binary flag.
        geoip: Auto-detect timezone/locale from proxy IP (default False).
        humanize: Enable human-like mouse, keyboard, scroll behavior (default False).
        human_preset: Humanize preset — 'default' or 'careful' (default 'default').
        human_config: Custom humanize config mapping to override preset values.
        **kwargs: Passed directly to playwright.chromium.launch().

    Returns:
        Playwright Browser object (async API).

    Example:
        >>> import asyncio
        >>> from cloakbrowser import launch_async
        >>>
        >>> async def main():
        ...     browser = await launch_async()
        ...     page = await browser.new_page()
        ...     await page.goto("https://bot.incolumitas.com")
        ...     print(await page.title())
        ...     await browser.close()
        >>>
        >>> asyncio.run(main())
    """
    _check_removed_kwargs(kwargs)

    from playwright.async_api import async_playwright

    binary_path = ensure_binary(license_key=license_key, browser_version=browser_version)
    timezone, locale, exit_ip = maybe_resolve_geoip(geoip, proxy, timezone, locale)
    proxy_kwargs, proxy_extra_args = _resolve_proxy_config(proxy, browser_version)
    args = _resolve_webrtc_args(args, proxy)
    if exit_ip and not (args and any(a.startswith("--fingerprint-webrtc-ip") for a in args)):
        args = list(args or [])
        args.append(f"--fingerprint-webrtc-ip={exit_ip}")
    chrome_args = build_args(stealth_args, (args or []) + proxy_extra_args, timezone=timezone, locale=locale, headless=headless, extension_paths=extension_paths)
    _maybe_warn_windows_fonts(chrome_args)

    logger.debug("Launching stealth Chromium async (headless=%s, args=%d)", headless, len(chrome_args))

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        executable_path=binary_path,
        headless=headless,
        args=chrome_args,
        ignore_default_args=IGNORE_DEFAULT_ARGS,
        **proxy_kwargs,
        **kwargs,
    )

    # Patch close() to also stop the Playwright instance
    _original_close = browser.close

    async def _close_with_cleanup() -> None:
        try:
            await _original_close()
        finally:
            await pw.stop()

    browser.close = _close_with_cleanup

    # Headed: default new_page()/new_context() to no_viewport (see launch()).
    if not headless:
        _default_no_viewport_async(browser)

    # Human-like behavioral patching (async variant)
    if humanize:
        from .human import patch_browser_async
        from .human.config import resolve_config
        cfg = resolve_config(human_preset, human_config)
        patch_browser_async(browser, cfg)

    return browser


def launch_persistent_context(
    user_data_dir: str | os.PathLike,
    headless: bool = True,
    proxy: str | ProxySettings | None = None,
    args: list[str] | None = None,
    stealth_args: bool = True,
    user_agent: str | None = None,
    viewport: dict | None = _VIEWPORT_UNSET,
    locale: str | None = None,
    timezone: str | None = None,
    color_scheme: Literal["light", "dark", "no-preference"] | None = None,
    geoip: bool = False,
    humanize: bool = False,
    human_preset: HumanPreset = "default",
    human_config: HumanConfigOverrides | None = None,
    extension_paths: list[str] | None = None,
    license_key: str | None = None,
    browser_version: str | None = None,
    **kwargs: Any,
) -> Any:
    """Launch stealth browser with a persistent profile and return a BrowserContext.

    This persists cookies, localStorage, cache, and other browser state across
    sessions by storing them in ``user_data_dir``. Also avoids incognito detection
    by services like BrowserScan (-10% penalty).

    Args:
        user_data_dir: Path to the directory where browser profile data is stored.
            Created automatically if it doesn't exist. Reuse the same path across
            sessions to restore cookies, localStorage, cached credentials, etc.
        headless: Run in headless mode (default True).
        proxy: Proxy URL string or Playwright proxy dict (see launch() for details).
        args: Additional Chromium CLI arguments.
        extension_paths: List of Chrome extension paths to load.
        stealth_args: Include default stealth fingerprint args (default True).
        user_agent: Custom user agent string.
        viewport: Viewport size dict, e.g. {"width": 1920, "height": 1080}.
            Pass None to disable viewport emulation (use OS window size).
        locale: Browser locale, e.g. "en-US".
        timezone: IANA timezone (e.g. 'America/New_York').
        color_scheme: Color scheme preference — 'light', 'dark', or 'no-preference'.
            Default: None (uses Chromium default, which is 'light').
        geoip: Auto-detect timezone/locale from proxy IP (default False).
            Requires ``pip install cloakbrowser[geoip]``.
        humanize: Enable human-like mouse, keyboard, scroll behavior (default False).
        human_preset: Humanize preset — 'default' or 'careful' (default 'default').
        human_config: Custom humanize config mapping to override preset values.
        **kwargs: Passed directly to playwright.chromium.launch_persistent_context().

    Returns:
        Playwright BrowserContext object backed by a persistent profile.
        Call ``.close()`` when done — this also stops the Playwright instance.

    Example:
        >>> from cloakbrowser import launch_persistent_context
        >>> ctx = launch_persistent_context("./my-profile", headless=False)
        >>> page = ctx.new_page()
        >>> page.goto("https://protected-site.com")
        >>> ctx.close()  # Profile is saved; re-use path next run to restore state.
    """
    _check_removed_kwargs(kwargs)

    from playwright.sync_api import sync_playwright

    timezone = _resolve_timezone(timezone, kwargs)

    binary_path = ensure_binary(license_key=license_key, browser_version=browser_version)
    timezone, locale, exit_ip = maybe_resolve_geoip(geoip, proxy, timezone, locale)
    proxy_kwargs, proxy_extra_args = _resolve_proxy_config(proxy, browser_version)
    args = _resolve_webrtc_args(args, proxy)
    if exit_ip and not (args and any(a.startswith("--fingerprint-webrtc-ip") for a in args)):
        args = list(args or [])
        args.append(f"--fingerprint-webrtc-ip={exit_ip}")
    chrome_args = build_args(stealth_args, (args or []) + proxy_extra_args, timezone=timezone, locale=locale, headless=headless, extension_paths=extension_paths)
    _maybe_warn_windows_fonts(chrome_args)

    logger.debug(
        "Launching persistent stealth Chromium (headless=%s, user_data_dir=%s)",
        headless,
        user_data_dir,
    )

    # locale and timezone are set via binary flags (--lang, --fingerprint-timezone)
    # — NOT via Playwright context kwargs which use detectable CDP emulation.
    context_kwargs: dict[str, Any] = {}
    if user_agent:
        context_kwargs["user_agent"] = user_agent
    context_kwargs.update(_resolve_context_viewport(viewport, headless))
    if color_scheme:
        context_kwargs["color_scheme"] = color_scheme
    context_kwargs.update(kwargs)
    _drop_conflicting_viewport(context_kwargs, kwargs)

    seed_widevine_hint(user_data_dir, binary_path)

    pw = sync_playwright().start()
    context = pw.chromium.launch_persistent_context(
        user_data_dir=os.fspath(user_data_dir),
        executable_path=binary_path,
        headless=headless,
        args=chrome_args,
        ignore_default_args=IGNORE_DEFAULT_ARGS,
        **proxy_kwargs,
        **context_kwargs,
    )

    # Patch close() to also stop the Playwright instance
    _original_close = context.close

    def _close_with_cleanup() -> None:
        try:
            _original_close()
        finally:
            pw.stop()

    context.close = _close_with_cleanup

    # Human-like behavioral patching
    if humanize:
        from .human import patch_context
        from .human.config import resolve_config
        cfg = resolve_config(human_preset, human_config)
        patch_context(context, cfg)

    return context


async def launch_persistent_context_async(
    user_data_dir: str | os.PathLike,
    headless: bool = True,
    proxy: str | ProxySettings | None = None,
    args: list[str] | None = None,
    stealth_args: bool = True,
    user_agent: str | None = None,
    viewport: dict | None = _VIEWPORT_UNSET,
    locale: str | None = None,
    timezone: str | None = None,
    color_scheme: Literal["light", "dark", "no-preference"] | None = None,
    geoip: bool = False,
    humanize: bool = False,
    human_preset: HumanPreset = "default",
    human_config: HumanConfigOverrides | None = None,
    extension_paths: list[str] | None = None,
    license_key: str | None = None,
    browser_version: str | None = None,
    **kwargs: Any,
) -> Any:
    """Async version of launch_persistent_context().

    Launch stealth browser with a persistent profile and return a BrowserContext.
    This persists cookies, localStorage, cache, and other browser state across
    sessions by storing them in ``user_data_dir``.

    Args:
        user_data_dir: Path to the directory where browser profile data is stored.
            Created automatically if it doesn't exist.
        headless: Run in headless mode (default True).
        proxy: Proxy URL string or Playwright proxy dict (see launch() for details).
        args: Additional Chromium CLI arguments.
        extension_paths: List of Chrome extension paths to load.
        stealth_args: Include default stealth fingerprint args (default True).
        user_agent: Custom user agent string.
        viewport: Viewport size dict, e.g. {"width": 1920, "height": 1080}.
            Pass None to disable viewport emulation (use OS window size).
        locale: Browser locale, e.g. "en-US".
        timezone: IANA timezone (e.g. 'America/New_York').
        color_scheme: Color scheme preference — 'light', 'dark', or 'no-preference'.
        geoip: Auto-detect timezone/locale from proxy IP (default False).
        humanize: Enable human-like mouse, keyboard, scroll behavior (default False).
        human_preset: Humanize preset — 'default' or 'careful' (default 'default').
        human_config: Custom humanize config mapping to override preset values.
        **kwargs: Passed directly to playwright.chromium.launch_persistent_context().

    Returns:
        Playwright BrowserContext object backed by a persistent profile (async API).
        Call ``await .close()`` when done.

    Example:
        >>> import asyncio
        >>> from cloakbrowser import launch_persistent_context_async
        >>>
        >>> async def main():
        ...     ctx = await launch_persistent_context_async("./my-profile", headless=False)
        ...     page = await ctx.new_page()
        ...     await page.goto("https://protected-site.com")
        ...     await ctx.close()
        >>>
        >>> asyncio.run(main())
    """
    _check_removed_kwargs(kwargs)

    from playwright.async_api import async_playwright

    timezone = _resolve_timezone(timezone, kwargs)

    binary_path = ensure_binary(license_key=license_key, browser_version=browser_version)
    timezone, locale, exit_ip = maybe_resolve_geoip(geoip, proxy, timezone, locale)
    proxy_kwargs, proxy_extra_args = _resolve_proxy_config(proxy, browser_version)
    args = _resolve_webrtc_args(args, proxy)
    if exit_ip and not (args and any(a.startswith("--fingerprint-webrtc-ip") for a in args)):
        args = list(args or [])
        args.append(f"--fingerprint-webrtc-ip={exit_ip}")
    chrome_args = build_args(stealth_args, (args or []) + proxy_extra_args, timezone=timezone, locale=locale, headless=headless, extension_paths=extension_paths)
    _maybe_warn_windows_fonts(chrome_args)

    logger.debug(
        "Launching persistent stealth Chromium async (headless=%s, user_data_dir=%s)",
        headless,
        user_data_dir,
    )

    # locale and timezone are set via binary flags (--lang, --fingerprint-timezone)
    # — NOT via Playwright context kwargs which use detectable CDP emulation.
    context_kwargs: dict[str, Any] = {}
    if user_agent:
        context_kwargs["user_agent"] = user_agent
    context_kwargs.update(_resolve_context_viewport(viewport, headless))
    if color_scheme:
        context_kwargs["color_scheme"] = color_scheme
    context_kwargs.update(kwargs)
    _drop_conflicting_viewport(context_kwargs, kwargs)

    seed_widevine_hint(user_data_dir, binary_path)

    pw = await async_playwright().start()
    context = await pw.chromium.launch_persistent_context(
        user_data_dir=os.fspath(user_data_dir),
        executable_path=binary_path,
        headless=headless,
        args=chrome_args,
        ignore_default_args=IGNORE_DEFAULT_ARGS,
        **proxy_kwargs,
        **context_kwargs,
    )

    # Patch close() to also stop the Playwright instance
    _original_close = context.close

    async def _close_with_cleanup() -> None:
        try:
            await _original_close()
        finally:
            await pw.stop()

    context.close = _close_with_cleanup

    # Human-like behavioral patching (async variant)
    if humanize:
        from .human import patch_context_async
        from .human.config import resolve_config
        cfg = resolve_config(human_preset, human_config)
        patch_context_async(context, cfg)

    return context


def launch_context(
    headless: bool = True,
    proxy: str | ProxySettings | None = None,
    args: list[str] | None = None,
    stealth_args: bool = True,
    user_agent: str | None = None,
    viewport: dict | None = _VIEWPORT_UNSET,
    locale: str | None = None,
    timezone: str | None = None,
    color_scheme: Literal["light", "dark", "no-preference"] | None = None,
    geoip: bool = False,
    humanize: bool = False,
    human_preset: HumanPreset = "default",
    human_config: HumanConfigOverrides | None = None,
    extension_paths: list[str] | None = None,
    license_key: str | None = None,
    browser_version: str | None = None,
    **kwargs: Any,
) -> Any:
    """Launch stealth browser and return a BrowserContext with common options pre-set.

    Convenience function that creates a browser + context in one call.
    Useful for setting user agent, viewport, locale, etc.

    Args:
        headless: Run in headless mode (default True).
        proxy: Proxy URL string or Playwright proxy dict (see launch() for details).
        args: Additional Chromium CLI arguments.
        extension_paths: List of Chrome extension paths to load.
        stealth_args: Include default stealth fingerprint args (default True).
        user_agent: Custom user agent string.
        viewport: Viewport size dict, e.g. {"width": 1920, "height": 1080}.
            Pass None to disable viewport emulation (use OS window size).
        locale: Browser locale, e.g. "en-US".
        timezone: IANA timezone (e.g. 'America/New_York').
        color_scheme: Color scheme preference — 'light', 'dark', or 'no-preference'.
            Default: None (uses Chromium default, which is 'light').
        geoip: Auto-detect timezone/locale from proxy IP (default False).
        humanize: Enable human-like mouse, keyboard, scroll behavior (default False).
        human_preset: Humanize preset — 'default' or 'careful' (default 'default').
        human_config: Custom humanize config mapping to override preset values.
        **kwargs: Passed to browser.new_context().

    Returns:
        Playwright BrowserContext object.
    """
    _check_removed_kwargs(kwargs)

    timezone = _resolve_timezone(timezone, kwargs)

    # Resolve geoip BEFORE launch() to avoid double-resolution and ensure
    # resolved values flow to binary flags
    timezone, locale, exit_ip = maybe_resolve_geoip(geoip, proxy, timezone, locale)
    # Inject geoip exit IP for WebRTC spoofing (free — no extra HTTP call)
    if exit_ip and not (args and any(a.startswith("--fingerprint-webrtc-ip") for a in args)):
        args = list(args or [])
        args.append(f"--fingerprint-webrtc-ip={exit_ip}")
    # --fingerprint-timezone is process-wide (reads CommandLine in renderer),
    # so it applies to ALL contexts, not just the default one.
    # locale and timezone are set via binary flags only — no CDP emulation.
    browser = launch(headless=headless, proxy=proxy, args=args, stealth_args=stealth_args,
                     timezone=timezone, locale=locale, extension_paths=extension_paths,
                     license_key=license_key, browser_version=browser_version)

    context_kwargs: dict[str, Any] = {}
    if user_agent:
        context_kwargs["user_agent"] = user_agent
    context_kwargs.update(_resolve_context_viewport(viewport, headless))
    if color_scheme:
        context_kwargs["color_scheme"] = color_scheme
    context_kwargs.update(kwargs)
    _drop_conflicting_viewport(context_kwargs, kwargs)

    try:
        context = browser.new_context(**context_kwargs)
    except Exception:
        browser.close()
        raise

    # Patch close() to also close the browser (and its Playwright instance)
    _original_ctx_close = context.close

    def _close_context_with_cleanup() -> None:
        try:
            _original_ctx_close()
        finally:
            browser.close()

    context.close = _close_context_with_cleanup

    # Human-like behavioral patching
    if humanize:
        from .human import patch_context
        from .human.config import resolve_config
        cfg = resolve_config(human_preset, human_config)
        patch_context(context, cfg)

    return context


async def launch_context_async(
    headless: bool = True,
    proxy: str | ProxySettings | None = None,
    args: list[str] | None = None,
    stealth_args: bool = True,
    user_agent: str | None = None,
    viewport: dict | None = _VIEWPORT_UNSET,
    locale: str | None = None,
    timezone: str | None = None,
    color_scheme: Literal["light", "dark", "no-preference"] | None = None,
    geoip: bool = False,
    humanize: bool = False,
    human_preset: HumanPreset = "default",
    human_config: HumanConfigOverrides | None = None,
    extension_paths: list[str] | None = None,
    license_key: str | None = None,
    browser_version: str | None = None,
    **kwargs: Any,
) -> Any:
    """Async version of launch_context().

    Launch stealth browser and return a BrowserContext with common options pre-set.
    All extra kwargs are forwarded to ``browser.new_context()`` — use this for
    ``storage_state``, ``permissions``, ``extra_http_headers``, etc. without needing
    a persistent profile folder.

    Args:
        headless: Run in headless mode (default True).
        proxy: Proxy URL string or Playwright proxy dict (see launch() for details).
        args: Additional Chromium CLI arguments.
        extension_paths: List of Chrome extension paths to load.
        stealth_args: Include default stealth fingerprint args (default True).
        user_agent: Custom user agent string.
        viewport: Viewport size dict, e.g. {"width": 1920, "height": 1080}.
            Pass None to disable viewport emulation (use OS window size).
        locale: Browser locale, e.g. "en-US".
        timezone: IANA timezone (e.g. 'America/New_York').
        color_scheme: Color scheme preference — 'light', 'dark', or 'no-preference'.
        geoip: Auto-detect timezone/locale from proxy IP (default False).
        humanize: Enable human-like mouse, keyboard, scroll behavior (default False).
        human_preset: Humanize preset — 'default' or 'careful' (default 'default').
        human_config: Custom humanize config mapping to override preset values.
        **kwargs: Passed to browser.new_context() — e.g. storage_state, permissions.

    Returns:
        Playwright BrowserContext object (async API).
        Call ``await .close()`` when done — this also closes the underlying browser.

    Example:
        >>> import asyncio
        >>> from cloakbrowser import launch_context_async
        >>>
        >>> async def main():
        ...     # Load saved session (cookies, localStorage)
        ...     ctx = await launch_context_async(
        ...         headless=True,
        ...         storage_state="state.json",
        ...     )
        ...     page = await ctx.new_page()
        ...     await page.goto("https://example.com")
        ...     # Save state back
        ...     await ctx.storage_state(path="state.json")
        ...     await ctx.close()
        >>>
        >>> asyncio.run(main())
    """
    _check_removed_kwargs(kwargs)

    timezone = _resolve_timezone(timezone, kwargs)

    # Resolve geoip BEFORE launch_async() to avoid double-resolution and ensure
    # resolved values flow to binary flags
    timezone, locale, exit_ip = maybe_resolve_geoip(geoip, proxy, timezone, locale)
    if exit_ip and not (args and any(a.startswith("--fingerprint-webrtc-ip") for a in args)):
        args = list(args or [])
        args.append(f"--fingerprint-webrtc-ip={exit_ip}")
    # --fingerprint-timezone is process-wide (reads CommandLine in renderer),
    # so it applies to ALL contexts, not just the default one.
    # locale and timezone are set via binary flags only — no CDP emulation.
    browser = await launch_async(headless=headless, proxy=proxy, args=args, stealth_args=stealth_args,
                                 timezone=timezone, locale=locale, extension_paths=extension_paths,
                                 license_key=license_key, browser_version=browser_version)

    context_kwargs: dict[str, Any] = {}
    if user_agent:
        context_kwargs["user_agent"] = user_agent
    context_kwargs.update(_resolve_context_viewport(viewport, headless))
    if color_scheme:
        context_kwargs["color_scheme"] = color_scheme
    context_kwargs.update(kwargs)
    _drop_conflicting_viewport(context_kwargs, kwargs)

    # Catch BaseException (not just Exception) so that asyncio.CancelledError
    # triggers browser cleanup — otherwise the underlying Chromium process
    # leaks when the awaiting task is cancelled.
    try:
        context = await browser.new_context(**context_kwargs)
    except BaseException:
        try:
            await browser.close()
        except BaseException:
            pass
        raise

    # Patch close() to also close the browser (and its Playwright instance)
    _original_ctx_close = context.close

    async def _close_context_with_cleanup() -> None:
        try:
            await _original_ctx_close()
        finally:
            await browser.close()

    context.close = _close_context_with_cleanup

    # Human-like behavioral patching (async variant)
    if humanize:
        from .human import patch_context_async
        from .human.config import resolve_config
        cfg = resolve_config(human_preset, human_config)
        patch_context_async(context, cfg)

    return context


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_proxy_scheme(proxy_url: str) -> str:
    """Prepend http:// to schemeless proxy URLs so parsers can extract hostname."""
    return proxy_url if "://" in proxy_url else f"http://{proxy_url}"


def _assemble_proxy_url(
    scheme: str,
    host: str,
    port: int | None,
    enc_user: str,
    enc_pass: str | None,
    path: str = "",
    params: str = "",
    query: str = "",
    fragment: str = "",
) -> str:
    """Build a proxy URL from already-percent-encoded credentials and host parts.

    ``enc_pass is None`` means no password (no colon in userinfo). Empty string
    means present-but-empty (colon preserved). This mirrors the distinction
    urlparse makes between ``user@host`` and ``user:@host``.
    """
    if ":" in host:  # IPv6 literal — re-add brackets
        host = f"[{host}]"
    if enc_pass is not None:
        userinfo = f"{enc_user}:{enc_pass}@"
    elif enc_user:
        userinfo = f"{enc_user}@"
    else:
        userinfo = ""
    netloc = f"{userinfo}{host}"
    if port is not None:
        netloc += f":{port}"
    return urlunparse((scheme, netloc, path, params, query, fragment))


def _reconstruct_socks_url(proxy: ProxySettings) -> str:
    """Reconstruct a SOCKS5 URL with inline credentials from a Playwright proxy dict."""
    server = proxy.get("server", "")
    username = proxy.get("username", "")
    password = proxy.get("password", "")
    if not username:
        return server
    parsed = urlparse(server)
    enc_user = quote(username, safe="")
    # Dict convention: empty/missing password → no colon.
    enc_pass = quote(password, safe="") if password else None
    return _assemble_proxy_url(
        parsed.scheme, parsed.hostname or "", parsed.port,
        enc_user, enc_pass, parsed.path,
    )


def _normalize_socks_string_url(url: str) -> str:
    """Re-encode credentials in a SOCKS5 URL string so Chromium's parser doesn't
    truncate them at special chars like '='. Idempotent: pre-encoded input stays
    the same (decoded then re-encoded).

    Emits an INFO log when re-encoding actually changes the URL, so users who
    previously hit silent SOCKS5 fallback (#157) can see what the wrapper did.
    Silent on already-encoded inputs (no false-positive noise).

    On unparseable input (invalid port, broken IPv6 literal, etc.) logs a
    warning and returns the original string — preserves pre-fix pass-through
    behavior so Chromium's own error handling kicks in.
    """
    try:
        parsed = urlparse(url)
        # Accessing .port raises ValueError on invalid port strings.
        _ = parsed.port
    except ValueError as e:
        logger.warning("Malformed SOCKS5 proxy URL, passing through unchanged: %s", e)
        return url
    # Skip only if no credentials at all (username AND password both absent).
    # urlparse returns None for absent components, "" for present-but-empty.
    if parsed.username is None and parsed.password is None:
        return url
    raw_user = parsed.username or ""
    enc_user = quote(unquote(raw_user), safe="") if raw_user else ""
    # Preserve the colon separator when password component is present, even if
    # empty, so `user:@host` stays `user:@host`.
    if parsed.password is not None:
        raw_pass = parsed.password
        enc_pass = quote(unquote(raw_pass), safe="") if raw_pass else ""
    else:
        raw_pass = None
        enc_pass = None
    normalized = _assemble_proxy_url(
        parsed.scheme, parsed.hostname or "", parsed.port,
        enc_user, enc_pass,
        parsed.path, parsed.params, parsed.query, parsed.fragment,
    )
    # Compare credentials, not the full URL: urlparse cosmetically lowercases
    # scheme and hostname, so a full-string compare would falsely fire on
    # `socks5://USER:pass@HOST.com:1080` even when no encoding work happened.
    if enc_user != raw_user or enc_pass != raw_pass:
        logger.info(
            "Auto URL-encoded SOCKS5 proxy credentials (special characters "
            "detected). Pre-encode the URL to suppress this notice."
        )
    return normalized


def _extract_proxy_url(proxy: str | ProxySettings | None) -> str | None:
    """Extract and normalize proxy URL string from proxy param.

    For SOCKS5 dicts with separate username/password fields, reconstructs
    the full URL with inline credentials so SOCKS5 auth works.
    """
    if proxy is None:
        return None
    if isinstance(proxy, dict):
        server = proxy.get("server", "")
        if not server:
            return None
        if _is_socks_proxy(proxy):
            return _reconstruct_socks_url(proxy)
        return _ensure_proxy_scheme(server)
    return _ensure_proxy_scheme(proxy)


def maybe_resolve_geoip(
    geoip: bool,
    proxy: str | ProxySettings | None,
    timezone: str | None,
    locale: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Auto-fill timezone/locale from proxy IP when geoip is enabled.

    Returns ``(timezone, locale, exit_ip)``.  *exit_ip* is a free bonus
    from the geoip lookup (no extra HTTP call) — used for WebRTC spoofing.
    """
    if not geoip or not proxy:
        return timezone, locale, None

    from .geoip import resolve_proxy_exit_ip, resolve_proxy_geo_with_ip

    proxy_url = _extract_proxy_url(proxy)
    if not proxy_url:
        return timezone, locale, None

    # When both tz/locale are explicit, still resolve exit IP for WebRTC
    if timezone is not None and locale is not None:
        exit_ip = resolve_proxy_exit_ip(proxy_url)
        return timezone, locale, exit_ip

    geo_tz, geo_locale, exit_ip = resolve_proxy_geo_with_ip(proxy_url)
    if timezone is None:
        timezone = geo_tz
    if locale is None:
        locale = geo_locale
    return timezone, locale, exit_ip


def _resolve_webrtc_args(
    args: list[str] | None,
    proxy: str | ProxySettings | None,
) -> list[str] | None:
    """Replace --fingerprint-webrtc-ip=auto with the resolved proxy exit IP.

    Returns args unchanged if no ``auto`` value is present.
    """
    if not args:
        return args
    idx = None
    for i, a in enumerate(args):
        if a == "--fingerprint-webrtc-ip=auto":
            idx = i
            break
    if idx is None:
        return args
    proxy_url = _extract_proxy_url(proxy)
    if not proxy_url:
        logger.warning("--fingerprint-webrtc-ip=auto requires a proxy; removing flag")
        args = list(args)
        del args[idx]
        return args
    try:
        from .geoip import resolve_proxy_exit_ip
        exit_ip = resolve_proxy_exit_ip(proxy_url)
    except Exception:
        logger.warning("Failed to resolve proxy exit IP for WebRTC spoofing; removing --fingerprint-webrtc-ip=auto")
        args = list(args)
        del args[idx]
        return args
    if exit_ip:
        args = list(args)
        args[idx] = f"--fingerprint-webrtc-ip={exit_ip}"
    else:
        logger.warning("Could not resolve proxy exit IP for WebRTC spoofing; removing --fingerprint-webrtc-ip=auto")
        args = list(args)
        del args[idx]
    return args


def build_args(
    stealth_args: bool,
    extra_args: list[str] | None,
    timezone: str | None = None,
    locale: str | None = None,
    headless: bool = True,
    extension_paths: list[str] | None = None,
) -> list[str]:
    """Combine stealth args with user-provided args and locale flags.

    Deduplicates by flag key (everything before '=').
    Priority: stealth defaults < user args < dedicated params (timezone/locale).
    """
    seen: dict[str, str] = {}

    if stealth_args:
        for arg in get_default_stealth_args():
            seen[arg.split("=", 1)[0]] = arg

    # GPU blocklist bypass:
    # - Headed mode (all platforms): Chromium blocks WebGL on software GPUs
    #   in Docker/Xvfb. Flag lets SwiftShader serve WebGL. See issue #56.
    # - Windows (all modes): Chromium's GPU blocklist blocks WebGPU for the
    #   Microsoft Basic Render Driver. Dawn's adapter_blocklist bypass alone
    #   isn't enough — need this flag too. Linux doesn't need it.
    import platform as _platform
    if not headless or _platform.system() == "Windows":
        seen["--ignore-gpu-blocklist"] = "--ignore-gpu-blocklist"

    if extra_args:
        for arg in extra_args:
            key = arg.split("=", 1)[0]
            if key in seen:
                logger.debug("Arg override: %s -> %s", seen[key], arg)
            seen[key] = arg

    # Timezone/locale flags are independent of stealth_args — always inject when set
    if timezone:
        key = "--fingerprint-timezone"
        flag = f"{key}={timezone}"
        if key in seen:
            logger.debug("Arg override: %s -> %s", seen[key], flag)
        seen[key] = flag
    if locale:
        for key in ("--lang", "--fingerprint-locale"):
            flag = f"{key}={locale}"
            if key in seen:
                logger.debug("Arg override: %s -> %s", seen[key], flag)
            seen[key] = flag

    if extension_paths:
        abs_paths = [os.path.abspath(p) for p in extension_paths]
        ext_val = ",".join(abs_paths)

        seen["--load-extension"] = f"--load-extension={ext_val}"
        seen["--disable-extensions-except"] = (
            f"--disable-extensions-except={ext_val}"
        )
    elif "--load-extension" in seen and "--disable-extensions-except" not in seen:
        # Auto-add companion flag when --load-extension was provided via
        # extra_args but the companion --disable-extensions-except was not.
        # Without this, Playwright's default --disable-extensions blocks all
        # extensions. See CloakHQ/CloakBrowser-Manager#30 and #37.
        ext_val = seen["--load-extension"].split("=", 1)[1]
        seen["--disable-extensions-except"] = (
            f"--disable-extensions-except={ext_val}"
        )

    return list(seen.values())


# ---------------------------------------------------------------------------
# Windows-font mismatch warning (Linux only)
#
# On Linux the binary spoofs the Windows platform by default, but fonts come
# from the host OS. A font-less Linux box contradicts the Windows claim and
# font-fingerprinting anti-bot systems flag the mismatch. Warn once per
# environment. See docs/chrome40-fpjs-font-minimum-set-investigation.md.
# ---------------------------------------------------------------------------

# Microsoft-proprietary fonts that signal a real Windows install (absent from
# ttf-mscorefonts-installer). Keep in sync with issue #395 and
# docs/chrome40-fpjs-font-minimum-set-investigation.md.
_WINDOWS_FONT_TELLS = (
    "Segoe UI",
    "Segoe UI Light",
    "Calibri",
    "Marlett",
    "MS UI Gothic",
    "Franklin Gothic",
)

_font_warning_checked = False


def _windows_fonts_present() -> bool | None:
    """Probe for Windows fonts via fc-list.

    Tri-state: True if any tell-tale font is installed, False if none found,
    None if it can't be determined (fc-list missing or errored). Callers must
    NOT warn on None — only an explicit False means "no Windows fonts".
    """
    import subprocess
    try:
        result = subprocess.run(
            ["fc-list"], capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    listing = result.stdout.lower()
    return any(font.lower() in listing for font in _WINDOWS_FONT_TELLS)


def _maybe_warn_windows_fonts(chrome_args: list[str]) -> None:
    """Warn once when spoofing Windows on a Linux host with no Windows fonts.

    Best-effort and silent on error — never raises. Gated by an in-process flag
    plus a cache-dir marker so it fires at most once per environment. Suppress
    entirely with CLOAKBROWSER_SUPPRESS_FONT_WARNING.
    """
    global _font_warning_checked
    if _font_warning_checked:
        return
    _font_warning_checked = True
    try:
        import platform
        if os.environ.get("CLOAKBROWSER_SUPPRESS_FONT_WARNING"):
            return
        if platform.system() != "Linux":
            return
        # Effective platform = the last --fingerprint-platform in the final argv
        # (build_args dedups, so there is at most one). None => no Windows spoof.
        effective_platform = None
        for arg in chrome_args:
            if arg.startswith("--fingerprint-platform="):
                effective_platform = arg.split("=", 1)[1].strip().lower()
        if effective_platform != "windows":
            return
        from .config import get_cache_dir
        marker = get_cache_dir() / ".font_warning_shown"
        if marker.exists():
            return
        present = _windows_fonts_present()
        if present is None or present is True:
            return  # fonts present, or can't determine — don't warn
        # Write straight to stderr (like the welcome banner and the JS/.NET
        # wrappers) so an app's logging config can't silence it.
        sys.stderr.write(
            "[cloakbrowser] No Windows fonts found — installing them is strongly "
            "advised for best results when spoofing Windows on Linux. "
            "https://github.com/CloakHQ/cloakbrowser#font-setup-on-linux "
            "(silence: CLOAKBROWSER_SUPPRESS_FONT_WARNING=1)\n"
        )
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("")
        except OSError:
            pass
    except Exception:
        pass


def _parse_proxy_url(proxy: str) -> dict[str, Any]:
    """Parse HTTP(S) proxy URL, extracting credentials into separate Playwright fields.

    Handles: http://user:pass@host:port -> {server: "http://host:port", username: "user", password: "pass"}
    Also handles: no credentials, URL-encoded special chars, missing port,
    and bare proxy strings without a scheme (e.g. 'user:pass@host:port' -> treated as http).

    SOCKS5 URLs are NOT handled here — they take a dedicated path via
    ``_normalize_socks_string_url`` in ``_resolve_proxy_config``.
    """
    # Bare format: "user:pass@host:port" — urlparse needs a scheme to extract credentials.
    normalized = proxy
    if "@" in proxy and "://" not in proxy:
        normalized = f"http://{proxy}"

    parsed = urlparse(normalized)

    if not parsed.username:
        return {"server": proxy}  # no creds — return original unchanged

    # Rebuild server URL without credentials
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc += f":{parsed.port}"

    server = urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))

    result: dict[str, Any] = {"server": server}
    result["username"] = unquote(parsed.username)
    if parsed.password:
        result["password"] = unquote(parsed.password)

    return result


def _has_credentials(proxy: str | ProxySettings) -> bool:
    """Check if the proxy has inline or dict-level credentials."""
    if isinstance(proxy, dict):
        return bool(proxy.get("username"))
    return "@" in proxy


def _reconstruct_http_url(proxy: ProxySettings) -> str:
    """Reconstruct an HTTP(S) proxy URL with inline credentials from a Playwright proxy dict."""
    server = proxy.get("server", "")
    username = proxy.get("username", "")
    password = proxy.get("password", "")
    if not username:
        return server
    parsed = urlparse(_ensure_proxy_scheme(server))
    enc_user = quote(username, safe="")
    enc_pass = quote(password, safe="") if password else None
    return _assemble_proxy_url(
        parsed.scheme, parsed.hostname or "", parsed.port,
        enc_user, enc_pass, parsed.path,
    )


def _normalize_http_string_url(url: str) -> str:
    """Re-encode credentials in an HTTP(S) proxy URL string for --proxy-server.

    Same pattern as ``_normalize_socks_string_url`` — decode then re-encode to
    ensure Chromium's proxy URL parser handles special chars correctly.
    """
    normalized = url if "://" in url else f"http://{url}"
    try:
        parsed = urlparse(normalized)
        _ = parsed.port
    except ValueError as e:
        logger.warning("Malformed HTTP proxy URL, passing through unchanged: %s", e)
        return normalized
    if parsed.username is None and parsed.password is None:
        return normalized
    raw_user = parsed.username or ""
    enc_user = quote(unquote(raw_user), safe="") if raw_user else ""
    if parsed.password is not None:
        raw_pass = parsed.password
        enc_pass = quote(unquote(raw_pass), safe="") if raw_pass else ""
    else:
        raw_pass = None
        enc_pass = None
    result = _assemble_proxy_url(
        parsed.scheme, parsed.hostname or "", parsed.port,
        enc_user, enc_pass,
        parsed.path, parsed.params, parsed.query, parsed.fragment,
    )
    if enc_user != raw_user or enc_pass != raw_pass:
        logger.info(
            "Auto URL-encoded HTTP proxy credentials (special characters "
            "detected). Pre-encode the URL to suppress this notice."
        )
    return result


_HTTP_PROXY_INLINE_AUTH_MIN_VERSION = "146.0.7680.177.5"
_HTTP_PROXY_INLINE_AUTH_PLATFORMS = {"linux-x64", "windows-x64"}


def _supports_http_proxy_inline_auth(version: str | None = None) -> bool:
    """Check if the running binary supports HTTP proxy inline credentials.

    Requires both a supported platform AND a binary version with preemptive proxy
    auth. ``version`` is the pinned/resolved Chromium version actually being
    launched; when None it falls back to the platform default. Passing the pin
    matters because a rollback can run a binary older than the default (#182).
    """
    from .config import get_platform_tag, get_chromium_version, _version_tuple
    tag = get_platform_tag()
    if tag not in _HTTP_PROXY_INLINE_AUTH_PLATFORMS:
        return False
    effective = version or get_chromium_version()
    return _version_tuple(effective) >= _version_tuple(_HTTP_PROXY_INLINE_AUTH_MIN_VERSION)


def _is_socks_proxy(proxy: str | ProxySettings | None) -> bool:
    """Check if the proxy uses SOCKS5 protocol."""
    if proxy is None:
        return False
    url = proxy.get("server", "") if isinstance(proxy, dict) else proxy
    return url.lower().startswith(("socks5://", "socks5h://"))


def _resolve_proxy_config(
    proxy: str | ProxySettings | None,
    browser_version: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Resolve proxy into Playwright kwargs and Chrome args.

    Proxies with credentials (SOCKS5 or HTTP/HTTPS) are passed via Chrome's
    --proxy-server flag with inline credentials, bypassing Playwright's CDP
    auth interceptor which breaks on some proxies and Google domains (#182).

    Returns:
        (proxy_kwargs, extra_chrome_args) — one or both will be empty.
    """
    if proxy is None:
        return {}, []

    if _is_socks_proxy(proxy):
        # SOCKS5: bypass Playwright, pass directly to Chrome via --proxy-server.
        # Chrome handles SOCKS5 auth natively from the URL.
        if isinstance(proxy, dict):
            url = _reconstruct_socks_url(proxy)
            extra_args = [f"--proxy-server={url}"]
            if proxy.get("bypass"):
                extra_args.append(f"--proxy-bypass-list={proxy['bypass']}")
            return {}, extra_args
        # String URL — re-encode creds to work around Chromium parser truncating
        # passwords at '=' and other special chars (#157).
        return {}, [f"--proxy-server={_normalize_socks_string_url(proxy)}"]

    # HTTP/HTTPS with credentials on supported platforms: bypass Playwright's
    # CDP auth interceptor, pass directly to Chrome via --proxy-server with
    # inline creds. Chrome sends Proxy-Authorization preemptively, avoiding
    # the 407 round-trip that breaks on some proxies (#182).
    requested_version = normalize_requested_version(browser_version)
    if _has_credentials(proxy) and _supports_http_proxy_inline_auth(requested_version):
        if isinstance(proxy, dict):
            url = _reconstruct_http_url(proxy)
            extra_args = [f"--proxy-server={url}"]
            if proxy.get("bypass"):
                extra_args.append(f"--proxy-bypass-list={proxy['bypass']}")
            return {}, extra_args
        return {}, [f"--proxy-server={_normalize_http_string_url(proxy)}"]

    # HTTP/HTTPS without credentials: use Playwright's proxy dict
    if isinstance(proxy, dict):
        return {"proxy": proxy}, []
    return {"proxy": _parse_proxy_url(proxy)}, []
