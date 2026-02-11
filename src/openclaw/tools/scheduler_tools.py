"""Tools for managing watch subscriptions."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import select

from openclaw.db.engine import get_session
from openclaw.memory.models import WatcherState, WatchSubscription
from openclaw.tools.base import BaseTool

logger = structlog.get_logger()

_VALID_TYPES = {"topic", "github", "rss", "email"}


class WatchTool(BaseTool):
    """Subscribe to proactive notifications."""

    name = "watch"
    description = (
        "Subscribe to proactive notifications about a topic, GitHub repo, RSS feed, or email inbox. "
        "Types: topic (web search), github (repo issues/PRs), rss (feed articles), email (inbox)."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "What to watch: search query, 'owner/repo', feed URL, or 'inbox'",
            },
            "watcher_type": {
                "type": "string",
                "enum": ["topic", "github", "rss", "email"],
                "description": "Type of watcher",
            },
        },
        "required": ["target", "watcher_type"],
    }

    def __init__(self, user_id: int | None = None) -> None:
        self._user_id = user_id

    async def execute(self, **kwargs: Any) -> str:
        target = kwargs["target"]
        watcher_type = kwargs["watcher_type"]

        if watcher_type not in _VALID_TYPES:
            return f"Ungueltiger Typ: {watcher_type}. Erlaubt: {', '.join(sorted(_VALID_TYPES))}"

        try:
            async with get_session() as session:
                sub = WatchSubscription(
                    user_id=self._user_id or 0,
                    watcher_type=watcher_type,
                    target=target,
                )
                session.add(sub)
                await session.flush()
                sub_id = sub.id

                # Create initial watcher state
                session.add(WatcherState(subscription_id=sub_id))
                await session.commit()

            return f"Watch erstellt (#{sub_id}): [{watcher_type}] {target}"
        except Exception as e:
            return f"Fehler beim Erstellen: {e}"


class UnwatchTool(BaseTool):
    """Unsubscribe from notifications."""

    name = "unwatch"
    description = "Cancel a watch subscription by ID."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "subscription_id": {
                "type": "integer",
                "description": "ID of the watch subscription to cancel",
            },
        },
        "required": ["subscription_id"],
    }

    async def execute(self, **kwargs: Any) -> str:
        sub_id = kwargs["subscription_id"]

        try:
            async with get_session() as session:
                result = await session.execute(select(WatchSubscription).where(WatchSubscription.id == sub_id))
                sub = result.scalar_one_or_none()
                if not sub:
                    return f"Watch #{sub_id} nicht gefunden."
                if not sub.active:
                    return f"Watch #{sub_id} ist bereits deaktiviert."
                sub.active = False
                await session.commit()

            return f"Watch #{sub_id} deaktiviert: [{sub.watcher_type}] {sub.target}"
        except Exception as e:
            return f"Fehler: {e}"


class ListWatchesTool(BaseTool):
    """List all active watch subscriptions."""

    name = "list_watches"
    description = "List all active watch subscriptions."
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, **kwargs: Any) -> str:
        try:
            async with get_session() as session:
                result = await session.execute(select(WatchSubscription).where(WatchSubscription.active.is_(True)))
                subs = list(result.scalars().all())

            if not subs:
                return "Keine aktiven Watches."

            lines = ["*Aktive Watches:*\n"]
            for sub in subs:
                lines.append(f"#{sub.id} [{sub.watcher_type}] {sub.target} (User {sub.user_id})")

            return "\n".join(lines)
        except Exception as e:
            return f"Fehler: {e}"
