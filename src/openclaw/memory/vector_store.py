"""ChromaDB vector store for semantic memory."""

from __future__ import annotations

from typing import Any

import chromadb
import structlog

logger = structlog.get_logger()

# Collection names
CONVERSATIONS = "conversations"
KNOWLEDGE = "knowledge"
RESEARCH = "research"


class VectorStore:
    """ChromaDB-backed vector store for semantic search across memory.

    Three collections:
    - conversations: past conversation messages for context retrieval
    - knowledge: learned facts, preferences, entities
    - research: stored research summaries and findings
    """

    def __init__(self, persist_dir: str) -> None:
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collections: dict[str, chromadb.Collection] = {}

        # Initialize collections
        for name in [CONVERSATIONS, KNOWLEDGE, RESEARCH]:
            self._collections[name] = self._client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )
        logger.info("vector_store_initialized", collections=list(self._collections.keys()))

    def add(
        self,
        collection: str,
        document: str,
        metadata: dict[str, Any] | None = None,
        doc_id: str | None = None,
    ) -> str:
        """Add a document to a collection. Returns the document ID."""
        coll = self._collections[collection]
        if doc_id is None:
            doc_id = f"{collection}_{coll.count()}"

        coll.add(
            documents=[document],
            metadatas=[metadata or {}],
            ids=[doc_id],
        )
        return doc_id

    def query(
        self,
        collection: str,
        query_text: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Query a collection for similar documents.

        Returns list of dicts with 'document', 'metadata', 'distance', 'id'.
        """
        coll = self._collections[collection]
        if coll.count() == 0:
            return []

        kwargs: dict[str, Any] = {
            "query_texts": [query_text],
            "n_results": min(n_results, coll.count()),
        }
        if where:
            kwargs["where"] = where

        results = coll.query(**kwargs)

        items = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                items.append(
                    {
                        "document": doc,
                        "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                        "distance": results["distances"][0][i] if results["distances"] else 0,
                        "id": results["ids"][0][i] if results["ids"] else "",
                    }
                )
        return items

    def count(self, collection: str) -> int:
        """Get the number of documents in a collection."""
        return self._collections[collection].count()

    def delete(self, collection: str, doc_ids: list[str]) -> None:
        """Delete documents by ID."""
        self._collections[collection].delete(ids=doc_ids)
