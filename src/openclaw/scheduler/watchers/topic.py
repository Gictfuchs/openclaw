"""Topic watcher - monitors topics via Brave Search for new articles."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from openclaw.scheduler.watchers.base import BaseWatcher

if TYPE_CHECKING:
    from openclaw.config import Settings
    from openclaw.integrations.brave import BraveSearchClient
    from openclaw.telegram.bot import FochsTelegramBot

logger = structlog.get_logger()


class TopicWatcher(BaseWatcher):
    """Monitor topics via Brave Search and notify on new results."""

    watcher_type = "topic"

    def __init__(
        self,
        brave: BraveSearchClient,
        telegram: FochsTelegramBot,
        settings: Settings,
    ) -> None:
        super().__init__(interval_seconds=3600, telegram=telegram, settings=settings)
        self.brave = brave

    async def check_and_notify(self) -> None:
        subscriptions = await self._get_subscriptions()
        if not subscriptions:
            return

        for sub in subscriptions:
            try:
                await self._check_topic(sub.id, sub.user_id, sub.target)
            except Exception as e:
                logger.error("topic_check_failed", target=sub.target, error=str(e))

    async def _check_topic(self, sub_id: int, user_id: int, query: str) -> None:
        response = await self.brave.search(query, count=5, freshness="pd")

        if not response.results:
            return

        known, _ = await self._get_state(sub_id)
        new_results = []
        all_known = set(known)

        for result in response.results:
            if result.url not in all_known:
                new_results.append(result)
                all_known.add(result.url)

        if new_results:
            lines = [f'*Neue Ergebnisse fuer "{query}":*\n']
            for r in new_results[:5]:
                lines.append(f"- [{r.title}]({r.url})")

            await self.send_notification(user_id, "\n".join(lines))
            await self._update_state(sub_id, list(all_known))
