"""Middleware for the web dashboard: rate-limiting and security headers."""

from __future__ import annotations

import time
from collections import defaultdict
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

if TYPE_CHECKING:
    from starlette.requests import Request


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to all responses.

    Protects against clickjacking, XSS, MIME sniffing, and other attacks.
    """

    async def dispatch(self, request: Request, call_next: object) -> Response:  # type: ignore[override]
        response: Response = await call_next(request)  # type: ignore[misc]
        # Prevent clickjacking
        response.headers["X-Frame-Options"] = "DENY"
        # Prevent MIME type sniffing
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Enable XSS filter (legacy, but harmless)
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # Referrer policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Content Security Policy — allow self + inline for HTMX/templates
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self' ws: wss:; "
            "frame-ancestors 'none'"
        )
        # Permissions policy — restrict sensitive browser features
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiting by IP address.

    Exempt paths: /api/health, /static/*
    Default: 60 requests per minute per IP.

    Periodically cleans up stale IP entries to prevent memory leaks.
    """

    # Clean up stale IPs every N requests
    _CLEANUP_INTERVAL: int = 100

    def __init__(
        self,
        app: object,
        requests_per_minute: int = 60,
        exempt_prefixes: tuple[str, ...] = ("/api/health", "/static/"),
    ) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._rpm = requests_per_minute
        self._exempt = exempt_prefixes
        self._window: dict[str, list[float]] = defaultdict(list)
        self._request_count: int = 0

    async def dispatch(self, request: Request, call_next: object) -> Response:  # type: ignore[override]
        """Check rate limit before processing request."""
        path = request.url.path

        # Exempt paths
        for prefix in self._exempt:
            if path.startswith(prefix):
                return await call_next(request)  # type: ignore[misc]

        # Get client IP
        client_ip = request.client.host if request.client else "unknown"
        now = time.monotonic()
        window_start = now - 60.0

        # Periodic cleanup of stale IPs to prevent memory leak
        self._request_count += 1
        if self._request_count >= self._CLEANUP_INTERVAL:
            self._request_count = 0
            stale_ips = [ip for ip, ts in self._window.items() if not ts or ts[-1] < window_start]
            for ip in stale_ips:
                del self._window[ip]

        # Clean old entries and count recent requests
        timestamps = self._window[client_ip]
        timestamps[:] = [t for t in timestamps if t > window_start]

        if len(timestamps) >= self._rpm:
            return JSONResponse(
                {"error": "Rate limit exceeded", "retry_after_seconds": 60},
                status_code=429,
            )

        timestamps.append(now)
        return await call_next(request)  # type: ignore[misc]
