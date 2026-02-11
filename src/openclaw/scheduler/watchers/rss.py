"""RSS watcher - monitors feeds for new articles."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from openclaw.scheduler.watchers.base import BaseWatcher

if TYPE_CHECKING:
    from openclaw.config import Settings
    from openclaw.integrations.rss import RSSClient
    from openclaw.telegram.bot import FochsTelegramBot

logger = structlog.get_logger()


class RSSWatcher(BaseWatcher):
    """Monitor RSS feeds for new articles."""

    watcher_type = "rss"

    def __init__(
        self,
        rss: RSSClient,
        telegram: FochsTelegramBot,
        settings: Settings,
    ) -> None:
        super().__init__(interval_seconds=1800, telegram=telegram, settings=settings)
        self.rss = rss

    async def check_and_notify(self) -> None:
        subscriptions = await self._get_subscriptions()
        if not subscriptions:
            return

        for sub in subscriptions:
            try:
                await self._check_feed(sub.id, sub.user_id, sub.target)
            except Exception as e:
                logger.error("rss_check_failed", target=sub.target, error=str(e))

    async def _check_feed(self, sub_id: int, user_id: int, url: str) -> None:
        result = await self.rss.fetch_feed(url, limit=10)

        if not result.entries:
            return

        known, _ = await self._get_state(sub_id)
        known_urls = set(known)
        new_entries = []

        for entry in result.entries:
            if entry.url and entry.url not in known_urls:
                new_entries.append(entry)
                known_urls.add(entry.url)

        if new_entries:
            lines = [f"*Neue Artikel in {result.title}:*\n"]
            for entry in new_entries[:5]:
                lines.append(f"- [{entry.title}]({entry.url})")

            await self.send_notification(user_id, "\n".join(lines))
            await self._update_state(sub_id, list(known_urls))
