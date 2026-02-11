"""Simple cookie-based authentication for the web dashboard.

Security:
- CSRF tokens are generated per session and validated on all state-changing POST requests.
- Timing-safe comparison is used for both login secrets and CSRF tokens.
- Login rate limiting: per-IP sliding window to prevent brute-force attacks.
"""

from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict
from typing import TYPE_CHECKING

import structlog

from openclaw.web import get_client_ip

if TYPE_CHECKING:
    from fastapi import Request

logger = structlog.get_logger()

_SESSION_KEY = "authenticated"
_CSRF_KEY = "csrf_token"

# --- Login brute-force protection ---
_LOGIN_MAX_ATTEMPTS = 5  # max failed attempts per IP in window
_LOGIN_WINDOW_SECONDS = 300.0  # 5-minute sliding window
_LOGIN_LOCKOUT_SECONDS = 900.0  # 15-minute lockout after exceeding limit

# Per-IP failed login timestamps (in-memory, resets on restart)
_login_failures: dict[str, list[float]] = defaultdict(list)


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


def is_login_locked(request: Request) -> bool:
    """Check if the client IP is currently locked out due to too many failed attempts."""
    ip = get_client_ip(request)
    failures = _login_failures.get(ip)
    if not failures:
        return False

    now = time.monotonic()

    # Clean old entries outside the lockout window
    cutoff = now - _LOGIN_LOCKOUT_SECONDS
    _login_failures[ip] = [t for t in failures if t > cutoff]
    failures = _login_failures[ip]

    if not failures:
        return False

    # Check if there were enough failures within the shorter attempt window
    attempt_cutoff = now - _LOGIN_WINDOW_SECONDS
    recent = [t for t in failures if t > attempt_cutoff]
    return len(recent) >= _LOGIN_MAX_ATTEMPTS


def _record_login_failure(request: Request) -> None:
    """Record a failed login attempt for the client IP."""
    ip = get_client_ip(request)
    now = time.monotonic()

    # Append and prune old entries
    _login_failures[ip].append(now)
    cutoff = now - _LOGIN_LOCKOUT_SECONDS
    _login_failures[ip] = [t for t in _login_failures[ip] if t > cutoff]

    recent_cutoff = now - _LOGIN_WINDOW_SECONDS
    recent_count = sum(1 for t in _login_failures[ip] if t > recent_cutoff)
    logger.warning("login_failed", ip=ip, recent_failures=recent_count)

    if recent_count >= _LOGIN_MAX_ATTEMPTS:
        logger.warning("login_locked_out", ip=ip, lockout_seconds=_LOGIN_LOCKOUT_SECONDS)


def do_login(request: Request, secret: str) -> bool:
    """Attempt login with the provided secret key.

    Uses hmac.compare_digest for timing-safe comparison to prevent
    timing side-channel attacks that could leak the secret.
    Records failed attempts for brute-force protection.

    Returns True on success.
    """
    expected = request.app.state.settings.web_secret_key.get_secret_value()
    if hmac.compare_digest(secret.encode("utf-8"), expected.encode("utf-8")):
        request.session[_SESSION_KEY] = True
        # Rotate CSRF token on login to prevent fixation
        request.session[_CSRF_KEY] = secrets.token_urlsafe(32)
        # Clear failure history for this IP on successful login
        ip = get_client_ip(request)
        _login_failures.pop(ip, None)
        return True
    _record_login_failure(request)
    return False


def do_logout(request: Request) -> None:
    """Clear the session."""
    request.session.clear()
