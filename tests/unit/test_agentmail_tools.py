"""Tests for the AgentMail tools."""

from unittest.mock import AsyncMock

import pytest

from openclaw.integrations.agentmail import (
    AgentInbox,
    AgentMailClient,
    AgentMailMessage,
    AgentMailSearchResult,
)
from openclaw.tools.agentmail_tools import (
    AgentMailInboxTool,
    AgentMailReadTool,
    AgentMailSearchTool,
    AgentMailSendTool,
)


@pytest.fixture
def mock_client() -> AsyncMock:
    return AsyncMock(spec=AgentMailClient)


# ---------------------------------------------------------------------------
# AgentMailInboxTool
# ---------------------------------------------------------------------------


class TestAgentMailInboxTool:
    async def test_execute_create_inbox(self, mock_client: AsyncMock) -> None:
        mock_client.create_inbox.return_value = AgentInbox(
            id="inbox_123",
            address="fochs-abc@agentmail.to",
            display_name="Fochs Bot",
        )

        tool = AgentMailInboxTool(client=mock_client)
        result = await tool.execute(action="create", display_name="Fochs Bot")

        assert "inbox_123" in result
        assert "fochs-abc@agentmail.to" in result
        assert "Fochs Bot" in result

    async def test_execute_list_inboxes(self, mock_client: AsyncMock) -> None:
        mock_client.list_inboxes.return_value = [
            AgentInbox(id="inbox_1", address="a@agentmail.to", display_name="Inbox A"),
            AgentInbox(id="inbox_2", address="b@agentmail.to"),
        ]

        tool = AgentMailInboxTool(client=mock_client)
        result = await tool.execute(action="list")

        assert "a@agentmail.to" in result
        assert "b@agentmail.to" in result
        assert "Inbox A" in result

    async def test_execute_list_no_inboxes(self, mock_client: AsyncMock) -> None:
        mock_client.list_inboxes.return_value = []

        tool = AgentMailInboxTool(client=mock_client)
        result = await tool.execute(action="list")

        assert "No agent" in result

    async def test_execute_unknown_action(self, mock_client: AsyncMock) -> None:
        tool = AgentMailInboxTool(client=mock_client)
        result = await tool.execute(action="delete")

        assert "Unknown" in result

    async def test_execute_handles_error(self, mock_client: AsyncMock) -> None:
        mock_client.create_inbox.side_effect = Exception("API error")

        tool = AgentMailInboxTool(client=mock_client)
        result = await tool.execute(action="create")

        assert "Failed" in result

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = AgentMailInboxTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "agentmail_inbox"
        assert "action" in defn["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# AgentMailReadTool
# ---------------------------------------------------------------------------


class TestAgentMailReadTool:
    async def test_execute_reads_messages(self, mock_client: AsyncMock) -> None:
        mock_client.get_messages.return_value = [
            AgentMailMessage(
                id="msg_1",
                inbox_id="inbox_1",
                from_address="sender@example.com",
                subject="Hello!",
                body="Hi, this is a test message.",
                is_read=False,
                received_at="2025-01-01",
            ),
        ]

        tool = AgentMailReadTool(client=mock_client)
        result = await tool.execute(inbox_id="inbox_1")

        assert "sender@example.com" in result
        assert "Hello!" in result
        assert "[UNREAD]" in result
        assert "test message" in result

    async def test_execute_no_messages(self, mock_client: AsyncMock) -> None:
        mock_client.get_messages.return_value = []

        tool = AgentMailReadTool(client=mock_client)
        result = await tool.execute(inbox_id="inbox_1")

        assert "No messages" in result

    async def test_execute_truncates_long_body(self, mock_client: AsyncMock) -> None:
        mock_client.get_messages.return_value = [
            AgentMailMessage(
                id="msg_1",
                inbox_id="inbox_1",
                from_address="sender@example.com",
                subject="Long",
                body="x" * 500,
            ),
        ]

        tool = AgentMailReadTool(client=mock_client)
        result = await tool.execute(inbox_id="inbox_1")

        assert "..." in result

    async def test_execute_handles_error(self, mock_client: AsyncMock) -> None:
        mock_client.get_messages.side_effect = Exception("API error")

        tool = AgentMailReadTool(client=mock_client)
        result = await tool.execute(inbox_id="inbox_1")

        assert "Failed" in result

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = AgentMailReadTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "agentmail_read"
        assert "inbox_id" in defn["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# AgentMailSendTool
# ---------------------------------------------------------------------------


class TestAgentMailSendTool:
    async def test_execute_sends_email(self, mock_client: AsyncMock) -> None:
        mock_client.send_message.return_value = "msg_sent_123"

        tool = AgentMailSendTool(client=mock_client)
        result = await tool.execute(
            inbox_id="inbox_1",
            to=["recipient@example.com"],
            subject="Test",
            body="Hello world!",
        )

        assert "sent successfully" in result
        assert "recipient@example.com" in result
        assert "msg_sent_123" in result

    async def test_execute_no_recipients(self, mock_client: AsyncMock) -> None:
        tool = AgentMailSendTool(client=mock_client)
        result = await tool.execute(inbox_id="inbox_1", to=[], subject="Test", body="Hi")

        assert "recipient" in result.lower()
        mock_client.send_message.assert_not_called()

    async def test_execute_empty_subject(self, mock_client: AsyncMock) -> None:
        tool = AgentMailSendTool(client=mock_client)
        result = await tool.execute(inbox_id="inbox_1", to=["a@b.com"], subject="  ", body="Hi")

        assert "empty" in result.lower()
        mock_client.send_message.assert_not_called()

    async def test_execute_handles_error(self, mock_client: AsyncMock) -> None:
        mock_client.send_message.side_effect = Exception("SMTP error")

        tool = AgentMailSendTool(client=mock_client)
        result = await tool.execute(
            inbox_id="inbox_1",
            to=["a@b.com"],
            subject="Test",
            body="Hi",
        )

        assert "Failed" in result

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = AgentMailSendTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "agentmail_send"
        assert "to" in defn["input_schema"]["properties"]
        assert "subject" in defn["input_schema"]["properties"]


# ---------------------------------------------------------------------------
# AgentMailSearchTool
# ---------------------------------------------------------------------------


class TestAgentMailSearchTool:
    async def test_execute_returns_results(self, mock_client: AsyncMock) -> None:
        mock_client.search.return_value = [
            AgentMailSearchResult(
                message_id="msg_1",
                subject="Invoice from Vendor",
                snippet="Your invoice for January is attached.",
                score=0.92,
                from_address="vendor@example.com",
            ),
        ]

        tool = AgentMailSearchTool(client=mock_client)
        result = await tool.execute(inbox_id="inbox_1", query="invoice")

        assert "Invoice from Vendor" in result
        assert "0.920" in result
        assert "vendor@example.com" in result

    async def test_execute_no_results(self, mock_client: AsyncMock) -> None:
        mock_client.search.return_value = []

        tool = AgentMailSearchTool(client=mock_client)
        result = await tool.execute(inbox_id="inbox_1", query="nonexistent")

        assert "No messages" in result

    async def test_execute_handles_error(self, mock_client: AsyncMock) -> None:
        mock_client.search.side_effect = Exception("Search error")

        tool = AgentMailSearchTool(client=mock_client)
        result = await tool.execute(inbox_id="inbox_1", query="test")

        assert "failed" in result.lower()

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = AgentMailSearchTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "agentmail_search"
        assert "query" in defn["input_schema"]["properties"]
