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
