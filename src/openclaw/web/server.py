"""Web dashboard server - FastAPI + Uvicorn running in the agent event loop."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

if TYPE_CHECKING:
    from openclaw.config import Settings

logger = structlog.get_logger()

_BASE = Path(__file__).parent


def create_app(settings: Settings, app_state: dict[str, Any]) -> FastAPI:
    """Create and configure the FastAPI application."""
    web_app = FastAPI(title="Fochs Dashboard", docs_url=None, redoc_url=None)

    # Session middleware for cookie-based auth
    web_app.add_middleware(
        SessionMiddleware,
        secret_key=settings.web_secret_key.get_secret_value(),
    )

    # Store references to agent components for routes to access
    web_app.state.fochs = app_state
    web_app.state.settings = settings

    # Static files
    static_dir = _BASE / "static"
    if static_dir.is_dir():
        web_app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # Register routes
    from openclaw.web.routes.api import router as api_router
    from openclaw.web.routes.chat import router as chat_router
    from openclaw.web.routes.dashboard import router as dashboard_router

    web_app.include_router(dashboard_router)
    web_app.include_router(api_router, prefix="/api")
    web_app.include_router(chat_router)

    return web_app


async def start_web_server(settings: Settings, app_state: dict[str, Any]) -> None:
    """Start the web server as a background task in the current event loop."""
    web_app = create_app(settings, app_state)
    config = uvicorn.Config(
        app=web_app,
        host=settings.web_host,
        port=settings.web_port,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    logger.info("web_dashboard_starting", host=settings.web_host, port=settings.web_port)
    await server.serve()
