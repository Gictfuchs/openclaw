"""Short-term memory: conversation buffer with token window."""

from __future__ import annotations

from typing import Any


class ShortTermMemory:
    """In-memory conversation buffer per user.

    Keeps the most recent messages within a token budget.
    Used as the immediate context for the agent loop.
    """

    def __init__(self, max_messages: int = 50) -> None:
        self._buffers: dict[int, list[dict[str, Any]]] = {}
        self._max_messages = max_messages

    def get_history(self, user_id: int) -> list[dict[str, Any]]:
        """Get conversation history for a user."""
        return list(self._buffers.get(user_id, []))

    def add_message(self, user_id: int, role: str, content: str) -> None:
        """Add a message to the conversation buffer."""
        if user_id not in self._buffers:
            self._buffers[user_id] = []

        self._buffers[user_id].append({"role": role, "content": content})

        # Trim to max_messages
        if len(self._buffers[user_id]) > self._max_messages:
            self._buffers[user_id] = self._buffers[user_id][-self._max_messages :]

    def clear(self, user_id: int) -> None:
        """Clear conversation history for a user."""
        self._buffers.pop(user_id, None)

    def get_all_user_ids(self) -> list[int]:
        """Get all user IDs with active conversations."""
        return list(self._buffers.keys())

    @property
    def active_conversations(self) -> int:
        return len(self._buffers)
