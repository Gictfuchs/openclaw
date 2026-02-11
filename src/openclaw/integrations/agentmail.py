"""AgentMail email API client.

Provides agent-owned inboxes (@agentmail.to) with semantic search
and auto-labeling. Separate from the user's personal email (IMAP/SMTP).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from openclaw.integrations import validate_id

logger = structlog.get_logger()

_DEFAULT_BASE_URL = "https://api.agentmail.to/v1"


@dataclass
class AgentInbox:
    """An agent-owned email inbox."""

    id: str
    address: str  # e.g. fochs-123@agentmail.to
    display_name: str = ""
    created_at: str = ""


@dataclass
class AgentMailMessage:
    """An email message in an agent inbox."""

    id: str
    inbox_id: str
    from_address: str = ""
    to_addresses: list[str] = field(default_factory=list)
    subject: str = ""
    body: str = ""
    is_read: bool = False
    received_at: str = ""
    labels: list[str] = field(default_factory=list)


@dataclass
class AgentMailSearchResult:
    """A semantic search result from AgentMail."""

    message_id: str
    subject: str
    snippet: str
    score: float = 0.0
    from_address: str = ""


class AgentMailClient:
    """Client for the AgentMail API.

    AgentMail provides agent-owned inboxes with:
    - Disposable @agentmail.to addresses
    - Semantic search across messages
    - Auto-labeling and data extraction

    This is separate from the user's personal email (IMAP/SMTP).
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    # ------------------------------------------------------------------
    # Inboxes
    # ------------------------------------------------------------------

    async def create_inbox(self, display_name: str = "") -> AgentInbox:
        """Create a new agent-owned inbox."""
        payload: dict[str, Any] = {}
        if display_name:
            payload["display_name"] = display_name

        try:
            resp = await self._client.post(f"{self._base_url}/inboxes", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("agentmail_create_inbox_error", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("agentmail_create_inbox_error", error=str(e))
            raise

        inbox = AgentInbox(
            id=data.get("id", ""),
            address=data.get("address", data.get("email", "")),
            display_name=data.get("display_name", display_name),
            created_at=data.get("created_at", ""),
        )
        logger.info("agentmail_inbox_created", inbox_id=inbox.id, address=inbox.address)
        return inbox

    async def list_inboxes(self) -> list[AgentInbox]:
        """List all agent-owned inboxes."""
        try:
            resp = await self._client.get(f"{self._base_url}/inboxes")
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("agentmail_list_inboxes_error", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("agentmail_list_inboxes_error", error=str(e))
            raise

        inboxes = []
        items = data if isinstance(data, list) else data.get("inboxes", data.get("items", []))
        for item in items:
            inboxes.append(
                AgentInbox(
                    id=item.get("id", ""),
                    address=item.get("address", item.get("email", "")),
                    display_name=item.get("display_name", ""),
                    created_at=item.get("created_at", ""),
                )
            )

        logger.info("agentmail_inboxes_listed", count=len(inboxes))
        return inboxes

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def get_messages(
        self,
        inbox_id: str,
        limit: int = 20,
        unread_only: bool = False,
    ) -> list[AgentMailMessage]:
        """Get messages from an inbox."""
        inbox_id = validate_id(inbox_id, "inbox_id")
        params: dict[str, Any] = {"limit": min(limit, 50)}
        if unread_only:
            params["unread"] = "true"

        try:
            resp = await self._client.get(
                f"{self._base_url}/inboxes/{inbox_id}/messages",
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("agentmail_get_messages_error", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("agentmail_get_messages_error", error=str(e))
            raise

        messages = []
        items = data if isinstance(data, list) else data.get("messages", data.get("items", []))
        for item in items:
            messages.append(self._parse_message(item, inbox_id))

        logger.info("agentmail_messages", inbox_id=inbox_id, count=len(messages))
        return messages

    async def send_message(
        self,
        inbox_id: str,
        to: list[str],
        subject: str,
        body: str,
    ) -> str:
        """Send an email from an agent inbox."""
        inbox_id = validate_id(inbox_id, "inbox_id")
        payload = {
            "to": to,
            "subject": subject,
            "body": body,
        }

        try:
            resp = await self._client.post(
                f"{self._base_url}/inboxes/{inbox_id}/messages",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("agentmail_send_error", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("agentmail_send_error", error=str(e))
            raise

        msg_id = data.get("id", data.get("message_id", ""))
        logger.info("agentmail_sent", inbox_id=inbox_id, to=to, message_id=msg_id)
        return msg_id

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        inbox_id: str,
        query: str,
        limit: int = 10,
    ) -> list[AgentMailSearchResult]:
        """Semantic search across inbox messages."""
        inbox_id = validate_id(inbox_id, "inbox_id")
        payload = {
            "query": query,
            "limit": min(limit, 20),
        }

        try:
            resp = await self._client.post(
                f"{self._base_url}/inboxes/{inbox_id}/search",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("agentmail_search_error", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("agentmail_search_error", error=str(e))
            raise

        results = []
        items = data if isinstance(data, list) else data.get("results", [])
        for item in items:
            results.append(
                AgentMailSearchResult(
                    message_id=item.get("message_id", item.get("id", "")),
                    subject=item.get("subject", ""),
                    snippet=item.get("snippet", item.get("content", "")),
                    score=item.get("score", 0.0),
                    from_address=item.get("from", item.get("from_address", "")),
                )
            )

        logger.info("agentmail_search", inbox_id=inbox_id, query=query, results=len(results))
        return results

    @staticmethod
    def _parse_message(data: dict[str, Any], inbox_id: str) -> AgentMailMessage:
        """Parse a message from API response data."""
        return AgentMailMessage(
            id=data.get("id", ""),
            inbox_id=inbox_id,
            from_address=data.get("from", data.get("from_address", "")),
            to_addresses=data.get("to", data.get("to_addresses", [])),
            subject=data.get("subject", ""),
            body=data.get("body", data.get("text", "")),
            is_read=data.get("is_read", data.get("read", False)),
            received_at=data.get("received_at", data.get("date", "")),
            labels=data.get("labels", []),
        )

    async def close(self) -> None:
        await self._client.aclose()
