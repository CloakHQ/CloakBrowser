"""Session manager for CloakBrowser API.

Manages multiple browser sessions with lifecycle tracking.
Each session has its own browser instance and pages.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger("cloakbrowser.api")


@dataclass
class PageInfo:
    """Metadata about an open page/tab."""
    page_id: str
    url: str
    title: str
    created_at: float = field(default_factory=time.time)


@dataclass
class SessionInfo:
    """Metadata about a browser session."""
    session_id: str
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    proxy: Optional[str] = None
    user_agent: Optional[str] = None
    viewport: Optional[dict] = None
    locale: Optional[str] = None
    timezone_id: Optional[str] = None
    pages: Dict[str, PageInfo] = field(default_factory=dict)


class BrowserSession:
    """Holds a live browser + context + pages for one session."""

    def __init__(self, session_id: str, info: SessionInfo):
        self.session_id = session_id
        self.info = info
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._pages: Dict[str, Any] = {}  # page_id -> playwright Page object

    async def initialize(
        self,
        proxy: Optional[str] = None,
        user_agent: Optional[str] = None,
        viewport: Optional[dict] = None,
        locale: Optional[str] = None,
        timezone_id: Optional[str] = None,
        stealth_args: bool = True,
    ) -> None:
        """Launch browser and create context."""
        from playwright.async_api import async_playwright
        from cloakbrowser.config import get_default_stealth_args
        from cloakbrowser.download import ensure_binary
        from cloakbrowser.browser import _build_args, _build_proxy_kwargs

        binary_path = ensure_binary()
        chrome_args = _build_args(stealth_args, None)

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            executable_path=binary_path,
            headless=True,
            args=chrome_args,
            ignore_default_args=["--enable-automation"],
            **_build_proxy_kwargs(proxy),
        )

        context_kwargs: dict[str, Any] = {}
        if user_agent:
            context_kwargs["user_agent"] = user_agent
        if viewport:
            context_kwargs["viewport"] = viewport
        if locale:
            context_kwargs["locale"] = locale
        if timezone_id:
            context_kwargs["timezone_id"] = timezone_id

        self._context = await self._browser.new_context(**context_kwargs)
        logger.info("Session %s initialized", self.session_id)

    async def new_page(self) -> tuple[str, Any]:
        """Create a new page/tab. Returns (page_id, page)."""
        page = await self._context.new_page()
        page_id = str(uuid.uuid4())[:8]
        self._pages[page_id] = page
        self.info.pages[page_id] = PageInfo(
            page_id=page_id,
            url=page.url,
            title="",
        )
        self.info.last_used = time.time()
        logger.debug("Session %s: new page %s", self.session_id, page_id)
        return page_id, page

    def get_page(self, page_id: str) -> Any:
        """Get a page by ID. Raises KeyError if not found."""
        if page_id not in self._pages:
            raise KeyError(f"Page '{page_id}' not found in session '{self.session_id}'")
        return self._pages[page_id]

    async def close_page(self, page_id: str) -> None:
        """Close a specific page."""
        page = self.get_page(page_id)
        await page.close()
        del self._pages[page_id]
        self.info.pages.pop(page_id, None)
        logger.debug("Session %s: closed page %s", self.session_id, page_id)

    async def close(self) -> None:
        """Close all pages, context, browser, and playwright."""
        try:
            for page in list(self._pages.values()):
                try:
                    await page.close()
                except Exception:
                    pass
            self._pages.clear()

            if self._context:
                try:
                    await self._context.close()
                except Exception:
                    pass

            if self._browser:
                try:
                    await self._browser.close()
                except Exception:
                    pass

            if self._pw:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
        except Exception as e:
            logger.warning("Error closing session %s: %s", self.session_id, e)
        finally:
            logger.info("Session %s closed", self.session_id)

    async def update_page_info(self, page_id: str) -> None:
        """Refresh URL and title for a page."""
        page = self.get_page(page_id)
        if page_id in self.info.pages:
            self.info.pages[page_id].url = page.url
            try:
                self.info.pages[page_id].title = await page.title()
            except Exception:
                pass
        self.info.last_used = time.time()


class SessionManager:
    """Global manager for all browser sessions."""

    def __init__(self, max_sessions: int = 10, session_ttl: int = 3600):
        """
        Args:
            max_sessions: Maximum concurrent sessions allowed.
            session_ttl: Seconds before an idle session is auto-closed (0 = disabled).
        """
        self._sessions: Dict[str, BrowserSession] = {}
        self._lock = asyncio.Lock()
        self.max_sessions = max_sessions
        self.session_ttl = session_ttl
        self._cleanup_task: Optional[asyncio.Task] = None

    async def start_cleanup_task(self) -> None:
        """Start background task to clean up idle sessions."""
        if self.session_ttl > 0:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self) -> None:
        """Periodically close sessions that have been idle too long."""
        while True:
            await asyncio.sleep(60)  # check every minute
            await self._cleanup_idle_sessions()

    async def _cleanup_idle_sessions(self) -> None:
        """Close sessions idle longer than session_ttl."""
        now = time.time()
        to_close = []
        async with self._lock:
            for sid, session in self._sessions.items():
                if now - session.info.last_used > self.session_ttl:
                    to_close.append(sid)

        for sid in to_close:
            logger.info("Auto-closing idle session %s", sid)
            await self.close_session(sid)

    async def create_session(
        self,
        proxy: Optional[str] = None,
        user_agent: Optional[str] = None,
        viewport: Optional[dict] = None,
        locale: Optional[str] = None,
        timezone_id: Optional[str] = None,
        stealth_args: bool = True,
    ) -> str:
        """Create a new browser session. Returns session_id."""
        async with self._lock:
            if len(self._sessions) >= self.max_sessions:
                raise RuntimeError(
                    f"Maximum sessions ({self.max_sessions}) reached. "
                    "Close an existing session first."
                )
            session_id = str(uuid.uuid4())[:12]

        info = SessionInfo(
            session_id=session_id,
            proxy=proxy,
            user_agent=user_agent,
            viewport=viewport,
            locale=locale,
            timezone_id=timezone_id,
        )
        session = BrowserSession(session_id, info)
        await session.initialize(
            proxy=proxy,
            user_agent=user_agent,
            viewport=viewport,
            locale=locale,
            timezone_id=timezone_id,
            stealth_args=stealth_args,
        )

        async with self._lock:
            self._sessions[session_id] = session

        logger.info("Created session %s (total: %d)", session_id, len(self._sessions))
        return session_id

    def get_session(self, session_id: str) -> BrowserSession:
        """Get a session by ID. Raises KeyError if not found."""
        if session_id not in self._sessions:
            raise KeyError(f"Session '{session_id}' not found")
        return self._sessions[session_id]

    async def close_session(self, session_id: str) -> None:
        """Close and remove a session."""
        async with self._lock:
            session = self._sessions.pop(session_id, None)

        if session:
            await session.close()
            logger.info("Removed session %s (remaining: %d)", session_id, len(self._sessions))

    def list_sessions(self) -> list[dict]:
        """Return summary of all active sessions."""
        result = []
        for sid, session in self._sessions.items():
            info = session.info
            result.append({
                "session_id": sid,
                "created_at": info.created_at,
                "last_used": info.last_used,
                "proxy": info.proxy,
                "page_count": len(info.pages),
                "pages": [
                    {"page_id": p.page_id, "url": p.url, "title": p.title}
                    for p in info.pages.values()
                ],
            })
        return result

    async def close_all(self) -> None:
        """Close all sessions (called on shutdown)."""
        session_ids = list(self._sessions.keys())
        for sid in session_ids:
            await self.close_session(sid)
        if self._cleanup_task:
            self._cleanup_task.cancel()
        logger.info("All sessions closed")


# Global singleton
manager = SessionManager(
    max_sessions=int(__import__("os").environ.get("MAX_SESSIONS", "10")),
    session_ttl=int(__import__("os").environ.get("SESSION_TTL", "3600")),
)
