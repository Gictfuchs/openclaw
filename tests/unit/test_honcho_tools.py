"""Tests for the Honcho memory layer tools."""

from unittest.mock import AsyncMock

import pytest

from openclaw.integrations.honcho import (
    HonchoClient,
    HonchoContext,
    HonchoQueryResult,
    HonchoSession,
)
from openclaw.tools.honcho_tools import (
    HonchoContextTool,
    HonchoQueryTool,
    HonchoRememberTool,
    HonchoSessionTool,
)


@pytest.fixture
def mock_client() -> AsyncMock:
    return AsyncMock(spec=HonchoClient)


# ---------------------------------------------------------------------------
# HonchoContextTool
# ---------------------------------------------------------------------------


class TestHonchoContextTool:
    async def test_execute_returns_context(self, mock_client: AsyncMock) -> None:
        mock_client.get_context.return_value = HonchoContext(
            session_id="sess_123",
            context="User prefers dark mode and speaks German. Last discussed topic: OpenClaw setup.",
            tokens=42,
        )

        tool = HonchoContextTool(client=mock_client)
        result = await tool.execute(session_id="sess_123")

        assert "sess_123" in result
        assert "42 tokens" in result
        assert "dark mode" in result
        assert "German" in result

    async def test_execute_handles_error(self, mock_client: AsyncMock) -> None:
        mock_client.get_context.side_effect = Exception("Session not found")

        tool = HonchoContextTool(client=mock_client)
        result = await tool.execute(session_id="bad_session")

        assert "Failed" in result

    async def test_execute_with_user_id(self, mock_client: AsyncMock) -> None:
        mock_client.get_context.return_value = HonchoContext(
            session_id="sess_456",
            context="User context",
        )

        tool = HonchoContextTool(client=mock_client)
        await tool.execute(session_id="sess_456", user_id="user_42")

        mock_client.get_context.assert_called_once_with(session_id="sess_456", user_id="user_42")

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = HonchoContextTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "honcho_context"
        assert "session_id" in defn["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# HonchoRememberTool
# ---------------------------------------------------------------------------


class TestHonchoRememberTool:
    async def test_execute_stores_content(self, mock_client: AsyncMock) -> None:
        mock_client.add_to_collection.return_value = "doc_abc"

        tool = HonchoRememberTool(client=mock_client)
        result = await tool.execute(
            collection_id="col_123",
            content="User prefers Python over JavaScript",
        )

        assert "stored" in result
        assert "col_123" in result
        assert "doc_abc" in result

    async def test_execute_empty_content(self, mock_client: AsyncMock) -> None:
        tool = HonchoRememberTool(client=mock_client)
        result = await tool.execute(collection_id="col_123", content="   ")

        assert "empty" in result.lower()
        mock_client.add_to_collection.assert_not_called()

    async def test_execute_handles_error(self, mock_client: AsyncMock) -> None:
        mock_client.add_to_collection.side_effect = Exception("Collection not found")

        tool = HonchoRememberTool(client=mock_client)
        result = await tool.execute(collection_id="bad_col", content="test")

        assert "Failed" in result

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = HonchoRememberTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "honcho_remember"
        assert "collection_id" in defn["input_schema"]["properties"]
        assert "content" in defn["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# HonchoQueryTool
# ---------------------------------------------------------------------------


class TestHonchoQueryTool:
    async def test_execute_returns_results(self, mock_client: AsyncMock) -> None:
        mock_client.query_collection.return_value = [
            HonchoQueryResult(content="User likes dark mode", score=0.95),
            HonchoQueryResult(content="Prefers German UI", score=0.82),
        ]

        tool = HonchoQueryTool(client=mock_client)
        result = await tool.execute(collection_id="col_123", query="user preferences")

        assert "dark mode" in result
        assert "0.950" in result
        assert "German" in result
        assert "2 matches" in result

    async def test_execute_no_results(self, mock_client: AsyncMock) -> None:
        mock_client.query_collection.return_value = []

        tool = HonchoQueryTool(client=mock_client)
        result = await tool.execute(collection_id="col_123", query="nonexistent")

        assert "No results" in result

    async def test_execute_caps_top_k(self, mock_client: AsyncMock) -> None:
        mock_client.query_collection.return_value = []

        tool = HonchoQueryTool(client=mock_client)
        await tool.execute(collection_id="col_123", query="test", top_k=100)

        mock_client.query_collection.assert_called_once_with(
            collection_id="col_123",
            query="test",
            user_id="default",
            top_k=10,
        )

    async def test_execute_handles_error(self, mock_client: AsyncMock) -> None:
        mock_client.query_collection.side_effect = Exception("API error")

        tool = HonchoQueryTool(client=mock_client)
        result = await tool.execute(collection_id="col_123", query="test")

        assert "failed" in result.lower()

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = HonchoQueryTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "honcho_query"
        assert "query" in defn["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# HonchoSessionTool
# ---------------------------------------------------------------------------


class TestHonchoSessionTool:
    async def test_execute_create_session(self, mock_client: AsyncMock) -> None:
        mock_client.create_session.return_value = HonchoSession(
            id="sess_new",
            app_id="app_123",
            user_id="default",
        )

        tool = HonchoSessionTool(client=mock_client)
        result = await tool.execute(action="create")

        assert "sess_new" in result
        assert "created" in result

    async def test_execute_list_sessions(self, mock_client: AsyncMock) -> None:
        mock_client.list_sessions.return_value = [
            HonchoSession(id="sess_1", app_id="app_123", created_at="2025-01-01"),
            HonchoSession(id="sess_2", app_id="app_123", created_at="2025-01-02"),
        ]

        tool = HonchoSessionTool(client=mock_client)
        result = await tool.execute(action="list")

        assert "sess_1" in result
        assert "sess_2" in result
        assert "2" in result

    async def test_execute_list_no_sessions(self, mock_client: AsyncMock) -> None:
        mock_client.list_sessions.return_value = []

        tool = HonchoSessionTool(client=mock_client)
        result = await tool.execute(action="list")

        assert "No Honcho" in result

    async def test_execute_unknown_action(self, mock_client: AsyncMock) -> None:
        tool = HonchoSessionTool(client=mock_client)
        result = await tool.execute(action="delete")

        assert "Unknown" in result

    async def test_execute_create_handles_error(self, mock_client: AsyncMock) -> None:
        mock_client.create_session.side_effect = Exception("API error")

        tool = HonchoSessionTool(client=mock_client)
        result = await tool.execute(action="create")

        assert "Failed" in result

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = HonchoSessionTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "honcho_session"
        assert "action" in defn["input_schema"]["properties"]
