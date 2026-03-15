"""Browser action endpoints — navigate, click, type, screenshot, evaluate, etc."""

from __future__ import annotations

import base64
import logging
from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from api.session_manager import manager

logger = logging.getLogger("cloakbrowser.api")

router = APIRouter(
    prefix="/sessions/{session_id}/pages/{page_id}",
    tags=["Actions"],
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_page(session_id: str, page_id: str):
    """Get page object or raise 404."""
    try:
        session = manager.get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found")
    try:
        return session, session.get_page(page_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Page '{page_id}' not found")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class NavigateRequest(BaseModel):
    url: str
    wait_until: str = "load"
    """Event to wait for: 'load', 'domcontentloaded', 'networkidle', 'commit'"""
    timeout: int = 30000
    """Timeout in milliseconds"""


class ClickRequest(BaseModel):
    selector: str
    """CSS selector or XPath (prefix with 'xpath=' for XPath)"""
    button: str = "left"
    """Mouse button: 'left', 'right', 'middle'"""
    click_count: int = 1
    timeout: int = 10000
    force: bool = False


class TypeRequest(BaseModel):
    selector: str
    text: str
    delay: int = 50
    """Delay between keystrokes in ms (simulates human typing)"""
    timeout: int = 10000
    clear_first: bool = False
    """Clear the field before typing"""


class FillRequest(BaseModel):
    selector: str
    value: str
    """Value to fill (instant, no delay)"""
    timeout: int = 10000


class SelectRequest(BaseModel):
    selector: str
    value: Optional[str] = None
    label: Optional[str] = None
    index: Optional[int] = None
    timeout: int = 10000


class WaitForRequest(BaseModel):
    selector: str
    state: str = "visible"
    """State to wait for: 'attached', 'detached', 'visible', 'hidden'"""
    timeout: int = 30000


class WaitForURLRequest(BaseModel):
    url: str
    """URL pattern (string, glob, or regex)"""
    timeout: int = 30000


class EvaluateRequest(BaseModel):
    expression: str
    """JavaScript expression to evaluate in the page context"""
    arg: Optional[Any] = None
    """Optional argument to pass to the expression"""


class ScreenshotRequest(BaseModel):
    full_page: bool = False
    format: str = "png"
    """Image format: 'png' or 'jpeg'"""
    quality: Optional[int] = None
    """JPEG quality 0-100 (only for jpeg)"""
    selector: Optional[str] = None
    """Screenshot a specific element instead of the full page"""


class ScrollRequest(BaseModel):
    x: int = 0
    y: int = 0
    """Scroll to absolute position"""
    delta_x: Optional[int] = None
    delta_y: Optional[int] = None
    """Or scroll by delta"""


class HoverRequest(BaseModel):
    selector: str
    timeout: int = 10000


class PressKeyRequest(BaseModel):
    key: str
    """Key name, e.g. 'Enter', 'Tab', 'Escape', 'ArrowDown'"""
    selector: Optional[str] = None
    """Focus element before pressing (optional)"""
    timeout: int = 10000


class GetTextRequest(BaseModel):
    selector: str
    timeout: int = 10000


class GetAttributeRequest(BaseModel):
    selector: str
    attribute: str
    timeout: int = 10000


class SetCookiesRequest(BaseModel):
    cookies: list[dict]
    """List of cookie dicts with keys: name, value, url/domain, path, etc."""


class InjectScriptRequest(BaseModel):
    script: str
    """JavaScript code to inject into the page"""


class WaitRequest(BaseModel):
    milliseconds: int
    """Time to wait in milliseconds"""


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

@router.post("/navigate")
async def navigate(session_id: str, page_id: str, body: NavigateRequest):
    """Navigate to a URL.

    Waits for the page to load before returning.
    """
    session, page = _get_page(session_id, page_id)
    try:
        response = await page.goto(
            body.url,
            wait_until=body.wait_until,
            timeout=body.timeout,
        )
        await session.update_page_info(page_id)
        return {
            "url": page.url,
            "title": await page.title(),
            "status": response.status if response else None,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Navigation failed: {e}")


@router.post("/reload")
async def reload(session_id: str, page_id: str, wait_until: str = "load", timeout: int = 30000):
    """Reload the current page."""
    session, page = _get_page(session_id, page_id)
    try:
        await page.reload(wait_until=wait_until, timeout=timeout)
        await session.update_page_info(page_id)
        return {"url": page.url, "title": await page.title()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reload failed: {e}")


@router.post("/go_back")
async def go_back(session_id: str, page_id: str, timeout: int = 30000):
    """Navigate back in browser history."""
    session, page = _get_page(session_id, page_id)
    try:
        await page.go_back(timeout=timeout)
        await session.update_page_info(page_id)
        return {"url": page.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Go back failed: {e}")


@router.post("/go_forward")
async def go_forward(session_id: str, page_id: str, timeout: int = 30000):
    """Navigate forward in browser history."""
    session, page = _get_page(session_id, page_id)
    try:
        await page.go_forward(timeout=timeout)
        await session.update_page_info(page_id)
        return {"url": page.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Go forward failed: {e}")


# ---------------------------------------------------------------------------
# Interaction
# ---------------------------------------------------------------------------

@router.post("/click")
async def click(session_id: str, page_id: str, body: ClickRequest):
    """Click an element by CSS selector."""
    _, page = _get_page(session_id, page_id)
    try:
        await page.click(
            body.selector,
            button=body.button,
            click_count=body.click_count,
            timeout=body.timeout,
            force=body.force,
        )
        return {"message": f"Clicked '{body.selector}'"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Click failed: {e}")


@router.post("/type")
async def type_text(session_id: str, page_id: str, body: TypeRequest):
    """Type text into an element (simulates real keystrokes with delay)."""
    _, page = _get_page(session_id, page_id)
    try:
        if body.clear_first:
            await page.fill(body.selector, "", timeout=body.timeout)
        await page.type(body.selector, body.text, delay=body.delay, timeout=body.timeout)
        return {"message": f"Typed into '{body.selector}'"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Type failed: {e}")


@router.post("/fill")
async def fill(session_id: str, page_id: str, body: FillRequest):
    """Fill an input field instantly (no keystroke simulation)."""
    _, page = _get_page(session_id, page_id)
    try:
        await page.fill(body.selector, body.value, timeout=body.timeout)
        return {"message": f"Filled '{body.selector}'"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Fill failed: {e}")


@router.post("/select")
async def select_option(session_id: str, page_id: str, body: SelectRequest):
    """Select an option in a <select> element."""
    _, page = _get_page(session_id, page_id)
    try:
        kwargs: dict[str, Any] = {"timeout": body.timeout}
        if body.value is not None:
            kwargs["value"] = body.value
        elif body.label is not None:
            kwargs["label"] = body.label
        elif body.index is not None:
            kwargs["index"] = body.index
        else:
            raise HTTPException(status_code=400, detail="Provide value, label, or index")

        selected = await page.select_option(body.selector, **kwargs)
        return {"selected": selected}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Select failed: {e}")


@router.post("/hover")
async def hover(session_id: str, page_id: str, body: HoverRequest):
    """Hover over an element."""
    _, page = _get_page(session_id, page_id)
    try:
        await page.hover(body.selector, timeout=body.timeout)
        return {"message": f"Hovered over '{body.selector}'"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Hover failed: {e}")


@router.post("/press_key")
async def press_key(session_id: str, page_id: str, body: PressKeyRequest):
    """Press a keyboard key, optionally on a focused element."""
    _, page = _get_page(session_id, page_id)
    try:
        if body.selector:
            await page.focus(body.selector, timeout=body.timeout)
        await page.keyboard.press(body.key)
        return {"message": f"Pressed '{body.key}'"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Key press failed: {e}")


@router.post("/scroll")
async def scroll(session_id: str, page_id: str, body: ScrollRequest):
    """Scroll the page to a position or by a delta."""
    _, page = _get_page(session_id, page_id)
    try:
        if body.delta_x is not None or body.delta_y is not None:
            dx = body.delta_x or 0
            dy = body.delta_y or 0
            await page.evaluate(f"window.scrollBy({dx}, {dy})")
        else:
            await page.evaluate(f"window.scrollTo({body.x}, {body.y})")
        return {"message": "Scrolled"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scroll failed: {e}")


# ---------------------------------------------------------------------------
# Waiting
# ---------------------------------------------------------------------------

@router.post("/wait_for_selector")
async def wait_for_selector(session_id: str, page_id: str, body: WaitForRequest):
    """Wait for an element to appear/disappear."""
    _, page = _get_page(session_id, page_id)
    try:
        await page.wait_for_selector(body.selector, state=body.state, timeout=body.timeout)
        return {"message": f"Element '{body.selector}' is {body.state}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Wait failed: {e}")


@router.post("/wait_for_url")
async def wait_for_url(session_id: str, page_id: str, body: WaitForURLRequest):
    """Wait until the page URL matches a pattern."""
    session, page = _get_page(session_id, page_id)
    try:
        await page.wait_for_url(body.url, timeout=body.timeout)
        await session.update_page_info(page_id)
        return {"url": page.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Wait for URL failed: {e}")


@router.post("/wait_for_load")
async def wait_for_load(session_id: str, page_id: str, state: str = "load", timeout: int = 30000):
    """Wait for a load state: 'load', 'domcontentloaded', 'networkidle'."""
    _, page = _get_page(session_id, page_id)
    try:
        await page.wait_for_load_state(state, timeout=timeout)
        return {"message": f"Load state '{state}' reached"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Wait for load failed: {e}")


@router.post("/wait")
async def wait(session_id: str, page_id: str, body: WaitRequest):
    """Wait for a fixed number of milliseconds."""
    import asyncio
    _get_page(session_id, page_id)  # validate
    await asyncio.sleep(body.milliseconds / 1000)
    return {"message": f"Waited {body.milliseconds}ms"}


# ---------------------------------------------------------------------------
# Data extraction
# ---------------------------------------------------------------------------

@router.get("/content")
async def get_content(session_id: str, page_id: str):
    """Get the full HTML content of the current page."""
    _, page = _get_page(session_id, page_id)
    try:
        content = await page.content()
        return {"content": content, "url": page.url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get content: {e}")


@router.post("/get_text")
async def get_text(session_id: str, page_id: str, body: GetTextRequest):
    """Get the inner text of an element."""
    _, page = _get_page(session_id, page_id)
    try:
        text = await page.inner_text(body.selector, timeout=body.timeout)
        return {"text": text, "selector": body.selector}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get text: {e}")


@router.post("/get_attribute")
async def get_attribute(session_id: str, page_id: str, body: GetAttributeRequest):
    """Get an attribute value from an element."""
    _, page = _get_page(session_id, page_id)
    try:
        value = await page.get_attribute(body.selector, body.attribute, timeout=body.timeout)
        return {"value": value, "selector": body.selector, "attribute": body.attribute}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get attribute: {e}")


@router.post("/evaluate")
async def evaluate(session_id: str, page_id: str, body: EvaluateRequest):
    """Execute JavaScript in the page context and return the result.

    Example:
        {"expression": "document.title"}
        {"expression": "(x) => x * 2", "arg": 21}
    """
    _, page = _get_page(session_id, page_id)
    try:
        if body.arg is not None:
            result = await page.evaluate(body.expression, body.arg)
        else:
            result = await page.evaluate(body.expression)
        return {"result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Evaluate failed: {e}")


@router.post("/inject_script")
async def inject_script(session_id: str, page_id: str, body: InjectScriptRequest):
    """Inject and execute a JavaScript script in the page."""
    _, page = _get_page(session_id, page_id)
    try:
        await page.add_script_tag(content=body.script)
        return {"message": "Script injected"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Script injection failed: {e}")


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------

@router.post("/screenshot")
async def screenshot(session_id: str, page_id: str, body: ScreenshotRequest = ScreenshotRequest()):
    """Take a screenshot of the page.

    Returns the image as base64-encoded string in JSON,
    or use /screenshot/raw for binary response.
    """
    _, page = _get_page(session_id, page_id)
    try:
        kwargs: dict[str, Any] = {
            "full_page": body.full_page,
            "type": body.format,
        }
        if body.quality and body.format == "jpeg":
            kwargs["quality"] = body.quality

        if body.selector:
            element = await page.query_selector(body.selector)
            if not element:
                raise HTTPException(status_code=404, detail=f"Element '{body.selector}' not found")
            img_bytes = await element.screenshot(**{k: v for k, v in kwargs.items() if k != "full_page"})
        else:
            img_bytes = await page.screenshot(**kwargs)

        img_b64 = base64.b64encode(img_bytes).decode()
        return {
            "image": img_b64,
            "format": body.format,
            "size": len(img_bytes),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {e}")


@router.post("/screenshot/raw", response_class=Response)
async def screenshot_raw(session_id: str, page_id: str, body: ScreenshotRequest = ScreenshotRequest()):
    """Take a screenshot and return raw binary image data.

    Content-Type will be image/png or image/jpeg.
    """
    _, page = _get_page(session_id, page_id)
    try:
        kwargs: dict[str, Any] = {
            "full_page": body.full_page,
            "type": body.format,
        }
        if body.quality and body.format == "jpeg":
            kwargs["quality"] = body.quality

        img_bytes = await page.screenshot(**kwargs)
        media_type = "image/jpeg" if body.format == "jpeg" else "image/png"
        return Response(content=img_bytes, media_type=media_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Screenshot failed: {e}")


# ---------------------------------------------------------------------------
# Cookies
# ---------------------------------------------------------------------------

@router.get("/cookies")
async def get_cookies(session_id: str, page_id: str):
    """Get all cookies for the current page."""
    session, page = _get_page(session_id, page_id)
    try:
        cookies = await session._context.cookies(page.url)
        return {"cookies": cookies}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get cookies: {e}")


@router.post("/cookies")
async def set_cookies(session_id: str, page_id: str, body: SetCookiesRequest):
    """Set cookies for the session context."""
    session, _ = _get_page(session_id, page_id)
    try:
        await session._context.add_cookies(body.cookies)
        return {"message": f"Set {len(body.cookies)} cookie(s)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set cookies: {e}")


@router.delete("/cookies")
async def clear_cookies(session_id: str, page_id: str):
    """Clear all cookies from the session context."""
    session, _ = _get_page(session_id, page_id)
    try:
        await session._context.clear_cookies()
        return {"message": "Cookies cleared"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to clear cookies: {e}")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

@router.post("/pdf", response_class=Response)
async def export_pdf(
    session_id: str,
    page_id: str,
    format: str = "A4",
    print_background: bool = True,
):
    """Export the current page as PDF. Returns binary PDF data."""
    _, page = _get_page(session_id, page_id)
    try:
        pdf_bytes = await page.pdf(format=format, print_background=print_background)
        return Response(content=pdf_bytes, media_type="application/pdf")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF export failed: {e}")
