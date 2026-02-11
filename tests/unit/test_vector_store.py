"""Tests for ChromaDB vector store."""

import pytest

from openclaw.memory.vector_store import CONVERSATIONS, HAS_CHROMADB, KNOWLEDGE, RESEARCH, VectorStore

pytestmark = pytest.mark.skipif(not HAS_CHROMADB, reason="chromadb not compatible with this Python version")


@pytest.fixture
def vector_store(tmp_path):
    return VectorStore(persist_dir=str(tmp_path / "chroma"))


class TestVectorStore:
    def test_add_and_query(self, vector_store: VectorStore) -> None:
        vector_store.add(KNOWLEDGE, "Python is a programming language", doc_id="k1")
        vector_store.add(KNOWLEDGE, "Rust is a systems language", doc_id="k2")
        vector_store.add(KNOWLEDGE, "Cooking pasta requires boiling water", doc_id="k3")

        results = vector_store.query(KNOWLEDGE, "programming languages")
        assert len(results) > 0
        # Programming-related docs should be more relevant than cooking
        docs = [r["document"] for r in results]
        assert any("Python" in d or "Rust" in d for d in docs)

    def test_count(self, vector_store: VectorStore) -> None:
        assert vector_store.count(KNOWLEDGE) == 0
        vector_store.add(KNOWLEDGE, "fact one", doc_id="k1")
        vector_store.add(KNOWLEDGE, "fact two", doc_id="k2")
        assert vector_store.count(KNOWLEDGE) == 2

    def test_delete(self, vector_store: VectorStore) -> None:
        vector_store.add(KNOWLEDGE, "to delete", doc_id="k1")
        assert vector_store.count(KNOWLEDGE) == 1
        vector_store.delete(KNOWLEDGE, ["k1"])
        assert vector_store.count(KNOWLEDGE) == 0

    def test_separate_collections(self, vector_store: VectorStore) -> None:
        vector_store.add(KNOWLEDGE, "knowledge item", doc_id="k1")
        vector_store.add(CONVERSATIONS, "conversation item", doc_id="c1")
        vector_store.add(RESEARCH, "research item", doc_id="r1")

        assert vector_store.count(KNOWLEDGE) == 1
        assert vector_store.count(CONVERSATIONS) == 1
        assert vector_store.count(RESEARCH) == 1

    def test_query_empty_collection(self, vector_store: VectorStore) -> None:
        results = vector_store.query(KNOWLEDGE, "anything")
        assert results == []

    def test_metadata(self, vector_store: VectorStore) -> None:
        vector_store.add(
            KNOWLEDGE,
            "User prefers dark mode",
            metadata={"category": "preference", "user_id": 123},
            doc_id="k1",
        )

        results = vector_store.query(KNOWLEDGE, "dark mode")
        assert len(results) == 1
        assert results[0]["metadata"]["category"] == "preference"
        assert results[0]["metadata"]["user_id"] == 123

    def test_query_with_where_filter(self, vector_store: VectorStore) -> None:
        vector_store.add(KNOWLEDGE, "fact about Python", metadata={"category": "fact"}, doc_id="k1")
        vector_store.add(KNOWLEDGE, "user likes tea", metadata={"category": "preference"}, doc_id="k2")

        results = vector_store.query(KNOWLEDGE, "Python", where={"category": "fact"})
        assert len(results) == 1
        assert "Python" in results[0]["document"]
