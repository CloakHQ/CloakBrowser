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
from typing import Any, Literal, TypedDict
from urllib.parse import quote, unquote, urlparse, urlunparse

from .config import DEFAULT_VIEWPORT, IGNORE_DEFAULT_ARGS, get_default_stealth_args
from .download import ensure_binary
from .human.config import HumanConfigOverrides, HumanPreset

logger = logging.getLogger("cloakbrowser")

# Sentinel to distinguish "viewport not provided" from "viewport=None" (disable emulation)
_VIEWPORT_UNSET = object()


def _resolve_timezone(timezone: str | None, kwargs: dict[str, Any]) -> str | None:
    """Accept both timezone and timezone_id — either works, no warning."""
    if "timezone_id" in kwargs:
        if timezone is None:
            timezone = kwargs.pop("timezone_id")
        else:
            kwargs.pop("timezone_id")
    return timezone


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
    backend: str | None = None,
    humanize: bool = False,
    human_preset: HumanPreset = "default",
    human_config: HumanConfigOverrides | None = None,
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
        stealth_args: Include default stealth fingerprint args (default True).
            Set to False if you want to pass your own --fingerprint flags.
        timezone: IANA timezone (e.g. 'America/New_York'). Sets --fingerprint-timezone binary flag.
        locale: BCP 47 locale (e.g. 'en-US'). Sets --lang binary flag.
        geoip: Auto-detect timezone/locale from proxy IP (default False).
            Requires ``pip install cloakbrowser[geoip]``. Downloads ~70 MB
            GeoLite2-City database on first use.  Explicit timezone/locale
            always override geoip results.
        backend: Playwright backend — 'playwright' (default) or 'patchright'.
            Patchright suppresses CDP signals (helps reCAPTCHA v3 Enterprise)
            but breaks proxy auth and add_init_script.
            Override globally with CLOAKBROWSER_BACKEND env var.
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
    sync_playwright = _import_sync_playwright(_resolve_backend(backend))

    binary_path = ensure_binary()
    timezone, locale, exit_ip = maybe_resolve_geoip(geoip, proxy, timezone, locale)
    proxy_kwargs, proxy_extra_args = _resolve_proxy_config(proxy)
    args = _resolve_webrtc_args(args, proxy)
    if exit_ip and not (args and any(a.startswith("--fingerprint-webrtc-ip") for a in args)):
        args = list(args or [])
        args.append(f"--fingerprint-webrtc-ip={exit_ip}")
    chrome_args = build_args(stealth_args, (args or []) + proxy_extra_args, timezone=timezone, locale=locale, headless=headless)

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
    backend: str | None = None,
    humanize: bool = False,
    human_preset: HumanPreset = "default",
    human_config: HumanConfigOverrides | None = None,
    **kwargs: Any,
) -> Any:
    """Async version of launch(). Returns a Playwright Browser object.

    Args:
        headless: Run in headless mode (default True).
        proxy: Proxy URL string or Playwright proxy dict (see launch() for details).
        args: Additional Chromium CLI arguments to pass.
        stealth_args: Include default stealth fingerprint args (default True).
        timezone: IANA timezone (e.g. 'America/New_York'). Sets --fingerprint-timezone binary flag.
        locale: BCP 47 locale (e.g. 'en-US'). Sets --lang binary flag.
        geoip: Auto-detect timezone/locale from proxy IP (default False).
        backend: Playwright backend — 'playwright' (default) or 'patchright'.
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
    async_playwright = _import_async_playwright(_resolve_backend(backend))

    binary_path = ensure_binary()
    timezone, locale, exit_ip = maybe_resolve_geoip(geoip, proxy, timezone, locale)
    proxy_kwargs, proxy_extra_args = _resolve_proxy_config(proxy)
    args = _resolve_webrtc_args(args, proxy)
    if exit_ip and not (args and any(a.startswith("--fingerprint-webrtc-ip") for a in args)):
        args = list(args or [])
        args.append(f"--fingerprint-webrtc-ip={exit_ip}")
    chrome_args = build_args(stealth_args, (args or []) + proxy_extra_args, timezone=timezone, locale=locale, headless=headless)

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
    backend: str | None = None,
    humanize: bool = False,
    human_preset: HumanPreset = "default",
    human_config: HumanConfigOverrides | None = None,
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
        backend: Playwright backend — 'playwright' (default) or 'patchright'.
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
    sync_playwright = _import_sync_playwright(_resolve_backend(backend))

    timezone = _resolve_timezone(timezone, kwargs)

    binary_path = ensure_binary()
    timezone, locale, exit_ip = maybe_resolve_geoip(geoip, proxy, timezone, locale)
    proxy_kwargs, proxy_extra_args = _resolve_proxy_config(proxy)
    args = _resolve_webrtc_args(args, proxy)
    if exit_ip and not (args and any(a.startswith("--fingerprint-webrtc-ip") for a in args)):
        args = list(args or [])
        args.append(f"--fingerprint-webrtc-ip={exit_ip}")
    chrome_args = build_args(stealth_args, (args or []) + proxy_extra_args, timezone=timezone, locale=locale, headless=headless)

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
    if viewport is _VIEWPORT_UNSET:
        context_kwargs["viewport"] = DEFAULT_VIEWPORT
    elif viewport is None:
        context_kwargs["no_viewport"] = True
    else:
        context_kwargs["viewport"] = viewport
    if color_scheme:
        context_kwargs["color_scheme"] = color_scheme
    context_kwargs.update(kwargs)

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
    backend: str | None = None,
    humanize: bool = False,
    human_preset: HumanPreset = "default",
    human_config: HumanConfigOverrides | None = None,
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
        stealth_args: Include default stealth fingerprint args (default True).
        user_agent: Custom user agent string.
        viewport: Viewport size dict, e.g. {"width": 1920, "height": 1080}.
            Pass None to disable viewport emulation (use OS window size).
        locale: Browser locale, e.g. "en-US".
        timezone: IANA timezone (e.g. 'America/New_York').
        color_scheme: Color scheme preference — 'light', 'dark', or 'no-preference'.
        geoip: Auto-detect timezone/locale from proxy IP (default False).
        backend: Playwright backend — 'playwright' (default) or 'patchright'.
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
    async_playwright = _import_async_playwright(_resolve_backend(backend))

    timezone = _resolve_timezone(timezone, kwargs)

    binary_path = ensure_binary()
    timezone, locale, exit_ip = maybe_resolve_geoip(geoip, proxy, timezone, locale)
    proxy_kwargs, proxy_extra_args = _resolve_proxy_config(proxy)
    args = _resolve_webrtc_args(args, proxy)
    if exit_ip and not (args and any(a.startswith("--fingerprint-webrtc-ip") for a in args)):
        args = list(args or [])
        args.append(f"--fingerprint-webrtc-ip={exit_ip}")
    chrome_args = build_args(stealth_args, (args or []) + proxy_extra_args, timezone=timezone, locale=locale, headless=headless)

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
    if viewport is _VIEWPORT_UNSET:
        context_kwargs["viewport"] = DEFAULT_VIEWPORT
    elif viewport is None:
        context_kwargs["no_viewport"] = True
    else:
        context_kwargs["viewport"] = viewport
    if color_scheme:
        context_kwargs["color_scheme"] = color_scheme
    context_kwargs.update(kwargs)

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
    backend: str | None = None,
    humanize: bool = False,
    human_preset: HumanPreset = "default",
    human_config: HumanConfigOverrides | None = None,
    **kwargs: Any,
) -> Any:
    """Launch stealth browser and return a BrowserContext with common options pre-set.

    Convenience function that creates a browser + context in one call.
    Useful for setting user agent, viewport, locale, etc.

    Args:
        headless: Run in headless mode (default True).
        proxy: Proxy URL string or Playwright proxy dict (see launch() for details).
        args: Additional Chromium CLI arguments.
        stealth_args: Include default stealth fingerprint args (default True).
        user_agent: Custom user agent string.
        viewport: Viewport size dict, e.g. {"width": 1920, "height": 1080}.
            Pass None to disable viewport emulation (use OS window size).
        locale: Browser locale, e.g. "en-US".
        timezone: IANA timezone (e.g. 'America/New_York').
        color_scheme: Color scheme preference — 'light', 'dark', or 'no-preference'.
            Default: None (uses Chromium default, which is 'light').
        geoip: Auto-detect timezone/locale from proxy IP (default False).
        backend: Playwright backend — 'playwright' (default) or 'patchright'.
        humanize: Enable human-like mouse, keyboard, scroll behavior (default False).
        human_preset: Humanize preset — 'default' or 'careful' (default 'default').
        human_config: Custom humanize config mapping to override preset values.
        **kwargs: Passed to browser.new_context().

    Returns:
        Playwright BrowserContext object.
    """
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
                     timezone=timezone, locale=locale, backend=backend)

    context_kwargs: dict[str, Any] = {}
    if user_agent:
        context_kwargs["user_agent"] = user_agent
    if viewport is _VIEWPORT_UNSET:
        context_kwargs["viewport"] = DEFAULT_VIEWPORT
    elif viewport is None:
        context_kwargs["no_viewport"] = True
    else:
        context_kwargs["viewport"] = viewport
    if color_scheme:
        context_kwargs["color_scheme"] = color_scheme
    context_kwargs.update(kwargs)

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


# ---------------------------------------------------------------------------
# Backend resolution
# ---------------------------------------------------------------------------


def _resolve_backend(backend: str | None) -> str:
    """Resolve backend: param > env var > default ('playwright')."""
    b = backend or os.environ.get("CLOAKBROWSER_BACKEND", "playwright")
    if b not in ("playwright", "patchright"):
        raise ValueError(f"Unknown backend '{b}'. Use 'playwright' or 'patchright'.")
    return b


def _import_sync_playwright(backend: str):
    """Import sync_playwright from the resolved backend."""
    if backend == "patchright":
        try:
            from patchright.sync_api import sync_playwright
        except ModuleNotFoundError:
            raise ModuleNotFoundError(
                "patchright is not installed. Install it with: pip install cloakbrowser[patchright]"
            ) from None
        return sync_playwright
    from playwright.sync_api import sync_playwright
    return sync_playwright


def _import_async_playwright(backend: str):
    """Import async_playwright from the resolved backend."""
    if backend == "patchright":
        try:
            from patchright.async_api import async_playwright
        except ModuleNotFoundError:
            raise ModuleNotFoundError(
                "patchright is not installed. Install it with: pip install cloakbrowser[patchright]"
            ) from None
        return async_playwright
    from playwright.async_api import async_playwright
    return async_playwright


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ensure_proxy_scheme(proxy_url: str) -> str:
    """Prepend http:// to schemeless proxy URLs so parsers can extract hostname."""
    return proxy_url if "://" in proxy_url else f"http://{proxy_url}"


def _reconstruct_socks_url(proxy: ProxySettings) -> str:
    """Reconstruct a SOCKS5 URL with inline credentials from a Playwright proxy dict."""
    server = proxy.get("server", "")
    username = proxy.get("username", "")
    password = proxy.get("password", "")
    if not username:
        return server
    parsed = urlparse(server)
    creds = quote(username, safe="")
    if password:
        creds += f":{quote(password, safe='')}"
    host = parsed.hostname or ""
    if ":" in host:  # IPv6 literal — re-add brackets
        host = f"[{host}]"
    netloc = f"{creds}@{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))


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

    from .geoip import resolve_proxy_geo_with_ip

    proxy_url = _extract_proxy_url(proxy)
    if not proxy_url:
        return timezone, locale, None

    # When both tz/locale are explicit, still resolve exit IP for WebRTC
    if timezone is not None and locale is not None:
        from .geoip import _resolve_exit_ip
        exit_ip = _resolve_exit_ip(proxy_url)
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
        from .geoip import _resolve_exit_ip
        exit_ip = _resolve_exit_ip(proxy_url)
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

    return list(seen.values())


def _parse_proxy_url(proxy: str) -> dict[str, Any]:
    """Parse proxy URL, extracting credentials into separate Playwright fields.

    Handles: http://user:pass@host:port -> {server: "http://host:port", username: "user", password: "pass"}
    Also handles: no credentials, URL-encoded special chars, socks5://, missing port,
    and bare proxy strings without a scheme (e.g. 'user:pass@host:port' -> treated as http).
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


def _is_socks_proxy(proxy: str | ProxySettings | None) -> bool:
    """Check if the proxy uses SOCKS5 protocol."""
    if proxy is None:
        return False
    url = proxy.get("server", "") if isinstance(proxy, dict) else proxy
    return url.lower().startswith(("socks5://", "socks5h://"))


def _resolve_proxy_config(
    proxy: str | ProxySettings | None,
) -> tuple[dict[str, Any], list[str]]:
    """Resolve proxy into Playwright kwargs and Chrome args.

    Playwright rejects SOCKS5 proxies with credentials in its proxy dict,
    so SOCKS5 is passed via --proxy-server Chrome arg instead.

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
        # String URL — pass as-is (Chrome handles user:pass@ in the URL)
        return {}, [f"--proxy-server={proxy}"]

    # HTTP/HTTPS: use Playwright's proxy dict as before
    if isinstance(proxy, dict):
        return {"proxy": proxy}, []
    return {"proxy": _parse_proxy_url(proxy)}, []
