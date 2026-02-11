"""Tests for scheduler tools (watch, unwatch, list_watches)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from openclaw.tools.scheduler_tools import ListWatchesTool, UnwatchTool, WatchTool

# ---------------------------------------------------------------------------
# Mock helpers for DB session
# ---------------------------------------------------------------------------


def _mock_session_context(session_mock):
    """Create an async context manager that yields *session_mock*."""

    class _Ctx:
        async def __aenter__(self):
            return session_mock

        async def __aexit__(self, *args):
            pass

    return _Ctx()


# ---------------------------------------------------------------------------
# WatchTool
# ---------------------------------------------------------------------------


class TestWatchTool:
    async def test_creates_subscription(self) -> None:
        tool = WatchTool(user_id=42)

        session = AsyncMock()
        # After flush, the sub should have an id attribute
        added_objects: list = []

        def capture_add(obj):
            obj.id = 1  # simulate DB-assigned id
            added_objects.append(obj)

        session.add = MagicMock(side_effect=capture_add)
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        with patch("openclaw.tools.scheduler_tools.get_session", return_value=_mock_session_context(session)):
            result = await tool.execute(target="AI news", watcher_type="topic")

        assert "Watch erstellt" in result
        assert "#1" in result
        assert "topic" in result
        assert "AI news" in result
        assert len(added_objects) == 2  # subscription + watcher state

    async def test_rejects_invalid_type(self) -> None:
        tool = WatchTool(user_id=42)
        result = await tool.execute(target="something", watcher_type="invalid")
        assert "Ungueltiger Typ" in result

    async def test_handles_db_error(self) -> None:
        tool = WatchTool(user_id=42)

        session = AsyncMock()
        session.add = MagicMock(side_effect=RuntimeError("DB gone"))

        with patch("openclaw.tools.scheduler_tools.get_session", return_value=_mock_session_context(session)):
            result = await tool.execute(target="test", watcher_type="rss")

        assert "Fehler" in result


# ---------------------------------------------------------------------------
# UnwatchTool
# ---------------------------------------------------------------------------


class TestUnwatchTool:
    async def test_deactivates_subscription(self) -> None:
        tool = UnwatchTool()

        sub = MagicMock()
        sub.id = 5
        sub.active = True
        sub.watcher_type = "github"
        sub.target = "owner/repo"

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = sub

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)
        session.commit = AsyncMock()

        with patch("openclaw.tools.scheduler_tools.get_session", return_value=_mock_session_context(session)):
            result = await tool.execute(subscription_id=5)

        assert "deaktiviert" in result
        assert sub.active is False

    async def test_not_found(self) -> None:
        tool = UnwatchTool()

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        with patch("openclaw.tools.scheduler_tools.get_session", return_value=_mock_session_context(session)):
            result = await tool.execute(subscription_id=999)

        assert "nicht gefunden" in result

    async def test_already_inactive(self) -> None:
        tool = UnwatchTool()

        sub = MagicMock()
        sub.id = 3
        sub.active = False

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = sub

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        with patch("openclaw.tools.scheduler_tools.get_session", return_value=_mock_session_context(session)):
            result = await tool.execute(subscription_id=3)

        assert "bereits deaktiviert" in result


# ---------------------------------------------------------------------------
# ListWatchesTool
# ---------------------------------------------------------------------------


class TestListWatchesTool:
    async def test_lists_active_subs(self) -> None:
        tool = ListWatchesTool()

        sub1 = MagicMock(id=1, watcher_type="topic", target="AI", user_id=42)
        sub2 = MagicMock(id=2, watcher_type="rss", target="https://feed.com", user_id=42)

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [sub1, sub2]

        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        with patch("openclaw.tools.scheduler_tools.get_session", return_value=_mock_session_context(session)):
            result = await tool.execute()

        assert "#1" in result
        assert "#2" in result
        assert "topic" in result
        assert "rss" in result

    async def test_empty_list(self) -> None:
        tool = ListWatchesTool()

        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []

        result_mock = MagicMock()
        result_mock.scalars.return_value = scalars_mock

        session = AsyncMock()
        session.execute = AsyncMock(return_value=result_mock)

        with patch("openclaw.tools.scheduler_tools.get_session", return_value=_mock_session_context(session)):
            result = await tool.execute()

        assert "Keine aktiven Watches" in result
