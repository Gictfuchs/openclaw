"""Honcho memory layer tools for the agent.

Complements (does not replace) the local ChromaDB-based memory.
Local = ChromaDB, Cloud = Honcho.
"""

from typing import Any

import structlog

from openclaw.integrations.honcho import HonchoClient
from openclaw.tools.base import BaseTool

logger = structlog.get_logger()


class HonchoContextTool(BaseTool):
    """Retrieve context for a Honcho session (effortless state retrieval)."""

    name = "honcho_context"
    description = (
        "Get condensed context for a Honcho session. This is Honcho's core feature: "
        "it returns a state representation optimized for LLM consumption. "
        "Use this to recall what happened in previous interactions."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "The Honcho session ID to get context for.",
            },
            "user_id": {
                "type": "string",
                "description": "User ID (default: 'default').",
            },
        },
        "required": ["session_id"],
    }

    def __init__(self, client: HonchoClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        session_id = kwargs["session_id"]
        user_id = kwargs.get("user_id", "default")

        try:
            context = await self._client.get_context(session_id=session_id, user_id=user_id)
        except Exception as e:
            return f"Failed to get Honcho context: {e}"

        parts = [f"Honcho Context (session: {context.session_id})"]
        if context.tokens:
            parts[0] += f" [{context.tokens} tokens]"
        parts.append(f"\n{context.context}")

        return "\n".join(parts)


class HonchoRememberTool(BaseTool):
    """Store content in a Honcho collection for long-term memory."""

    name = "honcho_remember"
    description = (
        "Store information in a Honcho collection for long-term retrieval. "
        "Useful for saving facts, preferences, or knowledge that should persist. "
        "Complements local memory (ChromaDB) with cloud-based storage."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "collection_id": {
                "type": "string",
                "description": "The collection ID to store in.",
            },
            "content": {
                "type": "string",
                "description": "The content to remember.",
            },
            "user_id": {
                "type": "string",
                "description": "User ID (default: 'default').",
            },
        },
        "required": ["collection_id", "content"],
    }

    def __init__(self, client: HonchoClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        collection_id = kwargs["collection_id"]
        content = kwargs["content"]
        user_id = kwargs.get("user_id", "default")

        if not content.strip():
            return "Error: Content cannot be empty."

        try:
            doc_id = await self._client.add_to_collection(
                collection_id=collection_id,
                content=content,
                user_id=user_id,
            )
        except Exception as e:
            return f"Failed to store in Honcho: {e}"

        return f"Content stored in Honcho collection '{collection_id}' (doc: {doc_id})."


class HonchoQueryTool(BaseTool):
    """Semantic search across Honcho collections."""

    name = "honcho_query"
    description = (
        "Search Honcho collections for relevant information using semantic similarity. "
        "Returns the most relevant content matching your query."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "collection_id": {
                "type": "string",
                "description": "The collection ID to search.",
            },
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of results to return (1-10, default 5).",
            },
            "user_id": {
                "type": "string",
                "description": "User ID (default: 'default').",
            },
        },
        "required": ["collection_id", "query"],
    }

    def __init__(self, client: HonchoClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        collection_id = kwargs["collection_id"]
        query = kwargs["query"]
        top_k = min(kwargs.get("top_k", 5), 10)
        user_id = kwargs.get("user_id", "default")

        try:
            results = await self._client.query_collection(
                collection_id=collection_id,
                query=query,
                user_id=user_id,
                top_k=top_k,
            )
        except Exception as e:
            return f"Honcho query failed: {e}"

        if not results:
            return f"No results found for '{query}' in collection '{collection_id}'."

        parts = [f"Honcho query results for '{query}' ({len(results)} matches):\n"]
        for i, r in enumerate(results, 1):
            score = f" (score: {r.score:.3f})" if r.score is not None else ""
            parts.append(f"{i}.{score} {r.content}")

        return "\n".join(parts)


class HonchoSessionTool(BaseTool):
    """Create or list Honcho sessions."""

    name = "honcho_session"
    description = (
        "Manage Honcho sessions. Create a new session or list existing ones. "
        "Sessions track conversation history and enable context retrieval."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "Action: 'create' or 'list'.",
                "enum": ["create", "list"],
            },
            "user_id": {
                "type": "string",
                "description": "User ID (default: 'default').",
            },
        },
        "required": ["action"],
    }

    def __init__(self, client: HonchoClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        action = kwargs["action"]
        user_id = kwargs.get("user_id", "default")

        if action == "create":
            try:
                session = await self._client.create_session(user_id=user_id)
            except Exception as e:
                return f"Failed to create Honcho session: {e}"

            return f"Honcho session created: {session.id} (user: {user_id})"

        if action == "list":
            try:
                sessions = await self._client.list_sessions(user_id=user_id)
            except Exception as e:
                return f"Failed to list Honcho sessions: {e}"

            if not sessions:
                return "No Honcho sessions found."

            parts = [f"Honcho sessions ({len(sessions)}):\n"]
            for s in sessions:
                created = f" (created: {s.created_at})" if s.created_at else ""
                parts.append(f"  - {s.id}{created}")

            return "\n".join(parts)

        return f"Unknown action: {action}. Use 'create' or 'list'."
