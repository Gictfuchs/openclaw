"""Tests for short-term memory."""

from openclaw.memory.short_term import ShortTermMemory


class TestShortTermMemory:
    def test_add_and_get(self) -> None:
        mem = ShortTermMemory()
        mem.add_message(1, "user", "Hello")
        mem.add_message(1, "assistant", "Hi!")

        history = mem.get_history(1)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["content"] == "Hi!"

    def test_separate_users(self) -> None:
        mem = ShortTermMemory()
        mem.add_message(1, "user", "User 1 message")
        mem.add_message(2, "user", "User 2 message")

        assert len(mem.get_history(1)) == 1
        assert len(mem.get_history(2)) == 1

    def test_max_messages(self) -> None:
        mem = ShortTermMemory(max_messages=3)
        for i in range(5):
            mem.add_message(1, "user", f"msg {i}")

        history = mem.get_history(1)
        assert len(history) == 3
        assert history[0]["content"] == "msg 2"  # Oldest kept

    def test_clear(self) -> None:
        mem = ShortTermMemory()
        mem.add_message(1, "user", "Hello")
        mem.clear(1)
        assert mem.get_history(1) == []

    def test_empty_history(self) -> None:
        mem = ShortTermMemory()
        assert mem.get_history(999) == []

    def test_active_conversations(self) -> None:
        mem = ShortTermMemory()
        assert mem.active_conversations == 0
        mem.add_message(1, "user", "a")
        mem.add_message(2, "user", "b")
        assert mem.active_conversations == 2

    def test_get_all_user_ids(self) -> None:
        mem = ShortTermMemory()
        mem.add_message(10, "user", "a")
        mem.add_message(20, "user", "b")
        assert sorted(mem.get_all_user_ids()) == [10, 20]

    def test_get_history_returns_copy(self) -> None:
        mem = ShortTermMemory()
        mem.add_message(1, "user", "Hello")
        history = mem.get_history(1)
        history.append({"role": "user", "content": "injected"})
        assert len(mem.get_history(1)) == 1  # Original not modified
