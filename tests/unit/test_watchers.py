"""Tests for scheduler watchers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from openclaw.scheduler.manager import SchedulerManager
from openclaw.scheduler.watchers.base import BaseWatcher
from openclaw.scheduler.watchers.email import EmailWatcher
from openclaw.scheduler.watchers.github import GitHubWatcher
from openclaw.scheduler.watchers.rss import RSSWatcher
from openclaw.scheduler.watchers.topic import TopicWatcher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(**overrides):
    """Create a minimal settings-like object."""
    defaults = {
        "autonomy_level": "full",
        "proactive_message_limit": 20,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_telegram():
    """Create a mock Telegram bot."""
    tg = AsyncMock()
    tg.send_proactive_message = AsyncMock()
    return tg


def _make_subscription(id_=1, user_id=42, watcher_type="topic", target="AI news", active=True):
    return SimpleNamespace(
        id=id_,
        user_id=user_id,
        watcher_type=watcher_type,
        target=target,
        active=active,
    )


# ---------------------------------------------------------------------------
# BaseWatcher (tested via a concrete subclass)
# ---------------------------------------------------------------------------


class DummyWatcher(BaseWatcher):
    watcher_type = "dummy"

    def __init__(self, telegram, settings):
        super().__init__(interval_seconds=60, telegram=telegram, settings=settings)
        self.check_called = 0

    async def check_and_notify(self) -> None:
        self.check_called += 1


class TestBaseWatcher:
    async def test_start_creates_task(self) -> None:
        watcher = DummyWatcher(telegram=_make_telegram(), settings=_make_settings())
        await watcher.start()
        assert watcher.is_running
        await watcher.stop()

    async def test_stop_cancels_task(self) -> None:
        watcher = DummyWatcher(telegram=_make_telegram(), settings=_make_settings())
        await watcher.start()
        await watcher.stop()
        assert not watcher.is_running

    async def test_get_status(self) -> None:
        watcher = DummyWatcher(telegram=_make_telegram(), settings=_make_settings())
        status = watcher.get_status()
        assert status["type"] == "dummy"
        assert status["running"] is False
        assert status["interval"] == 60

    async def test_send_notification_blocked_in_manual_mode(self) -> None:
        tg = _make_telegram()
        watcher = DummyWatcher(telegram=tg, settings=_make_settings(autonomy_level="manual"))
        result = await watcher.send_notification(42, "hello")
        assert result is False
        tg.send_proactive_message.assert_not_called()

    async def test_send_notification_adds_prefix_in_ask_mode(self) -> None:
        tg = _make_telegram()
        watcher = DummyWatcher(telegram=tg, settings=_make_settings(autonomy_level="ask"))
        # Patch budget check to always pass
        with (
            patch.object(watcher, "_check_budget", return_value=True),
            patch.object(watcher, "_log_message", new_callable=AsyncMock),
        ):
            result = await watcher.send_notification(42, "test msg")
        assert result is True
        sent_msg = tg.send_proactive_message.call_args[0][1]
        assert sent_msg.startswith("[Auto-Update]")

    async def test_send_notification_full_mode(self) -> None:
        tg = _make_telegram()
        watcher = DummyWatcher(telegram=tg, settings=_make_settings(autonomy_level="full"))
        with (
            patch.object(watcher, "_check_budget", return_value=True),
            patch.object(watcher, "_log_message", new_callable=AsyncMock),
        ):
            result = await watcher.send_notification(42, "hello")
        assert result is True
        tg.send_proactive_message.assert_called_once_with(42, "hello")

    async def test_send_notification_budget_exceeded(self) -> None:
        tg = _make_telegram()
        watcher = DummyWatcher(telegram=tg, settings=_make_settings(autonomy_level="full"))
        with patch.object(watcher, "_check_budget", return_value=False):
            result = await watcher.send_notification(42, "hello")
        assert result is False
        tg.send_proactive_message.assert_not_called()


# ---------------------------------------------------------------------------
# TopicWatcher
# ---------------------------------------------------------------------------


class TestTopicWatcher:
    async def test_check_and_notify_no_subs(self) -> None:
        brave = AsyncMock()
        watcher = TopicWatcher(brave=brave, telegram=_make_telegram(), settings=_make_settings())
        with patch.object(watcher, "_get_subscriptions", return_value=[]):
            await watcher.check_and_notify()
        brave.search.assert_not_called()

    async def test_check_and_notify_with_new_results(self) -> None:
        brave = AsyncMock()
        result1 = SimpleNamespace(url="https://a.com", title="Article A")
        result2 = SimpleNamespace(url="https://b.com", title="Article B")
        brave.search.return_value = SimpleNamespace(results=[result1, result2])

        tg = _make_telegram()
        watcher = TopicWatcher(brave=brave, telegram=tg, settings=_make_settings())

        sub = _make_subscription(watcher_type="topic", target="AI news")

        with (
            patch.object(watcher, "_get_subscriptions", return_value=[sub]),
            patch.object(watcher, "_get_state", return_value=([], None)),
            patch.object(watcher, "_update_state", new_callable=AsyncMock) as mock_update,
            patch.object(watcher, "send_notification", new_callable=AsyncMock) as mock_send,
        ):
            await watcher.check_and_notify()

        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "Article A" in msg
        assert "Article B" in msg
        mock_update.assert_called_once()

    async def test_check_and_notify_skips_known(self) -> None:
        brave = AsyncMock()
        result1 = SimpleNamespace(url="https://known.com", title="Known")
        brave.search.return_value = SimpleNamespace(results=[result1])

        watcher = TopicWatcher(brave=brave, telegram=_make_telegram(), settings=_make_settings())
        sub = _make_subscription(watcher_type="topic")

        with (
            patch.object(watcher, "_get_subscriptions", return_value=[sub]),
            patch.object(watcher, "_get_state", return_value=(["https://known.com"], None)),
            patch.object(watcher, "send_notification", new_callable=AsyncMock) as mock_send,
        ):
            await watcher.check_and_notify()

        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# GitHubWatcher
# ---------------------------------------------------------------------------


class TestGitHubWatcher:
    async def test_check_and_notify_new_issues(self) -> None:
        issue = SimpleNamespace(number=42, title="Bug fix", is_pr=False, labels=["bug"])
        github = MagicMock()
        github.list_issues = MagicMock(return_value=[issue])

        tg = _make_telegram()
        watcher = GitHubWatcher(github=github, telegram=tg, settings=_make_settings())
        sub = _make_subscription(watcher_type="github", target="owner/repo")

        with (
            patch.object(watcher, "_get_subscriptions", return_value=[sub]),
            patch.object(watcher, "_get_state", return_value=([], None)),
            patch.object(watcher, "_update_state", new_callable=AsyncMock),
            patch.object(watcher, "send_notification", new_callable=AsyncMock) as mock_send,
        ):
            await watcher.check_and_notify()

        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "Bug fix" in msg
        assert "#42" in msg

    async def test_check_and_notify_skips_known_issues(self) -> None:
        issue = SimpleNamespace(number=42, title="Bug fix", is_pr=False, labels=[])
        github = MagicMock()
        github.list_issues = MagicMock(return_value=[issue])

        watcher = GitHubWatcher(github=github, telegram=_make_telegram(), settings=_make_settings())
        sub = _make_subscription(watcher_type="github", target="owner/repo")

        with (
            patch.object(watcher, "_get_subscriptions", return_value=[sub]),
            patch.object(watcher, "_get_state", return_value=(["42"], None)),
            patch.object(watcher, "send_notification", new_callable=AsyncMock) as mock_send,
        ):
            await watcher.check_and_notify()

        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# RSSWatcher
# ---------------------------------------------------------------------------


class TestRSSWatcher:
    async def test_check_and_notify_new_entries(self) -> None:
        entry = SimpleNamespace(url="https://blog.com/post", title="New Post")
        rss = AsyncMock()
        rss.fetch_feed.return_value = SimpleNamespace(title="My Blog", entries=[entry])

        tg = _make_telegram()
        watcher = RSSWatcher(rss=rss, telegram=tg, settings=_make_settings())
        sub = _make_subscription(watcher_type="rss", target="https://blog.com/feed")

        with (
            patch.object(watcher, "_get_subscriptions", return_value=[sub]),
            patch.object(watcher, "_get_state", return_value=([], None)),
            patch.object(watcher, "_update_state", new_callable=AsyncMock),
            patch.object(watcher, "send_notification", new_callable=AsyncMock) as mock_send,
        ):
            await watcher.check_and_notify()

        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "New Post" in msg

    async def test_check_and_notify_empty_feed(self) -> None:
        rss = AsyncMock()
        rss.fetch_feed.return_value = SimpleNamespace(title="Empty Blog", entries=[])

        watcher = RSSWatcher(rss=rss, telegram=_make_telegram(), settings=_make_settings())
        sub = _make_subscription(watcher_type="rss", target="https://blog.com/feed")

        with (
            patch.object(watcher, "_get_subscriptions", return_value=[sub]),
            patch.object(watcher, "send_notification", new_callable=AsyncMock) as mock_send,
        ):
            await watcher.check_and_notify()

        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# EmailWatcher
# ---------------------------------------------------------------------------


class TestEmailWatcher:
    async def test_check_and_notify_new_unread(self) -> None:
        mail = SimpleNamespace(
            sender="alice@test.com",
            subject="Hello",
            date="2025-01-01",
            is_read=False,
        )
        email_client = AsyncMock()
        email_client.fetch_emails.return_value = [mail]

        tg = _make_telegram()
        watcher = EmailWatcher(email_client=email_client, telegram=tg, settings=_make_settings())
        sub = _make_subscription(watcher_type="email", target="inbox")

        with (
            patch.object(watcher, "_get_subscriptions", return_value=[sub]),
            patch.object(watcher, "_get_state", return_value=([], None)),
            patch.object(watcher, "_update_state", new_callable=AsyncMock),
            patch.object(watcher, "send_notification", new_callable=AsyncMock) as mock_send,
        ):
            await watcher.check_and_notify()

        mock_send.assert_called_once()
        msg = mock_send.call_args[0][1]
        assert "alice@test.com" in msg

    async def test_check_and_notify_all_read(self) -> None:
        mail = SimpleNamespace(
            sender="bob@test.com",
            subject="Read",
            date="2025-01-01",
            is_read=True,
        )
        email_client = AsyncMock()
        email_client.fetch_emails.return_value = [mail]

        watcher = EmailWatcher(email_client=email_client, telegram=_make_telegram(), settings=_make_settings())
        sub = _make_subscription(watcher_type="email", target="inbox")

        with (
            patch.object(watcher, "_get_subscriptions", return_value=[sub]),
            patch.object(watcher, "send_notification", new_callable=AsyncMock) as mock_send,
        ):
            await watcher.check_and_notify()

        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# SchedulerManager
# ---------------------------------------------------------------------------


class TestSchedulerManager:
    def test_init_with_all_integrations(self) -> None:
        mgr = SchedulerManager(
            telegram=_make_telegram(),
            settings=_make_settings(),
            brave=AsyncMock(),
            github=MagicMock(),
            rss=AsyncMock(),
            email=AsyncMock(),
        )
        assert len(mgr.watchers) == 4
        types = {w.watcher_type for w in mgr.watchers}
        assert types == {"topic", "github", "rss", "email"}

    def test_init_with_no_integrations(self) -> None:
        mgr = SchedulerManager(
            telegram=_make_telegram(),
            settings=_make_settings(),
        )
        assert len(mgr.watchers) == 0

    def test_init_with_partial_integrations(self) -> None:
        mgr = SchedulerManager(
            telegram=_make_telegram(),
            settings=_make_settings(),
            brave=AsyncMock(),
        )
        assert len(mgr.watchers) == 1
        assert mgr.watchers[0].watcher_type == "topic"

    async def test_start_and_stop(self) -> None:
        mgr = SchedulerManager(
            telegram=_make_telegram(),
            settings=_make_settings(),
            brave=AsyncMock(),
        )
        await mgr.start()
        assert mgr.watchers[0].is_running
        await mgr.stop()
        assert not mgr.watchers[0].is_running

    def test_get_status(self) -> None:
        mgr = SchedulerManager(
            telegram=_make_telegram(),
            settings=_make_settings(),
            brave=AsyncMock(),
            rss=AsyncMock(),
        )
        status = mgr.get_status()
        assert status["total"] == 2
        assert status["active"] == 0
        assert len(status["watchers"]) == 2
