"""AgentMail tools for the agent.

Provides agent-owned inboxes (@agentmail.to) — separate from
the user's personal email (IMAP/SMTP EmailClient).
"""

from typing import Any

import structlog

from openclaw.integrations.agentmail import AgentMailClient
from openclaw.tools.base import BaseTool

logger = structlog.get_logger()


class AgentMailInboxTool(BaseTool):
    """Create or list agent-owned email inboxes."""

    name = "agentmail_inbox"
    description = (
        "Manage agent-owned email inboxes (@agentmail.to). "
        "Create a new disposable inbox or list existing ones. "
        "These are separate from the user's personal email."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action: 'create' or 'list'.",
                "enum": ["create", "list"],
            },
            "display_name": {
                "type": "string",
                "description": "Display name for new inbox (only for 'create').",
            },
        },
        "required": ["action"],
    }

    def __init__(self, client: AgentMailClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]

        if action == "create":
            display_name = kwargs.get("display_name", "")
            try:
                inbox = await self._client.create_inbox(display_name=display_name)
            except Exception as e:
                return f"Failed to create inbox: {e}"

            return (
                f"Agent inbox created:\n"
                f"  ID: {inbox.id}\n"
                f"  Address: {inbox.address}\n"
                f"  Name: {inbox.display_name or '(none)'}"
            )

        if action == "list":
            try:
                inboxes = await self._client.list_inboxes()
            except Exception as e:
                return f"Failed to list inboxes: {e}"

            if not inboxes:
                return "No agent inboxes found."

            parts = [f"Agent inboxes ({len(inboxes)}):\n"]
            for inbox in inboxes:
                name = f" ({inbox.display_name})" if inbox.display_name else ""
                parts.append(f"  - {inbox.address}{name} [id: {inbox.id}]")

            return "\n".join(parts)

        return f"Unknown action: {action}. Use 'create' or 'list'."


class AgentMailReadTool(BaseTool):
    """Read messages from an agent inbox."""

    name = "agentmail_read"
    description = "Read email messages from an agent-owned inbox. Can filter for unread messages only."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "inbox_id": {
                "type": "string",
                "description": "The inbox ID to read from.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum messages to return (1-20, default 10).",
            },
            "unread_only": {
                "type": "boolean",
                "description": "Only show unread messages (default: false).",
            },
        },
        "required": ["inbox_id"],
    }

    def __init__(self, client: AgentMailClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        inbox_id = kwargs["inbox_id"]
        limit = min(kwargs.get("limit", 10), 20)
        unread_only = kwargs.get("unread_only", False)

        try:
            messages = await self._client.get_messages(
                inbox_id=inbox_id,
                limit=limit,
                unread_only=unread_only,
            )
        except Exception as e:
            return f"Failed to read messages: {e}"

        if not messages:
            return "No messages in this inbox."

        parts = [f"Messages ({len(messages)}):\n"]
        for msg in messages:
            read_mark = "" if msg.is_read else " [UNREAD]"
            labels = f" {msg.labels}" if msg.labels else ""
            body_preview = msg.body[:200] + "..." if len(msg.body) > 200 else msg.body
            parts.append(
                f"  From: {msg.from_address}{read_mark}{labels}\n"
                f"  Subject: {msg.subject}\n"
                f"  Date: {msg.received_at}\n"
                f"  {body_preview}\n"
            )

        return "\n".join(parts)


class AgentMailSendTool(BaseTool):
    """Send an email from an agent inbox."""

    name = "agentmail_send"
    description = (
        "Send an email from an agent-owned inbox (@agentmail.to). "
        "The email is sent from the agent's address, not the user's personal email."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "inbox_id": {
                "type": "string",
                "description": "The inbox ID to send from.",
            },
            "to": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of recipient email addresses.",
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
        "required": ["inbox_id", "to", "subject", "body"],
    }

    def __init__(self, client: AgentMailClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        inbox_id = kwargs["inbox_id"]
        to = kwargs["to"]
        subject = kwargs["subject"]
        body = kwargs["body"]

        if not to:
            return "Error: At least one recipient is required."

        if not subject.strip():
            return "Error: Subject cannot be empty."

        try:
            msg_id = await self._client.send_message(
                inbox_id=inbox_id,
                to=to,
                subject=subject,
                body=body,
            )
        except Exception as e:
            return f"Failed to send email: {e}"

        recipients = ", ".join(to)
        return f"Email sent successfully to {recipients} (message ID: {msg_id})."


class AgentMailSearchTool(BaseTool):
    """Semantic search across agent inbox messages."""

    name = "agentmail_search"
    description = (
        "Search agent inbox messages using semantic similarity. "
        "Finds messages by meaning rather than exact keyword matching."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "inbox_id": {
                "type": "string",
                "description": "The inbox ID to search.",
            },
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum results (1-10, default 5).",
            },
        },
        "required": ["inbox_id", "query"],
    }

    def __init__(self, client: AgentMailClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        inbox_id = kwargs["inbox_id"]
        query = kwargs["query"]
        limit = min(kwargs.get("limit", 5), 10)

        try:
            results = await self._client.search(
                inbox_id=inbox_id,
                query=query,
                limit=limit,
            )
        except Exception as e:
            return f"AgentMail search failed: {e}"

        if not results:
            return f"No messages found for '{query}'."

        parts = [f"Search results for '{query}' ({len(results)} matches):\n"]
        for i, r in enumerate(results, 1):
            score = f" (score: {r.score:.3f})" if r.score is not None else ""
            parts.append(f"{i}.{score} {r.subject}\n   From: {r.from_address}\n   {r.snippet}")

        return "\n".join(parts)
