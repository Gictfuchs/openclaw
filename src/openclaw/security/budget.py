"""Token budget tracker - prevents runaway API costs."""

from datetime import date, datetime
from typing import Any

import structlog

logger = structlog.get_logger()


class TokenBudget:
    """Tracks token usage and enforces budget limits.

    Prevents runaway costs from:
    - Agent loops consuming excessive tokens
    - Prompt injection causing repeated API calls
    - Sub-agents spawning unbounded work
    """

    def __init__(
        self,
        daily_limit: int = 500_000,
        monthly_limit: int = 10_000_000,
        per_run_limit: int = 50_000,
    ) -> None:
        self.daily_limit = daily_limit
        self.monthly_limit = monthly_limit
        self.per_run_limit = per_run_limit

        self._daily_usage: int = 0
        self._monthly_usage: int = 0
        self._current_day: date = date.today()
        self._current_month: int = date.today().month
        self._killed: bool = False

    def _rotate_if_needed(self) -> None:
        """Reset counters on day/month boundaries."""
        today = date.today()
        if today != self._current_day:
            logger.info("budget_daily_reset", previous_usage=self._daily_usage)
            self._daily_usage = 0
            self._current_day = today
        if today.month != self._current_month:
            logger.info("budget_monthly_reset", previous_usage=self._monthly_usage)
            self._monthly_usage = 0
            self._current_month = today.month
            self._killed = False  # Reset kill switch on new month

    def check_budget(self, estimated_tokens: int = 0) -> bool:
        """Check if we can afford the estimated token cost. Returns True if OK."""
        if self._killed:
            return False
        self._rotate_if_needed()
        if self._daily_usage + estimated_tokens > self.daily_limit:
            logger.warning("budget_daily_exceeded", usage=self._daily_usage, limit=self.daily_limit)
            return False
        if self._monthly_usage + estimated_tokens > self.monthly_limit:
            logger.warning("budget_monthly_exceeded", usage=self._monthly_usage, limit=self.monthly_limit)
            return False
        return True

    def check_run_budget(self, run_tokens: int) -> bool:
        """Check if a single run has exceeded its token limit."""
        return run_tokens <= self.per_run_limit

    def record_usage(self, tokens: int, provider: str = "") -> None:
        """Record token usage after an API call."""
        self._rotate_if_needed()
        self._daily_usage += tokens
        self._monthly_usage += tokens
        if self._daily_usage > self.daily_limit:
            logger.error("budget_kill_switch", reason="daily_limit", usage=self._daily_usage)
            self._killed = True
        if self._monthly_usage > self.monthly_limit:
            logger.error("budget_kill_switch", reason="monthly_limit", usage=self._monthly_usage)
            self._killed = True

    def kill(self) -> None:
        """Emergency kill switch - stop all API calls."""
        self._killed = True
        logger.error("budget_manual_kill", msg="All API calls disabled")

    def resume(self) -> None:
        """Resume after manual kill."""
        self._killed = False
        logger.info("budget_resumed")

    def get_status(self) -> dict[str, Any]:
        """Get current budget status."""
        self._rotate_if_needed()
        return {
            "daily_usage": self._daily_usage,
            "daily_limit": self.daily_limit,
            "daily_remaining": max(0, self.daily_limit - self._daily_usage),
            "monthly_usage": self._monthly_usage,
            "monthly_limit": self.monthly_limit,
            "monthly_remaining": max(0, self.monthly_limit - self._monthly_usage),
            "killed": self._killed,
            "date": str(self._current_day),
        }
