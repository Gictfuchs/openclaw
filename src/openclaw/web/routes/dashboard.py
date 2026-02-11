"""Dashboard page routes (login, logout, main page)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from openclaw.web.auth import do_login, do_logout, is_authenticated

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/login", response_class=HTMLResponse, response_model=None)
async def login_page(request: Request) -> HTMLResponse:
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=303)  # type: ignore[return-value]
    return templates.TemplateResponse(request, "login.html")


@router.post("/login", response_model=None)
async def login_submit(request: Request) -> RedirectResponse | HTMLResponse:
    form = await request.form()
    secret = str(form.get("secret_key", ""))
    if do_login(request, secret):
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": "Falscher Schluessel"})


@router.post("/logout")
async def logout_route(request: Request) -> RedirectResponse:
    do_logout(request)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/", response_class=HTMLResponse, response_model=None)
async def dashboard(request: Request) -> HTMLResponse | RedirectResponse:
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "dashboard.html")


@router.get("/chat", response_class=HTMLResponse, response_model=None)
async def chat_page(request: Request) -> HTMLResponse | RedirectResponse:
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    return templates.TemplateResponse(request, "chat.html")


@router.get("/settings", response_class=HTMLResponse, response_model=None)
async def settings_page(request: Request) -> HTMLResponse | RedirectResponse:
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    settings = request.app.state.settings
    return templates.TemplateResponse(request, "settings.html", {"settings": settings})
