"""Scheduler manager - coordinates all background watchers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from openclaw.scheduler.watchers.email import EmailWatcher
from openclaw.scheduler.watchers.github import GitHubWatcher
from openclaw.scheduler.watchers.rss import RSSWatcher
from openclaw.scheduler.watchers.topic import TopicWatcher

if TYPE_CHECKING:
    from openclaw.config import Settings
    from openclaw.integrations.brave import BraveSearchClient
    from openclaw.integrations.email import EmailClient
    from openclaw.integrations.github import GitHubClient
    from openclaw.integrations.rss import RSSClient
    from openclaw.scheduler.watchers.base import BaseWatcher
    from openclaw.telegram.bot import FochsTelegramBot

logger = structlog.get_logger()


class SchedulerManager:
    """Manages all background watchers."""

    def __init__(
        self,
        telegram: FochsTelegramBot,
        settings: Settings,
        brave: BraveSearchClient | None = None,
        github: GitHubClient | None = None,
        rss: RSSClient | None = None,
        email: EmailClient | None = None,
    ) -> None:
        self.watchers: list[BaseWatcher] = []

        if brave:
            self.watchers.append(TopicWatcher(brave=brave, telegram=telegram, settings=settings))
        if github:
            self.watchers.append(GitHubWatcher(github=github, telegram=telegram, settings=settings))
        if rss:
            self.watchers.append(RSSWatcher(rss=rss, telegram=telegram, settings=settings))
        if email:
            self.watchers.append(EmailWatcher(email_client=email, telegram=telegram, settings=settings))

        logger.info("scheduler_initialized", watchers=[w.watcher_type for w in self.watchers])

    async def start(self) -> None:
        """Start all watchers."""
        for watcher in self.watchers:
            await watcher.start()
        logger.info("scheduler_started", count=len(self.watchers))

    async def stop(self) -> None:
        """Stop all watchers."""
        for watcher in self.watchers:
            await watcher.stop()
        logger.info("scheduler_stopped")

    def get_status(self) -> dict[str, Any]:
        """Get scheduler status."""
        return {
            "watchers": [w.get_status() for w in self.watchers],
            "active": sum(1 for w in self.watchers if w.is_running),
            "total": len(self.watchers),
        }
