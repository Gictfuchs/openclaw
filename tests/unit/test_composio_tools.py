"""Tests for the Composio brokered credential execution tools."""

from unittest.mock import AsyncMock

import pytest

from openclaw.integrations.composio import (
    ComposioAction,
    ComposioApp,
    ComposioClient,
    ComposioExecutionResult,
)
from openclaw.tools.composio_tools import (
    ComposioActionsTool,
    ComposioAppsTool,
    ComposioExecuteTool,
)


@pytest.fixture
def mock_client() -> AsyncMock:
    return AsyncMock(spec=ComposioClient)


# ---------------------------------------------------------------------------
# ComposioAppsTool
# ---------------------------------------------------------------------------


class TestComposioAppsTool:
    async def test_execute_lists_apps(self, mock_client: AsyncMock) -> None:
        mock_client.list_apps.return_value = [
            ComposioApp(key="slack", name="Slack", description="Team messaging", connected=True),
            ComposioApp(key="jira", name="Jira", description="Issue tracking", categories=["project-management"]),
        ]

        tool = ComposioAppsTool(client=mock_client)
        result = await tool.execute()

        assert "Slack" in result
        assert "slack" in result
        assert "[connected]" in result
        assert "Jira" in result
        assert "project-management" in result

    async def test_execute_connected_only(self, mock_client: AsyncMock) -> None:
        mock_client.get_connected_apps.return_value = [
            ComposioApp(key="slack", name="Slack", connected=True),
        ]

        tool = ComposioAppsTool(client=mock_client)
        result = await tool.execute(connected_only=True)

        assert "Slack" in result
        mock_client.get_connected_apps.assert_called_once()
        mock_client.list_apps.assert_not_called()

    async def test_execute_no_apps(self, mock_client: AsyncMock) -> None:
        mock_client.list_apps.return_value = []

        tool = ComposioAppsTool(client=mock_client)
        result = await tool.execute()

        assert "No Composio" in result

    async def test_execute_handles_error(self, mock_client: AsyncMock) -> None:
        mock_client.list_apps.side_effect = Exception("API down")

        tool = ComposioAppsTool(client=mock_client)
        result = await tool.execute()

        assert "Failed" in result

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = ComposioAppsTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "composio_apps"
        assert "input_schema" in defn


# ---------------------------------------------------------------------------
# ComposioActionsTool
# ---------------------------------------------------------------------------


class TestComposioActionsTool:
    async def test_execute_lists_actions(self, mock_client: AsyncMock) -> None:
        mock_client.list_actions.return_value = [
            ComposioAction(
                name="SLACK_SEND_MESSAGE",
                display_name="Send Message",
                description="Send a message to a Slack channel",
                app_key="slack",
            ),
            ComposioAction(
                name="SLACK_LIST_CHANNELS",
                display_name="List Channels",
                app_key="slack",
            ),
        ]

        tool = ComposioActionsTool(client=mock_client)
        result = await tool.execute(app_key="slack")

        assert "SLACK_SEND_MESSAGE" in result
        assert "Send Message" in result
        assert "SLACK_LIST_CHANNELS" in result
        mock_client.list_actions.assert_called_once_with(app_key="slack")

    async def test_execute_no_actions(self, mock_client: AsyncMock) -> None:
        mock_client.list_actions.return_value = []

        tool = ComposioActionsTool(client=mock_client)
        result = await tool.execute(app_key="unknown_app")

        assert "No actions" in result

    async def test_execute_handles_error(self, mock_client: AsyncMock) -> None:
        mock_client.list_actions.side_effect = Exception("Not found")

        tool = ComposioActionsTool(client=mock_client)
        result = await tool.execute(app_key="bad_app")

        assert "Failed" in result

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = ComposioActionsTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "composio_actions"
        assert "app_key" in defn["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# ComposioExecuteTool
# ---------------------------------------------------------------------------


class TestComposioExecuteTool:
    async def test_execute_success(self, mock_client: AsyncMock) -> None:
        mock_client.execute_action.return_value = ComposioExecutionResult(
            success=True,
            data={"message_id": "msg_123", "channel": "general"},
        )

        tool = ComposioExecuteTool(client=mock_client)
        result = await tool.execute(
            action="SLACK_SEND_MESSAGE",
            params={"channel": "general", "text": "Hello!"},
        )

        assert "successfully" in result
        assert "msg_123" in result
        mock_client.execute_action.assert_called_once_with(
            action_name="SLACK_SEND_MESSAGE",
            params={"channel": "general", "text": "Hello!"},
            entity_id="default",
        )

    async def test_execute_failure(self, mock_client: AsyncMock) -> None:
        mock_client.execute_action.return_value = ComposioExecutionResult(
            success=False,
            error="Channel not found",
        )

        tool = ComposioExecuteTool(client=mock_client)
        result = await tool.execute(action="SLACK_SEND_MESSAGE", params={"channel": "nonexistent"})

        assert "failed" in result
        assert "Channel not found" in result

    async def test_execute_with_entity_id(self, mock_client: AsyncMock) -> None:
        mock_client.execute_action.return_value = ComposioExecutionResult(success=True)

        tool = ComposioExecuteTool(client=mock_client)
        await tool.execute(action="SLACK_SEND_MESSAGE", entity_id="user_42")

        mock_client.execute_action.assert_called_once_with(
            action_name="SLACK_SEND_MESSAGE",
            params={},
            entity_id="user_42",
        )

    async def test_execute_truncates_large_response(self, mock_client: AsyncMock) -> None:
        mock_client.execute_action.return_value = ComposioExecutionResult(
            success=True,
            data={"large_field": "x" * 5000},
        )

        tool = ComposioExecuteTool(client=mock_client)
        result = await tool.execute(action="BIG_ACTION")

        assert "truncated" in result

    async def test_execute_handles_exception(self, mock_client: AsyncMock) -> None:
        mock_client.execute_action.side_effect = Exception("Network error")

        tool = ComposioExecuteTool(client=mock_client)
        result = await tool.execute(action="BROKEN_ACTION")

        assert "Failed" in result

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = ComposioExecuteTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "composio_execute"
        assert "action" in defn["input_schema"]["properties"]
        assert "params" in defn["input_schema"]["properties"]
