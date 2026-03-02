"""CloakBrowser API Server.

A REST API that exposes CloakBrowser (stealth Chromium) as a service.
Deploy on Docker/Coolify and control browsers remotely via HTTP.

Usage:
    uvicorn api.main:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.session_manager import manager
from api.routers import sessions as sessions_router
from api.routers import pages as pages_router
from api.routers import actions as actions_router

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("cloakbrowser.api")

# ---------------------------------------------------------------------------
# API Key auth (optional)
# ---------------------------------------------------------------------------
API_KEY = os.environ.get("API_KEY", "")


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown logic."""
    logger.info("CloakBrowser API starting up...")
    # Pre-download binary if not present
    try:
        from cloakbrowser.download import ensure_binary
        ensure_binary()
        logger.info("CloakBrowser binary ready")
    except Exception as e:
        logger.warning("Binary check failed: %s", e)

    # Start idle session cleanup
    await manager.start_cleanup_task()
    logger.info(
        "Session manager ready (max_sessions=%d, session_ttl=%ds)",
        manager.max_sessions,
        manager.session_ttl,
    )

    yield  # Server is running

    # Shutdown: close all sessions
    logger.info("Shutting down — closing all sessions...")
    await manager.close_all()
    logger.info("CloakBrowser API stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="CloakBrowser API",
    description=(
        "Remote stealth browser control API. "
        "Launch anti-detect Chromium sessions and automate them via HTTP.\n\n"
        "## Quick Start\n"
        "1. `POST /sessions` — create a browser session\n"
        "2. `POST /sessions/{id}/pages` — open a new tab\n"
        "3. `POST /sessions/{id}/pages/{page_id}/navigate` — go to a URL\n"
        "4. `POST /sessions/{id}/pages/{page_id}/screenshot` — take a screenshot\n"
        "5. `DELETE /sessions/{id}` — close the session\n"
    ),
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
cors_origins = os.environ.get("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# API Key middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Validate API key if API_KEY env var is set."""
    # Skip auth for health check and docs
    if request.url.path in ("/health", "/docs", "/redoc", "/openapi.json"):
        return await call_next(request)

    if API_KEY:
        key = (
            request.headers.get("X-API-Key")
            or request.headers.get("Authorization", "").removeprefix("Bearer ")
        )
        if key != API_KEY:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key. Set X-API-Key header."},
            )

    return await call_next(request)


# ---------------------------------------------------------------------------
# Request timing middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    response.headers["X-Response-Time"] = f"{duration:.1f}ms"
    return response


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(sessions_router.router)
app.include_router(pages_router.router)
app.include_router(actions_router.router)


# ---------------------------------------------------------------------------
# Health & info endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["System"])
async def health():
    """Health check endpoint. Returns 200 if the service is running."""
    return {
        "status": "ok",
        "active_sessions": len(manager._sessions),
        "max_sessions": manager.max_sessions,
    }


@app.get("/", tags=["System"])
async def root():
    """API info and links."""
    return {
        "name": "CloakBrowser API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "active_sessions": len(manager._sessions),
    }
