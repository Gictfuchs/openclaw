"""Simple cookie-based authentication for the web dashboard."""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

_SESSION_KEY = "authenticated"


def is_authenticated(request: Request) -> bool:
    """Check if the current session is authenticated."""
    return bool(request.session.get(_SESSION_KEY, False))


def do_login(request: Request, secret: str) -> bool:
    """Attempt login with the provided secret key.

    Uses hmac.compare_digest for timing-safe comparison to prevent
    timing side-channel attacks that could leak the secret.

    Returns True on success.
    """
    expected = request.app.state.settings.web_secret_key.get_secret_value()
    if hmac.compare_digest(secret.encode("utf-8"), expected.encode("utf-8")):
        request.session[_SESSION_KEY] = True
        return True
    return False


def do_logout(request: Request) -> None:
    """Clear the session."""
    request.session.clear()


def require_auth(request: Request) -> Request:
    """FastAPI dependency that returns 401 if not authenticated."""
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return request
