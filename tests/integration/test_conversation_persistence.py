"""Integration tests for conversation history persistence."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from openclaw.core.agent import FochsAgent


class TestConversationPersistence:
    def _make_agent(
        self,
        memory: object | None = None,
    ) -> FochsAgent:
        llm = MagicMock()
        tools = MagicMock()
        tools.get_definitions.return_value = []
        return FochsAgent(llm=llm, tools=tools, memory=memory)

    @pytest.mark.asyncio
    async def test_ensure_history_loaded_no_memory(self) -> None:
        """Without memory, history starts empty."""
        agent = self._make_agent()
        history = await agent._ensure_history_loaded(user_id=42)
        assert history == []

    @pytest.mark.asyncio
    async def test_ensure_history_loaded_from_memory(self) -> None:
        """With memory, history is loaded from DB on first access."""
        memory = MagicMock()
        memory.get_recent_messages = AsyncMock(
            return_value=[
                {"role": "user", "content": "Hallo"},
                {"role": "assistant", "content": "Hi!"},
            ]
        )

        agent = self._make_agent(memory=memory)
        history = await agent._ensure_history_loaded(user_id=42)
        assert len(history) == 2
        assert history[0]["content"] == "Hallo"
        memory.get_recent_messages.assert_awaited_once_with(42, limit=50)

    @pytest.mark.asyncio
    async def test_ensure_history_cached(self) -> None:
        """Second call should use cached history, not reload from DB."""
        memory = MagicMock()
        memory.get_recent_messages = AsyncMock(return_value=[{"role": "user", "content": "Hi"}])

        agent = self._make_agent(memory=memory)

        # First call loads from DB
        await agent._ensure_history_loaded(user_id=42)
        # Second call should use cache
        await agent._ensure_history_loaded(user_id=42)

        # Should only be called once
        assert memory.get_recent_messages.await_count == 1

    @pytest.mark.asyncio
    async def test_ensure_history_memory_error_handled(self) -> None:
        """If memory fails, history starts empty without crashing."""
        memory = MagicMock()
        memory.get_recent_messages = AsyncMock(side_effect=RuntimeError("DB down"))

        agent = self._make_agent(memory=memory)
        history = await agent._ensure_history_loaded(user_id=42)
        assert history == []
