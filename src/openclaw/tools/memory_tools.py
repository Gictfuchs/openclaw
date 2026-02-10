"""Memory tools for the agent to recall and store information."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from openclaw.tools.base import BaseTool

if TYPE_CHECKING:
    from openclaw.memory.long_term import LongTermMemory

logger = structlog.get_logger()


class RecallMemoryTool(BaseTool):
    """Search long-term memory for relevant information."""

    name = "recall_memory"
    description = (
        "Search your long-term memory for relevant information. "
        "Use this to remember past conversations, stored facts, user preferences, "
        "or previous research results. Semantic search - describe what you're looking for."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What to search for in memory (natural language).",
            },
            "category": {
                "type": "string",
                "description": "Optional: filter by category ('fact', 'preference', 'entity').",
                "enum": ["fact", "preference", "entity"],
            },
        },
        "required": ["query"],
    }

    def __init__(self, memory: LongTermMemory) -> None:
        self._memory = memory

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs["query"]
        category = kwargs.get("category")

        if category:
            results = await self._memory.recall_knowledge(query, category=category)
        else:
            results = await self._memory.recall(query)

        if not results:
            return "No relevant memories found."

        parts = [f"Memory search for: {query}\n"]
        for i, item in enumerate(results, 1):
            collection = item.get("collection", "unknown")
            distance = item.get("distance", 0)
            relevance = max(0, round((1 - distance) * 100))
            parts.append(f"{i}. [{collection}] (relevance: {relevance}%) {item['document'][:300]}")

        return "\n".join(parts)


class StoreMemoryTool(BaseTool):
    """Store important information in long-term memory."""

    name = "store_memory"
    description = (
        "Store an important fact, user preference, or entity in long-term memory. "
        "Use this when you learn something that should be remembered for future conversations. "
        "Examples: user preferences, important facts, learned information."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Category: 'fact' (learned info), 'preference' (user preference), 'entity' (person/place/thing).",
                "enum": ["fact", "preference", "entity"],
            },
            "key": {
                "type": "string",
                "description": "Short label/key for this memory (e.g. 'favorite_language', 'user_name').",
            },
            "value": {
                "type": "string",
                "description": "The information to remember.",
            },
        },
        "required": ["category", "key", "value"],
    }

    def __init__(self, memory: LongTermMemory) -> None:
        self._memory = memory

    async def execute(self, **kwargs: Any) -> str:
        category = kwargs["category"]
        key = kwargs["key"]
        value = kwargs["value"]

        try:
            await self._memory.store_knowledge(
                category=category,
                key=key,
                value=value,
                source="agent",
            )
        except Exception as e:
            return f"Error storing memory: {e}"

        return f"Stored [{category}] {key}: {value}"
