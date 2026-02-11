"""Tests for memory tools.

These tests use mocked LongTermMemory and do NOT require a working ChromaDB.
"""

from unittest.mock import AsyncMock

import pytest

from openclaw.memory.long_term import LongTermMemory
from openclaw.tools.memory_tools import RecallMemoryTool, StoreMemoryTool


@pytest.fixture
def mock_memory():
    return AsyncMock(spec=LongTermMemory)


class TestRecallMemoryTool:
    async def test_recall_returns_results(self, mock_memory: AsyncMock) -> None:
        mock_memory.recall.return_value = [
            {"document": "User likes Python", "collection": "knowledge", "distance": 0.2, "id": "k1", "metadata": {}},
            {
                "document": "Previous chat about coding",
                "collection": "conversations",
                "distance": 0.4,
                "id": "c1",
                "metadata": {},
            },
        ]

        tool = RecallMemoryTool(memory=mock_memory)
        result = await tool.execute(query="Python programming")

        assert "User likes Python" in result
        assert "knowledge" in result
        assert "80%" in result  # 1 - 0.2 = 0.8 = 80%

    async def test_recall_with_category(self, mock_memory: AsyncMock) -> None:
        mock_memory.recall_knowledge.return_value = [
            {"document": "dark mode: enabled", "collection": "knowledge", "distance": 0.1, "id": "k1", "metadata": {}},
        ]

        tool = RecallMemoryTool(memory=mock_memory)
        result = await tool.execute(query="display settings", category="preference")

        mock_memory.recall_knowledge.assert_called_once_with("display settings", category="preference")
        assert "dark mode" in result

    async def test_recall_empty(self, mock_memory: AsyncMock) -> None:
        mock_memory.recall.return_value = []

        tool = RecallMemoryTool(memory=mock_memory)
        result = await tool.execute(query="nonexistent")

        assert "No relevant memories" in result

    def test_tool_definition(self, mock_memory: AsyncMock) -> None:
        tool = RecallMemoryTool(memory=mock_memory)
        defn = tool.to_definition()
        assert defn["name"] == "recall_memory"
        assert "query" in defn["input_schema"]["required"]


class TestStoreMemoryTool:
    async def test_store_success(self, mock_memory: AsyncMock) -> None:
        tool = StoreMemoryTool(memory=mock_memory)
        result = await tool.execute(category="preference", key="theme", value="dark mode")

        mock_memory.store_knowledge.assert_called_once_with(
            category="preference",
            key="theme",
            value="dark mode",
            source="agent",
        )
        assert "Stored" in result
        assert "preference" in result
        assert "theme" in result

    async def test_store_error(self, mock_memory: AsyncMock) -> None:
        mock_memory.store_knowledge.side_effect = Exception("DB error")

        tool = StoreMemoryTool(memory=mock_memory)
        result = await tool.execute(category="fact", key="test", value="value")

        assert "Error" in result

    def test_tool_definition(self, mock_memory: AsyncMock) -> None:
        tool = StoreMemoryTool(memory=mock_memory)
        defn = tool.to_definition()
        assert defn["name"] == "store_memory"
        assert "category" in defn["input_schema"]["required"]
        assert "key" in defn["input_schema"]["required"]
        assert "value" in defn["input_schema"]["required"]
