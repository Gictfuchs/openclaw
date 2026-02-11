"""Integration tests for health endpoint and rate limiting."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from openclaw.config import Settings
from openclaw.web.server import create_app


class TestHealthEndpoint:
    def _make_settings(self) -> Settings:
        return Settings(
            anthropic_api_key="test-key",
            telegram_bot_token="test-token",
            telegram_allowed_users=[123],
        )

    def test_health_no_agent(self) -> None:
        settings = self._make_settings()
        app = create_app(settings, {"agent": None})
        client = TestClient(app)
        response = client.get("/api/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["checks"]["agent"] is False

    def test_health_with_agent(self) -> None:
        settings = self._make_settings()
        agent = MagicMock()
        # Mock async check_availability

        async def mock_availability() -> dict[str, bool]:
            return {"claude": True}

        agent.llm.check_availability = mock_availability

        app = create_app(settings, {"agent": agent})
        client = TestClient(app)
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["checks"]["agent"] is True
        assert data["checks"]["llm"] is True

    def test_health_no_auth_required(self) -> None:
        """Health endpoint should NOT require authentication."""
        settings = self._make_settings()
        app = create_app(settings, {"agent": None})
        client = TestClient(app)
        # No login, should still get response
        response = client.get("/api/health")
        assert response.status_code in (200, 503)  # Either healthy or degraded, but not 401


class TestSettingsPage:
    def _make_settings(self) -> Settings:
        return Settings(
            anthropic_api_key="test-key",
            telegram_bot_token="test-token",
            telegram_allowed_users=[123],
        )

    def test_settings_redirects_without_auth(self) -> None:
        settings = self._make_settings()
        app = create_app(settings, {"agent": None})
        client = TestClient(app)
        response = client.get("/settings", follow_redirects=False)
        assert response.status_code == 303
        assert "/login" in response.headers.get("location", "")

    def test_settings_route_exists(self) -> None:
        settings = self._make_settings()
        app = create_app(settings, {"agent": None})
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/settings" in routes


class TestSecurityHeaders:
    def _make_settings(self) -> Settings:
        return Settings(
            anthropic_api_key="test-key",
            telegram_bot_token="test-token",
            telegram_allowed_users=[123],
        )

    def test_response_has_security_headers(self) -> None:
        settings = self._make_settings()
        app = create_app(settings, {"agent": None})
        client = TestClient(app)
        response = client.get("/api/health")
        assert response.headers.get("X-Frame-Options") == "DENY"
        assert response.headers.get("X-Content-Type-Options") == "nosniff"
        assert response.headers.get("X-XSS-Protection") == "1; mode=block"
        assert "default-src" in response.headers.get("Content-Security-Policy", "")
        assert "frame-ancestors 'none'" in response.headers.get("Content-Security-Policy", "")
        assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_permissions_policy_header(self) -> None:
        settings = self._make_settings()
        app = create_app(settings, {"agent": None})
        client = TestClient(app)
        response = client.get("/api/health")
        pp = response.headers.get("Permissions-Policy", "")
        assert "camera=()" in pp
        assert "microphone=()" in pp


class TestLogoutCSRF:
    def _make_settings(self) -> Settings:
        return Settings(
            anthropic_api_key="test-key",
            telegram_bot_token="test-token",
            telegram_allowed_users=[123],
        )

    def test_logout_rejects_get(self) -> None:
        """GET /logout should return 405 (Method Not Allowed)."""
        settings = self._make_settings()
        app = create_app(settings, {"agent": None})
        client = TestClient(app)
        response = client.get("/logout", follow_redirects=False)
        assert response.status_code == 405

    def test_logout_accepts_post(self) -> None:
        """POST /logout should redirect to /login."""
        settings = self._make_settings()
        app = create_app(settings, {"agent": None})
        client = TestClient(app)
        response = client.post("/logout", follow_redirects=False)
        assert response.status_code == 303
        assert "/login" in response.headers.get("location", "")
