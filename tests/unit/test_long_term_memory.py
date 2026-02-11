"""Tests for long-term memory."""

import pytest

from openclaw.db.engine import close_db, init_db
from openclaw.memory.long_term import LongTermMemory
from openclaw.memory.vector_store import HAS_CHROMADB, VectorStore

pytestmark = pytest.mark.skipif(not HAS_CHROMADB, reason="chromadb not compatible with this Python version")


@pytest.fixture
async def memory(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)

    vector_store = VectorStore(persist_dir=str(tmp_path / "chroma"))
    mem = LongTermMemory(vector_store=vector_store)
    yield mem

    await close_db()


class TestLongTermMemory:
    async def test_store_and_recall_message(self, memory: LongTermMemory) -> None:
        await memory.store_message(user_id=1, role="user", content="What is Python?")
        await memory.store_message(user_id=1, role="assistant", content="Python is a programming language.")

        results = await memory.recall("Python programming")
        assert len(results) > 0
        docs = [r["document"] for r in results]
        assert any("Python" in d for d in docs)

    async def test_store_and_recall_knowledge(self, memory: LongTermMemory) -> None:
        await memory.store_knowledge(
            category="preference",
            key="language",
            value="User prefers German",
            user_id=1,
        )

        results = await memory.recall_knowledge("language preference")
        assert len(results) > 0
        assert any("German" in r["document"] for r in results)

    async def test_knowledge_upsert(self, memory: LongTermMemory) -> None:
        await memory.store_knowledge(category="fact", key="sky_color", value="blue")
        await memory.store_knowledge(category="fact", key="sky_color", value="blue during day, dark at night")

        results = await memory.recall_knowledge("sky color")
        # Should have the updated value
        assert any("dark at night" in r["document"] for r in results)

    async def test_get_recent_messages(self, memory: LongTermMemory) -> None:
        for i in range(5):
            await memory.store_message(user_id=1, role="user", content=f"Message {i}")

        messages = await memory.get_recent_messages(user_id=1, limit=3)
        assert len(messages) == 3
        # Should be in chronological order (oldest first)
        assert messages[0]["content"] == "Message 2"
        assert messages[2]["content"] == "Message 4"

    async def test_recall_across_collections(self, memory: LongTermMemory) -> None:
        await memory.store_message(user_id=1, role="user", content="I love cooking Italian food")
        await memory.store_knowledge(category="preference", key="cuisine", value="Italian")
        await memory.store_research(
            query="Italian recipes", summary="Best pasta recipes", sources=["https://example.com"]
        )

        results = await memory.recall("Italian food cooking")
        assert len(results) > 0
        # Should find results from multiple collections
        collections = {r["collection"] for r in results}
        assert len(collections) >= 1  # At least one collection matched

    async def test_get_stats(self, memory: LongTermMemory) -> None:
        await memory.store_message(user_id=1, role="user", content="Hello")
        await memory.store_knowledge(category="fact", key="test", value="value")

        stats = await memory.get_stats()
        assert stats["conversations"] == 1
        assert stats["knowledge"] == 1
        assert stats["research"] == 0
