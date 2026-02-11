"""Token budget tracker - prevents runaway API costs."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()


class TokenBudget:
    """Tracks token usage and enforces budget limits.

    Prevents runaway costs from:
    - Agent loops consuming excessive tokens
    - Prompt injection causing repeated API calls
    - Sub-agents spawning unbounded work

    Optionally persists state to a JSON file so usage survives restarts.
    """

    def __init__(
        self,
        daily_limit: int = 500_000,
        monthly_limit: int = 10_000_000,
        per_run_limit: int = 50_000,
        persist_path: str | None = None,
    ) -> None:
        self.daily_limit = daily_limit
        self.monthly_limit = monthly_limit
        self.per_run_limit = per_run_limit
        self._persist_path = Path(persist_path) if persist_path else None

        self._daily_usage: int = 0
        self._monthly_usage: int = 0
        self._current_day: date = date.today()
        self._current_month: int = date.today().month
        self._killed: bool = False

        # Load persisted state if available
        self._load_state()

    def _load_state(self) -> None:
        """Load persisted budget state from file."""
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text(encoding="utf-8"))
            saved_day = date.fromisoformat(data.get("date", ""))
            saved_month = data.get("month", 0)
            today = date.today()

            # Only restore if still same day
            if saved_day == today:
                self._daily_usage = data.get("daily_usage", 0)
            # Only restore monthly if still same month
            if saved_month == today.month:
                self._monthly_usage = data.get("monthly_usage", 0)

            logger.info(
                "budget_state_loaded",
                daily_usage=self._daily_usage,
                monthly_usage=self._monthly_usage,
            )
        except Exception as e:
            logger.warning("budget_state_load_failed", error=str(e))

    def _save_state(self) -> None:
        """Persist budget state to file."""
        if not self._persist_path:
            return
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "daily_usage": self._daily_usage,
                "monthly_usage": self._monthly_usage,
                "date": str(self._current_day),
                "month": self._current_month,
            }
            self._persist_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("budget_state_save_failed", error=str(e))

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
        # Persist after every usage update
        self._save_state()

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
