"""Long-term memory: persistent storage + semantic search.

When ChromaDB is unavailable (Python 3.14 compat), recall falls back to
SQLite LIKE-based text search.  Less precise than semantic search but
keeps the memory system fully functional.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from sqlalchemy import func, select

from openclaw.db.engine import get_session
from openclaw.memory.models import ConversationMessage, KnowledgeEntry, ResearchRecord
from openclaw.memory.vector_store import CONVERSATIONS, KNOWLEDGE, RESEARCH, VectorStore

logger = structlog.get_logger()


class LongTermMemory:
    """Persistent memory combining SQLite (structured) and ChromaDB (semantic).

    SQLite stores the authoritative data.
    ChromaDB indexes it for semantic similarity search.

    When ChromaDB is unavailable, recall methods fall back to SQLite
    LIKE-based text search so the agent still has a working memory.
    """

    def __init__(self, vector_store: VectorStore) -> None:
        self._vectors = vector_store
        self._use_vectors = vector_store._available

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

    # ------------------------------------------------------------------
    # Recall: ChromaDB semantic search with SQLite LIKE fallback
    # ------------------------------------------------------------------

    async def recall(self, query: str, n_results: int = 5) -> list[dict[str, Any]]:
        """Search across all memory collections.

        Uses ChromaDB semantic search when available, otherwise falls back
        to SQLite LIKE-based text search.
        """
        if self._use_vectors:
            return await self._recall_vector(query, n_results)
        return await self._recall_sqlite(query, n_results)

    async def _recall_vector(self, query: str, n_results: int) -> list[dict[str, Any]]:
        """Semantic search via ChromaDB."""
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

        results.sort(key=lambda x: x.get("distance", 1.0))
        return results[:n_results]

    async def _recall_sqlite(self, query: str, n_results: int) -> list[dict[str, Any]]:
        """Fallback: LIKE-based text search across SQLite tables."""
        results: list[dict[str, Any]] = []
        pattern = f"%{query}%"

        async with get_session() as session:
            # Search knowledge entries (key + value)
            stmt = (
                select(KnowledgeEntry)
                .where(
                    (KnowledgeEntry.key.ilike(pattern)) | (KnowledgeEntry.value.ilike(pattern)),
                )
                .order_by(KnowledgeEntry.updated_at.desc())
                .limit(n_results)
            )
            result = await session.execute(stmt)
            for entry in result.scalars().all():
                results.append(
                    {
                        "document": f"{entry.key}: {entry.value}",
                        "collection": KNOWLEDGE,
                        "metadata": {"category": entry.category, "source": entry.source},
                        "distance": 0.5,
                        "id": f"know_{entry.id}",
                    }
                )

            # Search conversations
            stmt = (
                select(ConversationMessage)
                .where(ConversationMessage.content.ilike(pattern))
                .order_by(ConversationMessage.created_at.desc())
                .limit(n_results)
            )
            result = await session.execute(stmt)
            for msg in result.scalars().all():
                results.append(
                    {
                        "document": msg.content,
                        "collection": CONVERSATIONS,
                        "metadata": {"user_id": msg.user_id, "role": msg.role},
                        "distance": 0.5,
                        "id": f"msg_{msg.id}",
                    }
                )

            # Search research records
            stmt = (
                select(ResearchRecord)
                .where(
                    (ResearchRecord.query.ilike(pattern)) | (ResearchRecord.summary.ilike(pattern)),
                )
                .order_by(ResearchRecord.created_at.desc())
                .limit(n_results)
            )
            result = await session.execute(stmt)
            for rec in result.scalars().all():
                results.append(
                    {
                        "document": f"{rec.query}\n{rec.summary}",
                        "collection": RESEARCH,
                        "metadata": {"user_id": rec.user_id or 0},
                        "distance": 0.5,
                        "id": f"research_{rec.id}",
                    }
                )

        return results[:n_results]

    async def recall_knowledge(
        self,
        query: str,
        category: str | None = None,
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        """Search specifically in knowledge entries."""
        if self._use_vectors:
            where = {"category": category} if category else None
            return self._vectors.query(
                collection=KNOWLEDGE,
                query_text=query,
                n_results=n_results,
                where=where,
            )

        # SQLite fallback
        pattern = f"%{query}%"
        async with get_session() as session:
            stmt = select(KnowledgeEntry).where(
                (KnowledgeEntry.key.ilike(pattern)) | (KnowledgeEntry.value.ilike(pattern)),
            )
            if category:
                stmt = stmt.where(KnowledgeEntry.category == category)
            stmt = stmt.order_by(KnowledgeEntry.updated_at.desc()).limit(n_results)

            result = await session.execute(stmt)
            return [
                {
                    "document": f"{e.key}: {e.value}",
                    "collection": KNOWLEDGE,
                    "metadata": {"category": e.category, "source": e.source},
                    "distance": 0.5,
                    "id": f"know_{e.id}",
                }
                for e in result.scalars().all()
            ]

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

    async def get_stats(self) -> dict[str, int]:
        """Get memory statistics from SQLite (always accurate)."""
        async with get_session() as session:
            conv_count = (await session.execute(select(func.count(ConversationMessage.id)))).scalar() or 0
            know_count = (await session.execute(select(func.count(KnowledgeEntry.id)))).scalar() or 0
            research_count = (await session.execute(select(func.count(ResearchRecord.id)))).scalar() or 0
        return {
            "conversations": conv_count,
            "knowledge": know_count,
            "research": research_count,
        }
