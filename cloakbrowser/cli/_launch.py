"""Shared browser-launch helpers for the agent CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def launch_for_cli(
    profile: str | None = None,
    url: str | None = None,
    headless: bool = True,
    timeout: int = 30,
    profiles_dir: Path | None = None,
) -> tuple[Any, Any]:  # (context or browser, page)
    """Launch cloakbrowser and navigate to URL. Returns (context_or_browser, page)."""
    from ..browser import launch, launch_persistent_context

    if profile:
        d = (profiles_dir or Path.home() / ".cloakbrowser" / "profiles") / profile
        d.mkdir(parents=True, exist_ok=True)
        context = launch_persistent_context(str(d), headless=headless)
        page = context.new_page() if context.pages else context.pages[0]
    else:
        browser = launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()

    if url:
        page.goto(url, timeout=timeout * 1000)

    return context, page
