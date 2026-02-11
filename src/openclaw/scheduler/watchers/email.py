"""Email watcher - monitors inbox for new unread emails."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from openclaw.scheduler.watchers.base import BaseWatcher

if TYPE_CHECKING:
    from openclaw.config import Settings
    from openclaw.integrations.email import EmailClient
    from openclaw.telegram.bot import FochsTelegramBot

logger = structlog.get_logger()


class EmailWatcher(BaseWatcher):
    """Monitor email inbox for new unread messages."""

    watcher_type = "email"

    def __init__(
        self,
        email_client: EmailClient,
        telegram: FochsTelegramBot,
        settings: Settings,
    ) -> None:
        super().__init__(interval_seconds=600, telegram=telegram, settings=settings)
        self.email_client = email_client

    async def check_and_notify(self) -> None:
        subscriptions = await self._get_subscriptions()
        if not subscriptions:
            return

        for sub in subscriptions:
            try:
                await self._check_inbox(sub.id, sub.user_id)
            except Exception as e:
                logger.error("email_check_failed", error=str(e))

    async def _check_inbox(self, sub_id: int, user_id: int) -> None:
        emails = await self.email_client.fetch_emails(folder="INBOX", limit=10)

        if not emails:
            return

        # Filter to unread only
        unread = [e for e in emails if not e.is_read]
        if not unread:
            return

        known, _ = await self._get_state(sub_id)
        known_ids = set(known)
        new_emails = []

        for mail in unread:
            mail_id = f"{mail.sender}:{mail.subject}:{mail.date}"
            if mail_id not in known_ids:
                new_emails.append(mail)
                known_ids.add(mail_id)

        if new_emails:
            lines = [f"*{len(new_emails)} neue E-Mail(s):*\n"]
            for mail in new_emails[:5]:
                lines.append(f"- Von: {mail.sender} - {mail.subject}")

            await self.send_notification(user_id, "\n".join(lines))
            await self._update_state(sub_id, list(known_ids))
