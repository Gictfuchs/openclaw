"""Tests for LLM router — fallback budget handling."""

from __future__ import annotations

import pytest

from openclaw.llm.base import BaseLLM, LLMResponse, TokenUsage
from openclaw.llm.router import LLMRouter, TaskComplexity
from openclaw.security.budget import TokenBudget


class FakeLLM(BaseLLM):
    """Minimal fake LLM for router tests."""

    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.provider_name = name
        self._fail = fail
        self.generate_calls: int = 0

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        self.generate_calls += 1
        if self._fail:
            raise RuntimeError(f"{self.provider_name} failed")
        return LLMResponse(
            content=f"response from {self.provider_name}",
            usage=TokenUsage(input_tokens=100, output_tokens=50),
            model="test-model",
            provider=self.provider_name,
        )

    async def is_available(self) -> bool:
        return not self._fail


@pytest.fixture
def budget() -> TokenBudget:
    return TokenBudget(daily_limit=100_000, monthly_limit=1_000_000, per_run_limit=50_000)


class TestRouterFallbackBudget:
    """Verify budget is correctly adjusted (not double-counted) on fallback."""

    async def test_success_path_adjusts_reservation(self, budget: TokenBudget) -> None:
        """On success, reservation should be adjusted to actual usage."""
        claude = FakeLLM("claude")
        router = LLMRouter(claude=claude)
        router.budget = budget

        response = await router.generate(
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=4096,
            complexity=TaskComplexity.COMPLEX,
        )

        assert response.content == "response from claude"
        # Actual usage = 150 tokens (100 + 50), not 4096 (the reservation)
        status = await budget.get_status()
        assert status["daily_usage"] == 150

    async def test_fallback_adjusts_reservation_not_double_counts(self, budget: TokenBudget) -> None:
        """On fallback, budget should be adjusted, not double-counted."""
        claude = FakeLLM("claude", fail=True)
        gemini = FakeLLM("gemini")
        router = LLMRouter(claude=claude, gemini=gemini)
        router.budget = budget

        response = await router.generate(
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=4096,
            complexity=TaskComplexity.COMPLEX,
        )

        assert response.content == "response from gemini"
        # Budget should only reflect actual gemini usage (150), not 4096 + 150
        status = await budget.get_status()
        assert status["daily_usage"] == 150

    async def test_all_fallbacks_fail_releases_reservation(self, budget: TokenBudget) -> None:
        """When all providers fail, the reservation should be released."""
        claude = FakeLLM("claude", fail=True)
        gemini = FakeLLM("gemini", fail=True)
        ollama = FakeLLM("ollama", fail=True)
        router = LLMRouter(claude=claude, gemini=gemini, ollama=ollama)
        router.budget = budget

        with pytest.raises(RuntimeError, match="All LLM providers failed"):
            await router.generate(
                messages=[{"role": "user", "content": "hello"}],
                max_tokens=4096,
                complexity=TaskComplexity.COMPLEX,
            )

        # Reservation should be fully released (usage = 0)
        status = await budget.get_status()
        assert status["daily_usage"] == 0

    async def test_fallback_no_budget_works(self) -> None:
        """Fallback without budget configured should still work."""
        claude = FakeLLM("claude", fail=True)
        gemini = FakeLLM("gemini")
        router = LLMRouter(claude=claude, gemini=gemini)
        # No budget set

        response = await router.generate(
            messages=[{"role": "user", "content": "hello"}],
            max_tokens=4096,
            complexity=TaskComplexity.COMPLEX,
        )

        assert response.content == "response from gemini"

    async def test_provider_selection_with_tools(self) -> None:
        """When tools are provided, Claude should be preferred."""
        claude = FakeLLM("claude")
        gemini = FakeLLM("gemini")
        router = LLMRouter(claude=claude, gemini=gemini)

        tools = [{"type": "function", "function": {"name": "test"}}]
        response = await router.generate(
            messages=[{"role": "user", "content": "hello"}],
            tools=tools,
        )

        assert response.provider == "claude"
        assert claude.generate_calls == 1
        assert gemini.generate_calls == 0

    async def test_provider_selection_web_search(self) -> None:
        """WEB_SEARCH complexity should prefer Gemini."""
        claude = FakeLLM("claude")
        gemini = FakeLLM("gemini")
        router = LLMRouter(claude=claude, gemini=gemini)

        response = await router.generate(
            messages=[{"role": "user", "content": "hello"}],
            complexity=TaskComplexity.WEB_SEARCH,
        )

        assert response.provider == "gemini"
