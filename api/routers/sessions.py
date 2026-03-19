"""Session management endpoints."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.session_manager import manager

router = APIRouter(prefix="/sessions", tags=["Sessions"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class CreateSessionRequest(BaseModel):
    proxy: Optional[str] = None
    """Proxy URL, e.g. 'http://user:pass@host:port' or 'socks5://host:port'"""

    user_agent: Optional[str] = None
    """Custom User-Agent string"""

    viewport: Optional[dict] = None
    """Viewport size, e.g. {"width": 1920, "height": 1080}"""

    locale: Optional[str] = None
    """Browser locale, e.g. 'en-US'"""

    timezone_id: Optional[str] = None
    """Timezone, e.g. 'America/New_York'"""

    stealth_args: bool = True
    """Use default stealth fingerprint args (recommended)"""


class CreateSessionResponse(BaseModel):
    session_id: str
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("", response_model=CreateSessionResponse, status_code=201)
async def create_session(body: CreateSessionRequest = CreateSessionRequest()):
    """Create a new stealth browser session.

    Returns a `session_id` that you use in all subsequent requests.
    The browser is launched immediately and kept alive until you close it.
    """
    try:
        session_id = await manager.create_session(
            proxy=body.proxy,
            user_agent=body.user_agent,
            viewport=body.viewport,
            locale=body.locale,
            timezone_id=body.timezone_id,
            stealth_args=body.stealth_args,
        )
        return CreateSessionResponse(
            session_id=session_id,
            message="Session created successfully",
        )
    except RuntimeError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create session: {e}")


@router.get("")
async def list_sessions():
    """List all active browser sessions."""
    return {
        "sessions": manager.list_sessions(),
        "total": len(manager._sessions),
    }


@router.delete("/{session_id}", status_code=200)
async def close_session(session_id: str):
    """Close and destroy a browser session.

    All pages in the session are closed and resources freed.
    """
    try:
        manager.get_session(session_id)  # validate exists
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    await manager.close_session(session_id)
    return {"message": f"Session '{session_id}' closed"}


@router.get("/{session_id}")
async def get_session(session_id: str):
    """Get details about a specific session."""
    try:
        session = manager.get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")

    info = session.info
    return {
        "session_id": session_id,
        "created_at": info.created_at,
        "last_used": info.last_used,
        "proxy": info.proxy,
        "user_agent": info.user_agent,
        "viewport": info.viewport,
        "locale": info.locale,
        "timezone_id": info.timezone_id,
        "pages": [
            {"page_id": p.page_id, "url": p.url, "title": p.title}
            for p in info.pages.values()
        ],
    }
