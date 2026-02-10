"""Email tools for the agent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from openclaw.tools.base import BaseTool

if TYPE_CHECKING:
    from openclaw.integrations.email import EmailClient

logger = structlog.get_logger()


class ReadEmailsTool(BaseTool):
    """Read recent emails from the inbox."""

    name = "read_emails"
    description = (
        "Read recent emails from the inbox. Returns subject, sender, date, and a preview of the body."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Number of recent emails to fetch (default 5, max 15).",
            },
            "folder": {
                "type": "string",
                "description": "IMAP folder to read from (default 'INBOX').",
            },
        },
        "required": [],
    }

    def __init__(self, client: EmailClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        limit = min(kwargs.get("limit", 5), 15)
        folder = kwargs.get("folder", "INBOX")

        try:
            messages = await self._client.fetch_recent(folder=folder, limit=limit)
        except Exception as e:
            return f"Error reading emails: {e}"

        if not messages:
            return "No emails found."

        parts = [f"Recent emails ({len(messages)}):\n"]
        for msg in messages:
            read_marker = "" if msg.is_read else "[NEW] "
            preview = msg.body[:200].replace("\n", " ").strip()
            parts.append(
                f"{read_marker}From: {msg.sender}\n"
                f"  Subject: {msg.subject}\n"
                f"  Date: {msg.date}\n"
                f"  Preview: {preview}...\n"
            )

        return "\n".join(parts)


class SendEmailTool(BaseTool):
    """Send an email."""

    name = "send_email"
    description = "Send an email to a specified recipient."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient email address.",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line.",
            },
            "body": {
                "type": "string",
                "description": "Email body text.",
            },
        },
        "required": ["to", "subject", "body"],
    }

    def __init__(self, client: EmailClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        to = kwargs["to"]
        subject = kwargs["subject"]
        body = kwargs["body"]

        try:
            await self._client.send(to=to, subject=subject, body=body)
        except Exception as e:
            return f"Error sending email: {e}"

        return f"Email sent to {to} with subject: {subject}"
