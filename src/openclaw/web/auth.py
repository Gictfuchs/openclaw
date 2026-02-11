"""Simple cookie-based authentication for the web dashboard.

Security:
- CSRF tokens are generated per session and validated on all state-changing POST requests.
- Timing-safe comparison is used for both login secrets and CSRF tokens.
"""

from __future__ import annotations

import hmac
import secrets

from fastapi import HTTPException, Request

_SESSION_KEY = "authenticated"
_CSRF_KEY = "csrf_token"


def is_authenticated(request: Request) -> bool:
    """Check if the current session is authenticated."""
    return bool(request.session.get(_SESSION_KEY, False))


def get_csrf_token(request: Request) -> str:
    """Get or create a CSRF token for the current session.

    The token is stored in the session and must be included in all
    state-changing POST forms as a hidden ``csrf_token`` field.
    """
    token = request.session.get(_CSRF_KEY)
    if not token:
        token = secrets.token_urlsafe(32)
        request.session[_CSRF_KEY] = token
    return token


def validate_csrf_token(request: Request, token: str) -> bool:
    """Validate a submitted CSRF token against the session token.

    Uses hmac.compare_digest for timing-safe comparison.
    """
    expected = request.session.get(_CSRF_KEY, "")
    if not expected or not token:
        return False
    return hmac.compare_digest(token.encode("utf-8"), expected.encode("utf-8"))


def do_login(request: Request, secret: str) -> bool:
    """Attempt login with the provided secret key.

    Uses hmac.compare_digest for timing-safe comparison to prevent
    timing side-channel attacks that could leak the secret.

    Returns True on success.
    """
    expected = request.app.state.settings.web_secret_key.get_secret_value()
    if hmac.compare_digest(secret.encode("utf-8"), expected.encode("utf-8")):
        request.session[_SESSION_KEY] = True
        # Rotate CSRF token on login to prevent fixation
        request.session[_CSRF_KEY] = secrets.token_urlsafe(32)
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
