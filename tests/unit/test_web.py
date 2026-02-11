"""Tests for web dashboard (auth, server, routes, chat)."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from openclaw.config import Settings
from openclaw.web.auth import do_login, do_logout, is_authenticated
from openclaw.web.routes.chat import WEB_USER_ID, _event_to_dict
from openclaw.web.server import create_app

# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


class TestAuth:
    def test_is_authenticated_false(self) -> None:
        request = MagicMock()
        request.session = {}
        assert is_authenticated(request) is False

    def test_is_authenticated_true(self) -> None:
        request = MagicMock()
        request.session = {"authenticated": True}
        assert is_authenticated(request) is True

    def test_do_login_correct(self) -> None:
        request = MagicMock()
        request.session = {}
        request.app.state.settings.web_secret_key.get_secret_value.return_value = "my-secret"
        assert do_login(request, "my-secret") is True
        assert request.session["authenticated"] is True

    def test_do_login_incorrect(self) -> None:
        request = MagicMock()
        request.session = {}
        request.app.state.settings.web_secret_key.get_secret_value.return_value = "my-secret"
        assert do_login(request, "wrong") is False
        assert "authenticated" not in request.session

    def test_do_logout(self) -> None:
        request = MagicMock()
        session = {"authenticated": True}
        request.session = session
        do_logout(request)
        assert len(session) == 0


# ---------------------------------------------------------------------------
# Event serialization tests
# ---------------------------------------------------------------------------


class TestEventToDict:
    def test_thinking_event(self) -> None:
        from openclaw.core.events import ThinkingEvent

        event = ThinkingEvent(content="hmm")
        result = _event_to_dict(event)
        assert result["type"] == "thinking"
        assert result["content"] == "hmm"
        assert "timestamp" in result

    def test_tool_call_event(self) -> None:
        from openclaw.core.events import ToolCallEvent

        event = ToolCallEvent(tool="web_search", input={"query": "test"})
        result = _event_to_dict(event)
        assert result["type"] == "tool_call"
        assert result["tool"] == "web_search"
        assert result["input"] == {"query": "test"}

    def test_tool_result_event_truncation(self) -> None:
        from openclaw.core.events import ToolResultEvent

        long_output = "x" * 3000
        event = ToolResultEvent(tool="web_scrape", output=long_output)
        result = _event_to_dict(event)
        assert result["type"] == "tool_result"
        assert len(result["output"]) < 3000
        assert "gekuerzt" in result["output"]

    def test_response_event(self) -> None:
        from openclaw.core.events import ResponseEvent

        event = ResponseEvent(content="Hello!")
        result = _event_to_dict(event)
        assert result["type"] == "response"
        assert result["content"] == "Hello!"

    def test_error_event(self) -> None:
        from openclaw.core.events import ErrorEvent

        event = ErrorEvent(message="fail", recoverable=False)
        result = _event_to_dict(event)
        assert result["type"] == "error"
        assert result["message"] == "fail"
        assert result["recoverable"] is False


# ---------------------------------------------------------------------------
# Server / App factory tests
# ---------------------------------------------------------------------------


class TestCreateApp:
    def _make_settings(self) -> Settings:
        return Settings(
            anthropic_api_key="test-key",
            telegram_bot_token="test-token",
            telegram_allowed_users=[123],
        )

    def test_create_app_returns_fastapi(self) -> None:
        settings = self._make_settings()
        app = create_app(settings, {"agent": None, "scheduler": None, "sub_agent_runner": None})
        assert app.title == "Fochs Dashboard"

    def test_app_has_routes(self) -> None:
        settings = self._make_settings()
        app = create_app(settings, {"agent": None})
        routes = [r.path for r in app.routes if hasattr(r, "path")]
        assert "/login" in routes
        assert "/" in routes
        assert "/api/status" in routes

    def test_login_page_renders(self) -> None:
        settings = self._make_settings()
        app = create_app(settings, {"agent": None})
        client = TestClient(app)
        response = client.get("/login")
        assert response.status_code == 200
        assert "Fochs" in response.text

    def test_dashboard_redirects_without_auth(self) -> None:
        settings = self._make_settings()
        app = create_app(settings, {"agent": None})
        client = TestClient(app)
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 303
        assert "/login" in response.headers.get("location", "")

    def test_api_status_requires_auth(self) -> None:
        settings = self._make_settings()
        app = create_app(settings, {"agent": None})
        client = TestClient(app)
        response = client.get("/api/status")
        assert response.status_code == 401

    def test_chat_page_redirects_without_auth(self) -> None:
        settings = self._make_settings()
        app = create_app(settings, {"agent": None})
        client = TestClient(app)
        response = client.get("/chat", follow_redirects=False)
        assert response.status_code == 303


# ---------------------------------------------------------------------------
# WebSocket constants
# ---------------------------------------------------------------------------


class TestWebSocketConstants:
    def test_web_user_id(self) -> None:
        assert WEB_USER_ID == 1_000_000
