"""Base watcher with asyncio loop, autonomy gate, and budget check."""

from __future__ import annotations

import asyncio
import contextlib
import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import func, select

from openclaw.db.engine import get_session
from openclaw.memory.models import ProactiveMessageLog, WatcherState, WatchSubscription

if TYPE_CHECKING:
    from openclaw.config import Settings
    from openclaw.telegram.bot import FochsTelegramBot

logger = structlog.get_logger()


class BaseWatcher(ABC):
    """Base class for all background watchers."""

    watcher_type: str = ""

    def __init__(
        self,
        interval_seconds: int,
        telegram: FochsTelegramBot,
        settings: Settings,
    ) -> None:
        self.interval = interval_seconds
        self.telegram = telegram
        self.settings = settings
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the watcher background task."""
        self._task = asyncio.create_task(self._run_loop())
        logger.info("watcher_started", watcher=self.watcher_type, interval=self.interval)

    async def stop(self) -> None:
        """Stop the watcher."""
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
            logger.info("watcher_stopped", watcher=self.watcher_type)

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def _run_loop(self) -> None:
        """Main loop: check, sleep, repeat."""
        # Small initial delay to let everything start up
        await asyncio.sleep(5)
        while True:
            try:
                await self.check_and_notify()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("watcher_error", watcher=self.watcher_type, error=str(e))
            await asyncio.sleep(self.interval)

    async def send_notification(self, user_id: int, message: str) -> bool:
        """Send a proactive notification respecting autonomy and budget.

        Returns True if the message was sent.
        """
        # Check autonomy level
        level = self.settings.autonomy_level
        if level == "manual":
            logger.debug("autonomy_blocked", user_id=user_id, level=level)
            return False

        # Check proactive message budget
        if not await self._check_budget(user_id):
            logger.warning("proactive_budget_exceeded", user_id=user_id)
            return False

        # Prepend prefix for "ask" mode
        if level == "ask":
            message = f"[Auto-Update]\n{message}"

        await self.telegram.send_proactive_message(user_id, message)
        await self._log_message(user_id)
        return True

    async def _check_budget(self, user_id: int) -> bool:
        """Check if user hasn't exceeded daily proactive message limit."""
        today = datetime.now(UTC).date()
        async with get_session() as session:
            result = await session.execute(
                select(func.count(ProactiveMessageLog.id)).where(
                    ProactiveMessageLog.user_id == user_id,
                    func.date(ProactiveMessageLog.sent_at) == today,
                )
            )
            count = result.scalar() or 0
        return count < self.settings.proactive_message_limit

    async def _log_message(self, user_id: int) -> None:
        """Log a sent proactive message."""
        async with get_session() as session:
            session.add(ProactiveMessageLog(user_id=user_id))
            await session.commit()

    async def _get_subscriptions(self) -> list[WatchSubscription]:
        """Get all active subscriptions for this watcher type."""
        async with get_session() as session:
            result = await session.execute(
                select(WatchSubscription).where(
                    WatchSubscription.watcher_type == self.watcher_type,
                    WatchSubscription.active.is_(True),
                )
            )
            return list(result.scalars().all())

    async def _get_state(self, subscription_id: int) -> tuple[list[str], WatcherState | None]:
        """Get known items for a subscription. Returns (known_items, state_row)."""
        async with get_session() as session:
            result = await session.execute(select(WatcherState).where(WatcherState.subscription_id == subscription_id))
            state = result.scalar_one_or_none()
            if state:
                known: list[str] = json.loads(state.known_items) if state.known_items else []
                return known, state
            return [], None

    async def _update_state(self, subscription_id: int, known_items: list[str]) -> None:
        """Update the known items for a subscription."""
        # Keep only the latest 500 items to prevent unbounded growth
        known_items = known_items[-500:]
        async with get_session() as session:
            result = await session.execute(select(WatcherState).where(WatcherState.subscription_id == subscription_id))
            state = result.scalar_one_or_none()
            if state:
                state.known_items = json.dumps(known_items)
                state.last_check = datetime.now(UTC)
            else:
                session.add(
                    WatcherState(
                        subscription_id=subscription_id,
                        known_items=json.dumps(known_items),
                    )
                )
            await session.commit()

    @abstractmethod
    async def check_and_notify(self) -> None:
        """Check for updates and send notifications."""
        ...

    def get_status(self) -> dict[str, Any]:
        """Get watcher status."""
        return {
            "type": self.watcher_type,
            "running": self.is_running,
            "interval": self.interval,
        }
