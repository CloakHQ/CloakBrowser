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
from typing import Any

from .config import get_default_stealth_args
from .download import ensure_binary

logger = logging.getLogger("cloakbrowser")


def launch(
    headless: bool = True,
    proxy: str | None = None,
    args: list[str] | None = None,
    stealth_args: bool = True,
    **kwargs: Any,
) -> Any:
    """Launch stealth Chromium browser. Returns a Playwright Browser object.

    Args:
        headless: Run in headless mode (default True).
        proxy: Proxy server URL (e.g. 'http://proxy:8080' or 'socks5://proxy:1080').
        args: Additional Chromium CLI arguments to pass.
        stealth_args: Include default stealth fingerprint args (default True).
            Set to False if you want to pass your own --fingerprint flags.
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
    from playwright.sync_api import sync_playwright

    binary_path = ensure_binary()
    chrome_args = _build_args(stealth_args, args)

    logger.debug("Launching stealth Chromium (headless=%s, args=%d)", headless, len(chrome_args))

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path=binary_path,
        headless=headless,
        args=chrome_args,
        ignore_default_args=["--enable-automation"],
        **_build_proxy_kwargs(proxy),
        **kwargs,
    )

    # Patch close() to also stop the Playwright instance
    _original_close = browser.close

    def _close_with_cleanup() -> None:
        _original_close()
        pw.stop()

    browser.close = _close_with_cleanup

    return browser


async def launch_async(
    headless: bool = True,
    proxy: str | None = None,
    args: list[str] | None = None,
    stealth_args: bool = True,
    **kwargs: Any,
) -> Any:
    """Async version of launch(). Returns a Playwright Browser object.

    Args:
        headless: Run in headless mode (default True).
        proxy: Proxy server URL (e.g. 'http://proxy:8080' or 'socks5://proxy:1080').
        args: Additional Chromium CLI arguments to pass.
        stealth_args: Include default stealth fingerprint args (default True).
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
    from playwright.async_api import async_playwright

    binary_path = ensure_binary()
    chrome_args = _build_args(stealth_args, args)

    logger.debug("Launching stealth Chromium async (headless=%s, args=%d)", headless, len(chrome_args))

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        executable_path=binary_path,
        headless=headless,
        args=chrome_args,
        ignore_default_args=["--enable-automation"],
        **_build_proxy_kwargs(proxy),
        **kwargs,
    )

    # Patch close() to also stop the Playwright instance
    _original_close = browser.close

    async def _close_with_cleanup() -> None:
        await _original_close()
        await pw.stop()

    browser.close = _close_with_cleanup

    return browser


def launch_context(
    headless: bool = True,
    proxy: str | None = None,
    args: list[str] | None = None,
    stealth_args: bool = True,
    user_agent: str | None = None,
    viewport: dict | None = None,
    locale: str | None = None,
    timezone_id: str | None = None,
    **kwargs: Any,
) -> Any:
    """Launch stealth browser and return a BrowserContext with common options pre-set.

    Convenience function that creates a browser + context in one call.
    Useful for setting user agent, viewport, locale, etc.

    Args:
        headless: Run in headless mode (default True).
        proxy: Proxy server URL.
        args: Additional Chromium CLI arguments.
        stealth_args: Include default stealth fingerprint args (default True).
        user_agent: Custom user agent string.
        viewport: Viewport size dict, e.g. {"width": 1920, "height": 1080}.
        locale: Browser locale, e.g. "en-US".
        timezone_id: Timezone, e.g. "America/New_York".
        **kwargs: Passed to browser.new_context().

    Returns:
        Playwright BrowserContext object.
    """
    browser = launch(headless=headless, proxy=proxy, args=args, stealth_args=stealth_args)

    context_kwargs: dict[str, Any] = {}
    if user_agent:
        context_kwargs["user_agent"] = user_agent
    if viewport:
        context_kwargs["viewport"] = viewport
    if locale:
        context_kwargs["locale"] = locale
    if timezone_id:
        context_kwargs["timezone_id"] = timezone_id
    context_kwargs.update(kwargs)

    try:
        context = browser.new_context(**context_kwargs)
    except Exception:
        browser.close()
        raise

    # Patch close() to also close the browser (and its Playwright instance)
    _original_ctx_close = context.close

    def _close_context_with_cleanup() -> None:
        _original_ctx_close()
        browser.close()

    context.close = _close_context_with_cleanup

    return context


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_args(stealth_args: bool, extra_args: list[str] | None) -> list[str]:
    """Combine stealth args with user-provided args."""
    result = []
    if stealth_args:
        result.extend(get_default_stealth_args())
    if extra_args:
        result.extend(extra_args)
    return result


def _build_proxy_kwargs(proxy: str | None) -> dict[str, Any]:
    """Build proxy kwargs for Playwright launch."""
    if proxy is None:
        return {}
    return {"proxy": {"server": proxy}}
