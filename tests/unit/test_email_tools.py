"""Tests for email tools."""

from unittest.mock import AsyncMock

import pytest

from openclaw.integrations.email import EmailClient, EmailMessage
from openclaw.tools.email_tools import ReadEmailsTool, SendEmailTool


@pytest.fixture
def mock_email_client():
    return AsyncMock(spec=EmailClient)


class TestReadEmailsTool:
    async def test_formats_emails(self, mock_email_client: AsyncMock) -> None:
        mock_email_client.fetch_recent.return_value = [
            EmailMessage(
                subject="Meeting tomorrow",
                sender="boss@company.com",
                to="me@example.com",
                date="Mon, 01 Jan 2025 09:00:00",
                body="Please join the meeting at 10am.\nBring your laptop.",
                is_read=True,
            ),
            EmailMessage(
                subject="Newsletter",
                sender="news@example.com",
                to="me@example.com",
                date="Mon, 01 Jan 2025 08:00:00",
                body="Latest news from the tech world...",
                is_read=False,
            ),
        ]

        tool = ReadEmailsTool(client=mock_email_client)
        result = await tool.execute(limit=5)

        assert "Meeting tomorrow" in result
        assert "boss@company.com" in result
        assert "[NEW]" in result  # Unread marker
        assert "Newsletter" in result

    async def test_no_emails(self, mock_email_client: AsyncMock) -> None:
        mock_email_client.fetch_recent.return_value = []

        tool = ReadEmailsTool(client=mock_email_client)
        result = await tool.execute()

        assert "No emails found" in result

    async def test_error_handling(self, mock_email_client: AsyncMock) -> None:
        mock_email_client.fetch_recent.side_effect = Exception("Connection refused")

        tool = ReadEmailsTool(client=mock_email_client)
        result = await tool.execute()

        assert "Error" in result

    async def test_limit_capped(self, mock_email_client: AsyncMock) -> None:
        mock_email_client.fetch_recent.return_value = []

        tool = ReadEmailsTool(client=mock_email_client)
        await tool.execute(limit=50)

        mock_email_client.fetch_recent.assert_called_once_with(folder="INBOX", limit=15)

    def test_tool_definition(self, mock_email_client: AsyncMock) -> None:
        tool = ReadEmailsTool(client=mock_email_client)
        defn = tool.to_definition()
        assert defn["name"] == "read_emails"


class TestSendEmailTool:
    async def test_sends_email(self, mock_email_client: AsyncMock) -> None:
        tool = SendEmailTool(client=mock_email_client)
        result = await tool.execute(
            to="recipient@example.com",
            subject="Test Subject",
            body="Hello!",
        )

        mock_email_client.send.assert_called_once_with(
            to="recipient@example.com",
            subject="Test Subject",
            body="Hello!",
        )
        assert "Email sent" in result
        assert "recipient@example.com" in result

    async def test_send_error(self, mock_email_client: AsyncMock) -> None:
        mock_email_client.send.side_effect = Exception("SMTP error")

        tool = SendEmailTool(client=mock_email_client)
        result = await tool.execute(to="a@b.com", subject="X", body="Y")

        assert "Error" in result

    def test_tool_definition(self, mock_email_client: AsyncMock) -> None:
        tool = SendEmailTool(client=mock_email_client)
        defn = tool.to_definition()
        assert defn["name"] == "send_email"
        assert "to" in defn["input_schema"]["required"]
        assert "subject" in defn["input_schema"]["required"]
        assert "body" in defn["input_schema"]["required"]
