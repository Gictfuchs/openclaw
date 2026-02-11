"""GitHub watcher - monitors repos for new issues and PRs."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from openclaw.scheduler.watchers.base import BaseWatcher

if TYPE_CHECKING:
    from openclaw.config import Settings
    from openclaw.integrations.github import GitHubClient
    from openclaw.telegram.bot import FochsTelegramBot

logger = structlog.get_logger()


class GitHubWatcher(BaseWatcher):
    """Monitor GitHub repos for new issues and PRs."""

    watcher_type = "github"

    def __init__(
        self,
        github: GitHubClient,
        telegram: FochsTelegramBot,
        settings: Settings,
    ) -> None:
        super().__init__(interval_seconds=1800, telegram=telegram, settings=settings)
        self.github = github

    async def check_and_notify(self) -> None:
        subscriptions = await self._get_subscriptions()
        if not subscriptions:
            return

        for sub in subscriptions:
            try:
                await self._check_repo(sub.id, sub.user_id, sub.target)
            except Exception as e:
                logger.error("github_check_failed", target=sub.target, error=str(e))

    async def _check_repo(self, sub_id: int, user_id: int, repo: str) -> None:
        loop = asyncio.get_running_loop()
        issues = await loop.run_in_executor(
            None,
            lambda: self.github.list_issues(repo, state="open", limit=10),
        )

        if not issues:
            return

        known, _ = await self._get_state(sub_id)
        known_numbers = {str(n) for n in known}
        new_issues = []

        for issue in issues:
            if str(issue.number) not in known_numbers:
                new_issues.append(issue)
                known_numbers.add(str(issue.number))

        if new_issues:
            lines = [f"*Neues in {repo}:*\n"]
            for issue in new_issues[:5]:
                kind = "PR" if issue.is_pr else "Issue"
                labels = f" [{', '.join(issue.labels)}]" if issue.labels else ""
                lines.append(f"- {kind} #{issue.number}: {issue.title}{labels}")

            await self.send_notification(user_id, "\n".join(lines))
            await self._update_state(sub_id, list(known_numbers))
