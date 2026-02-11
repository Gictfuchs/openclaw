"""Dashboard page routes (login, logout, main page).

Security: All state-changing POST routes validate CSRF tokens.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from openclaw.web.auth import (
    do_login,
    do_logout,
    get_csrf_token,
    is_authenticated,
    validate_csrf_token,
)

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent.parent / "templates"))


@router.get("/login", response_class=HTMLResponse, response_model=None)
async def login_page(request: Request) -> HTMLResponse:
    if is_authenticated(request):
        return RedirectResponse(url="/", status_code=303)  # type: ignore[return-value]
    csrf_token = get_csrf_token(request)
    return templates.TemplateResponse(request, "login.html", {"csrf_token": csrf_token})


@router.post("/login", response_model=None)
async def login_submit(request: Request) -> RedirectResponse | HTMLResponse:
    form = await request.form()

    # CSRF validation
    csrf_token = str(form.get("csrf_token", ""))
    if not validate_csrf_token(request, csrf_token):
        csrf_new = get_csrf_token(request)
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Ungueltige Anfrage. Bitte erneut versuchen.", "csrf_token": csrf_new},
            status_code=403,
        )

    secret = str(form.get("secret_key", ""))
    if do_login(request, secret):
        return RedirectResponse(url="/", status_code=303)

    csrf_new = get_csrf_token(request)
    return templates.TemplateResponse(request, "login.html", {"error": "Falscher Schluessel", "csrf_token": csrf_new})


@router.post("/logout")
async def logout_route(request: Request) -> RedirectResponse:
    # CSRF validation for logout
    form = await request.form()
    csrf_token = str(form.get("csrf_token", ""))
    if not validate_csrf_token(request, csrf_token):
        # Reject invalid CSRF but don't reveal details
        return RedirectResponse(url="/login", status_code=303)

    do_logout(request)
    return RedirectResponse(url="/login", status_code=303)


@router.get("/", response_class=HTMLResponse, response_model=None)
async def dashboard(request: Request) -> HTMLResponse | RedirectResponse:
    if not is_authenticated(request):
        return RedirectResponse(url="/login", status_code=303)
    csrf_token = get_csrf_token(request)
    return templates.TemplateResponse(request, "dashboard.html", {"csrf_token": csrf_token})


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
