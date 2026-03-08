"""Page/tab management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.session_manager import manager

router = APIRouter(prefix="/sessions/{session_id}/pages", tags=["Pages"])


def _get_session(session_id: str):
    try:
        return manager.get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")


@router.post("", status_code=201)
async def new_page(session_id: str):
    """Open a new tab/page in the session.

    Returns a `page_id` used for all page-level actions.
    """
    session = _get_session(session_id)
    try:
        page_id, page = await session.new_page()
        return {
            "page_id": page_id,
            "url": page.url,
            "message": "Page created",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create page: {e}")


@router.get("")
async def list_pages(session_id: str):
    """List all open pages in a session."""
    session = _get_session(session_id)
    return {
        "pages": [
            {"page_id": p.page_id, "url": p.url, "title": p.title}
            for p in session.info.pages.values()
        ]
    }


@router.delete("/{page_id}")
async def close_page(session_id: str, page_id: str):
    """Close a specific page/tab."""
    session = _get_session(session_id)
    try:
        await session.close_page(page_id)
        return {"message": f"Page '{page_id}' closed"}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Page '{page_id}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to close page: {e}")


@router.get("/{page_id}")
async def get_page_info(session_id: str, page_id: str):
    """Get current URL and title of a page."""
    session = _get_session(session_id)
    try:
        await session.update_page_info(page_id)
        page_info = session.info.pages[page_id]
        return {
            "page_id": page_id,
            "url": page_info.url,
            "title": page_info.title,
        }
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Page '{page_id}' not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get page info: {e}")
