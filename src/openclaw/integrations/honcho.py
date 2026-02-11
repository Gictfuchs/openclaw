"""Honcho memory layer client.

Provides cloud-based entity-centric memory with effortless state retrieval.
Complements (does not replace) the local ChromaDB-based LongTermMemory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import structlog

from openclaw.integrations import check_response_size, validate_id

logger = structlog.get_logger()

_DEFAULT_BASE_URL = "https://api.honcho.dev/v1"


@dataclass
class HonchoSession:
    """A Honcho conversation session."""

    id: str
    app_id: str
    user_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""


@dataclass
class HonchoMessage:
    """A message within a Honcho session."""

    id: str
    session_id: str
    role: str  # "user" or "assistant"
    content: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HonchoContext:
    """Effortless state retrieval result — Honcho's core feature."""

    session_id: str
    context: str
    tokens: int = 0


@dataclass
class HonchoCollection:
    """A Honcho vector collection for long-term knowledge."""

    id: str
    name: str
    app_id: str
    user_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class HonchoQueryResult:
    """A semantic search result from a Honcho collection."""

    content: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class HonchoClient:
    """Client for the Honcho memory layer API.

    Honcho provides entity-centric memory with:
    - Effortless State Retrieval (``get_context()``)
    - Session management with message history
    - Semantic search across vector collections
    """

    def __init__(
        self,
        api_key: str,
        app_id: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key
        self._app_id = app_id
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    async def create_session(
        self,
        user_id: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> HonchoSession:
        """Create a new conversation session."""
        user_id = validate_id(user_id, "user_id")
        payload: dict[str, Any] = {"metadata": metadata or {}}

        try:
            resp = await self._client.post(
                f"{self._base_url}/apps/{self._app_id}/users/{user_id}/sessions",
                json=payload,
            )
            resp.raise_for_status()
            check_response_size(resp.content, context="honcho_create_session")
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("honcho_create_session_error", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("honcho_create_session_error", error=str(e))
            raise

        session = HonchoSession(
            id=data.get("id", ""),
            app_id=self._app_id,
            user_id=user_id,
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at", ""),
        )
        logger.info("honcho_session_created", session_id=session.id)
        return session

    async def list_sessions(self, user_id: str = "default") -> list[HonchoSession]:
        """List sessions for a user."""
        user_id = validate_id(user_id, "user_id")
        try:
            resp = await self._client.get(
                f"{self._base_url}/apps/{self._app_id}/users/{user_id}/sessions",
            )
            resp.raise_for_status()
            check_response_size(resp.content, context="honcho_list_sessions")
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("honcho_list_sessions_error", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("honcho_list_sessions_error", error=str(e))
            raise

        sessions = []
        items = data if isinstance(data, list) else data.get("items", [])
        for item in items:
            sessions.append(
                HonchoSession(
                    id=item.get("id", ""),
                    app_id=self._app_id,
                    user_id=user_id,
                    metadata=item.get("metadata", {}),
                    created_at=item.get("created_at", ""),
                )
            )

        logger.info("honcho_sessions_listed", count=len(sessions))
        return sessions

    # ------------------------------------------------------------------
    # Context (core feature)
    # ------------------------------------------------------------------

    async def get_context(
        self,
        session_id: str,
        user_id: str = "default",
    ) -> HonchoContext:
        """Effortless State Retrieval — get context for a session.

        This is Honcho's core feature: it returns a condensed representation
        of the session state optimized for LLM consumption.
        """
        session_id = validate_id(session_id, "session_id")
        user_id = validate_id(user_id, "user_id")
        try:
            resp = await self._client.get(
                f"{self._base_url}/apps/{self._app_id}/users/{user_id}/sessions/{session_id}/context",
            )
            resp.raise_for_status()
            check_response_size(resp.content, context="honcho_get_context")
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("honcho_get_context_error", status=e.response.status_code, session_id=session_id)
            raise
        except Exception as e:
            logger.error("honcho_get_context_error", error=str(e), session_id=session_id)
            raise

        return HonchoContext(
            session_id=session_id,
            context=data.get("context", data.get("content", "")),
            tokens=data.get("tokens", 0),
        )

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        user_id: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> HonchoMessage:
        """Add a message to a session."""
        session_id = validate_id(session_id, "session_id")
        user_id = validate_id(user_id, "user_id")
        payload: dict[str, Any] = {
            "role": role,
            "content": content,
            "metadata": metadata or {},
        }

        try:
            resp = await self._client.post(
                f"{self._base_url}/apps/{self._app_id}/users/{user_id}/sessions/{session_id}/messages",
                json=payload,
            )
            resp.raise_for_status()
            check_response_size(resp.content, context="honcho_add_message")
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("honcho_add_message_error", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("honcho_add_message_error", error=str(e))
            raise

        return HonchoMessage(
            id=data.get("id", ""),
            session_id=session_id,
            role=data.get("role", role),
            content=data.get("content", content),
            metadata=data.get("metadata", {}),
        )

    # ------------------------------------------------------------------
    # Collections (vector storage)
    # ------------------------------------------------------------------

    async def create_collection(
        self,
        name: str,
        user_id: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> HonchoCollection:
        """Create a vector collection for long-term knowledge."""
        user_id = validate_id(user_id, "user_id")
        payload: dict[str, Any] = {
            "name": name,
            "metadata": metadata or {},
        }

        try:
            resp = await self._client.post(
                f"{self._base_url}/apps/{self._app_id}/users/{user_id}/collections",
                json=payload,
            )
            resp.raise_for_status()
            check_response_size(resp.content, context="honcho_create_collection")
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("honcho_create_collection_error", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("honcho_create_collection_error", error=str(e))
            raise

        return HonchoCollection(
            id=data.get("id", ""),
            name=data.get("name", name),
            app_id=self._app_id,
            user_id=user_id,
            metadata=data.get("metadata", {}),
        )

    async def add_to_collection(
        self,
        collection_id: str,
        content: str,
        user_id: str = "default",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Add content to a vector collection."""
        collection_id = validate_id(collection_id, "collection_id")
        user_id = validate_id(user_id, "user_id")
        payload: dict[str, Any] = {
            "content": content,
            "metadata": metadata or {},
        }

        try:
            resp = await self._client.post(
                f"{self._base_url}/apps/{self._app_id}/users/{user_id}/collections/{collection_id}/documents",
                json=payload,
            )
            resp.raise_for_status()
            check_response_size(resp.content, context="honcho_add_to_collection")
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("honcho_add_to_collection_error", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("honcho_add_to_collection_error", error=str(e))
            raise

        doc_id = data.get("id", "")
        logger.info("honcho_document_added", collection_id=collection_id, doc_id=doc_id)
        return doc_id

    async def query_collection(
        self,
        collection_id: str,
        query: str,
        user_id: str = "default",
        top_k: int = 5,
    ) -> list[HonchoQueryResult]:
        """Semantic search across a collection."""
        collection_id = validate_id(collection_id, "collection_id")
        user_id = validate_id(user_id, "user_id")
        payload: dict[str, Any] = {
            "query": query,
            "top_k": top_k,
        }

        try:
            resp = await self._client.post(
                f"{self._base_url}/apps/{self._app_id}/users/{user_id}/collections/{collection_id}/query",
                json=payload,
            )
            resp.raise_for_status()
            check_response_size(resp.content, context="honcho_query")
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("honcho_query_error", status=e.response.status_code)
            raise
        except Exception as e:
            logger.error("honcho_query_error", error=str(e))
            raise

        results = []
        items = data if isinstance(data, list) else data.get("results", [])
        for item in items:
            results.append(
                HonchoQueryResult(
                    content=item.get("content", ""),
                    score=item.get("score", 0.0),
                    metadata=item.get("metadata", {}),
                )
            )

        logger.info("honcho_query", collection_id=collection_id, results=len(results))
        return results

    async def close(self) -> None:
        await self._client.aclose()
