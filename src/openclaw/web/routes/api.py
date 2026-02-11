"""Status API endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from openclaw.web.auth import is_authenticated

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/status", response_model=None)
async def get_status(request: Request) -> JSONResponse | HTMLResponse:
    """Return aggregated status for the dashboard.

    Returns HTML partial when requested by HTMX, JSON otherwise.
    """
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    fochs: dict[str, Any] = request.app.state.fochs
    agent = fochs.get("agent")
    scheduler = fochs.get("scheduler")
    sub_runner = fochs.get("sub_agent_runner")

    status: dict[str, Any] = {}
    if agent:
        status = await agent.get_status()
    if scheduler:
        status["scheduler"] = scheduler.get_status()
    if sub_runner:
        status["sub_agents"] = sub_runner.get_status()

    # Return HTML partial for HTMX, or JSON for API consumers
    accept = request.headers.get("accept", "")
    if "text/html" in accept:
        return templates.TemplateResponse(request, "partials/status.html", {"status": status})
    return JSONResponse(status)


@router.get("/health")
async def health_check(request: Request) -> JSONResponse:
    """Health check endpoint (unauthenticated).

    Returns 200 if healthy, 503 if degraded.
    """
    fochs: dict[str, Any] = request.app.state.fochs
    agent = fochs.get("agent")

    checks: dict[str, bool] = {"agent": agent is not None}

    # Check LLM availability
    if agent:
        try:
            availability = await agent.llm.check_availability()
            checks["llm"] = any(availability.values())
        except Exception:
            checks["llm"] = False
    else:
        checks["llm"] = False

    healthy = all(checks.values())
    return JSONResponse(
        {"status": "healthy" if healthy else "degraded", "checks": checks},
        status_code=200 if healthy else 503,
    )
