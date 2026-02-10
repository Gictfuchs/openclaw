"""Long-term memory: persistent storage + semantic search."""

from __future__ import annotations

import json
from typing import Any

import structlog
from sqlalchemy import select

from openclaw.db.engine import get_session
from openclaw.memory.models import ConversationMessage, KnowledgeEntry, ResearchRecord
from openclaw.memory.vector_store import CONVERSATIONS, KNOWLEDGE, RESEARCH, VectorStore

logger = structlog.get_logger()


class LongTermMemory:
    """Persistent memory combining SQLite (structured) and ChromaDB (semantic).

    SQLite stores the authoritative data.
    ChromaDB indexes it for semantic similarity search.
    """

    def __init__(self, vector_store: VectorStore) -> None:
        self._vectors = vector_store

    async def store_message(self, user_id: int, role: str, content: str) -> None:
        """Store a conversation message in both SQLite and ChromaDB."""
        async with get_session() as session:
            msg = ConversationMessage(user_id=user_id, role=role, content=content)
            session.add(msg)
            await session.commit()
            msg_id = msg.id

        # Index in ChromaDB for semantic retrieval
        self._vectors.add(
            collection=CONVERSATIONS,
            document=content,
            metadata={"user_id": user_id, "role": role},
            doc_id=f"msg_{msg_id}",
        )

    async def store_knowledge(
        self,
        category: str,
        key: str,
        value: str,
        source: str = "conversation",
        user_id: int | None = None,
    ) -> None:
        """Store a knowledge entry (fact, preference, entity)."""
        async with get_session() as session:
            # Upsert: update if same category+key exists
            stmt = select(KnowledgeEntry).where(
                KnowledgeEntry.category == category,
                KnowledgeEntry.key == key,
            )
            if user_id is not None:
                stmt = stmt.where(KnowledgeEntry.user_id == user_id)

            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.value = value
                existing.source = source
                entry_id = existing.id
            else:
                entry = KnowledgeEntry(
                    category=category,
                    key=key,
                    value=value,
                    source=source,
                    user_id=user_id,
                )
                session.add(entry)
                await session.flush()
                entry_id = entry.id

            await session.commit()

        # Index in ChromaDB
        self._vectors.add(
            collection=KNOWLEDGE,
            document=f"{key}: {value}",
            metadata={"category": category, "source": source, "user_id": user_id or 0},
            doc_id=f"know_{entry_id}",
        )

        logger.debug("knowledge_stored", category=category, key=key)

    async def store_research(
        self,
        query: str,
        summary: str,
        sources: list[str],
        user_id: int | None = None,
    ) -> None:
        """Store a research result."""
        async with get_session() as session:
            record = ResearchRecord(
                query=query,
                summary=summary,
                sources=json.dumps(sources),
                user_id=user_id,
            )
            session.add(record)
            await session.commit()
            record_id = record.id

        self._vectors.add(
            collection=RESEARCH,
            document=f"{query}\n{summary}",
            metadata={"user_id": user_id or 0},
            doc_id=f"research_{record_id}",
        )

    async def recall(self, query: str, n_results: int = 5) -> list[dict[str, Any]]:
        """Semantic search across all memory collections."""
        results: list[dict[str, Any]] = []

        for collection_name in [KNOWLEDGE, CONVERSATIONS, RESEARCH]:
            items = self._vectors.query(
                collection=collection_name,
                query_text=query,
                n_results=n_results,
            )
            for item in items:
                item["collection"] = collection_name
                results.append(item)

        # Sort by relevance (lower distance = more similar)
        results.sort(key=lambda x: x.get("distance", 1.0))
        return results[:n_results]

    async def recall_knowledge(
        self,
        query: str,
        category: str | None = None,
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Search specifically in knowledge entries."""
        where = {"category": category} if category else None
        return self._vectors.query(
            collection=KNOWLEDGE,
            query_text=query,
            n_results=n_results,
            where=where,
        )

    async def get_recent_messages(self, user_id: int, limit: int = 20) -> list[dict[str, str]]:
        """Get recent conversation messages from SQLite."""
        async with get_session() as session:
            stmt = (
                select(ConversationMessage)
                .where(ConversationMessage.user_id == user_id)
                .order_by(ConversationMessage.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            messages = result.scalars().all()

        # Reverse to chronological order
        return [{"role": m.role, "content": m.content} for m in reversed(messages)]

    def get_stats(self) -> dict[str, int]:
        """Get memory statistics."""
        return {
            "conversations": self._vectors.count(CONVERSATIONS),
            "knowledge": self._vectors.count(KNOWLEDGE),
            "research": self._vectors.count(RESEARCH),
        }
