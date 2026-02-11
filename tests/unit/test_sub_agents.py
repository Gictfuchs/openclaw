"""Tests for sub-agent system (config, runner, delegate tool)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openclaw.core.events import ErrorEvent, ResponseEvent
from openclaw.sub_agents.config import (
    CODE_AGENT,
    RESEARCH_AGENT,
    SUB_AGENT_TYPES,
    SUMMARY_AGENT,
    SubAgentConfig,
)
from openclaw.sub_agents.runner import SubAgentRunner
from openclaw.tools.delegate_tool import DelegateTool

# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestSubAgentConfig:
    def test_config_is_frozen(self) -> None:
        cfg = SubAgentConfig(name="test", system_prompt="hello")
        with pytest.raises(AttributeError):
            cfg.name = "changed"  # type: ignore[misc]

    def test_builtin_types_exist(self) -> None:
        assert "research" in SUB_AGENT_TYPES
        assert "code" in SUB_AGENT_TYPES
        assert "summary" in SUB_AGENT_TYPES

    def test_research_config(self) -> None:
        assert RESEARCH_AGENT.name == "research"
        assert "web_search" in RESEARCH_AGENT.allowed_tools
        assert "web_scrape" in RESEARCH_AGENT.allowed_tools
        assert RESEARCH_AGENT.max_iterations == 8

    def test_code_config(self) -> None:
        assert CODE_AGENT.name == "code"
        assert "github_repo" in CODE_AGENT.allowed_tools
        assert CODE_AGENT.max_iterations == 5

    def test_summary_config(self) -> None:
        assert SUMMARY_AGENT.name == "summary"
        assert "recall_memory" in SUMMARY_AGENT.allowed_tools
        assert SUMMARY_AGENT.max_iterations == 3

    def test_default_values(self) -> None:
        cfg = SubAgentConfig(name="test", system_prompt="prompt")
        assert cfg.allowed_tools == []
        assert cfg.max_iterations == 5
        assert cfg.max_tokens == 15_000


# ---------------------------------------------------------------------------
# Runner tests
# ---------------------------------------------------------------------------


def _make_tool_registry():
    """Create a mock ToolRegistry with get_subset support."""
    registry = MagicMock()
    subset = MagicMock()
    subset.tool_names = ["web_search"]
    subset.get_definitions.return_value = []
    registry.get_subset.return_value = subset
    return registry


class TestSubAgentRunner:
    async def test_run_unknown_type(self) -> None:
        runner = SubAgentRunner(llm=AsyncMock(), tools=_make_tool_registry())
        result = await runner.run(agent_type="nonexistent", task="test")
        assert "Unbekannter Sub-Agent Typ" in result
        assert "research" in result  # should list available types

    async def test_run_returns_response(self) -> None:
        """Test that the runner collects ResponseEvents from the agent loop."""
        mock_llm = AsyncMock()
        runner = SubAgentRunner(llm=mock_llm, tools=_make_tool_registry())

        # Mock the AgentLoop to yield a single ResponseEvent
        async def mock_run(task, **kwargs):
            yield ResponseEvent(content="Research completed: AI is advancing fast.")

        with patch("openclaw.sub_agents.runner.AgentLoop") as mock_loop:
            mock_loop.return_value.run = mock_run
            result = await runner.run(agent_type="research", task="research AI trends")

        assert "Research completed" in result
        assert "AI is advancing fast" in result

    async def test_run_handles_error_event(self) -> None:
        mock_llm = AsyncMock()
        runner = SubAgentRunner(llm=mock_llm, tools=_make_tool_registry())

        async def mock_run(task, **kwargs):
            yield ErrorEvent(message="Budget exhausted")

        with patch("openclaw.sub_agents.runner.AgentLoop") as mock_loop:
            mock_loop.return_value.run = mock_run
            result = await runner.run(agent_type="summary", task="summarize this")

        assert "Budget exhausted" in result

    async def test_run_timeout(self) -> None:
        mock_llm = AsyncMock()
        runner = SubAgentRunner(llm=mock_llm, tools=_make_tool_registry())

        async def mock_run(task, **kwargs):
            await asyncio.sleep(10)  # will be cancelled
            yield ResponseEvent(content="never reached")

        with patch("openclaw.sub_agents.runner.AgentLoop") as mock_loop:
            mock_loop.return_value.run = mock_run
            result = await runner.run(agent_type="code", task="review code", timeout=0.1)

        assert "Zeitlimit" in result

    async def test_run_exception_handling(self) -> None:
        mock_llm = AsyncMock()
        runner = SubAgentRunner(llm=mock_llm, tools=_make_tool_registry())

        async def mock_run(task, **kwargs):
            raise RuntimeError("LLM crashed")
            yield  # make it a generator  # noqa: F401

        with patch("openclaw.sub_agents.runner.AgentLoop") as mock_loop:
            mock_loop.return_value.run = mock_run
            result = await runner.run(agent_type="research", task="test")

        assert "Fehler" in result
        assert "LLM crashed" in result

    async def test_concurrency_limit(self) -> None:
        """Verify the semaphore is used (active count tracks correctly)."""
        mock_llm = AsyncMock()
        runner = SubAgentRunner(llm=mock_llm, tools=_make_tool_registry())

        assert runner._active == 0

        async def mock_run(task, **kwargs):
            yield ResponseEvent(content="done")

        with patch("openclaw.sub_agents.runner.AgentLoop") as mock_loop:
            mock_loop.return_value.run = mock_run
            await runner.run(agent_type="summary", task="test")

        assert runner._active == 0  # Back to 0 after completion

    def test_get_status(self) -> None:
        runner = SubAgentRunner(llm=AsyncMock(), tools=_make_tool_registry())
        status = runner.get_status()
        assert status["active"] == 0
        assert status["max_concurrent"] == 3
        assert "research" in status["available_types"]
        assert "code" in status["available_types"]
        assert "summary" in status["available_types"]

    async def test_uses_restricted_tool_registry(self) -> None:
        """Verify the runner calls get_subset with the correct tool names."""
        mock_llm = AsyncMock()
        registry = _make_tool_registry()
        runner = SubAgentRunner(llm=mock_llm, tools=registry)

        async def mock_run(task, **kwargs):
            yield ResponseEvent(content="done")

        with patch("openclaw.sub_agents.runner.AgentLoop") as mock_loop:
            mock_loop.return_value.run = mock_run
            await runner.run(agent_type="research", task="test")

        registry.get_subset.assert_called_once_with(RESEARCH_AGENT.allowed_tools)


# ---------------------------------------------------------------------------
# DelegateTool tests
# ---------------------------------------------------------------------------


class TestDelegateTool:
    def test_tool_definition(self) -> None:
        runner = MagicMock()
        tool = DelegateTool(runner=runner)
        defn = tool.to_definition()
        assert defn["name"] == "delegate"
        assert "agent_type" in defn["input_schema"]["required"]
        assert "task" in defn["input_schema"]["required"]
        # Should list available agent types in the enum
        props = defn["input_schema"]["properties"]
        assert "research" in props["agent_type"]["enum"]
        assert "code" in props["agent_type"]["enum"]
        assert "summary" in props["agent_type"]["enum"]

    async def test_execute_calls_runner(self) -> None:
        runner = AsyncMock()
        runner.run = AsyncMock(return_value="Sub-agent result here")

        tool = DelegateTool(runner=runner)
        result = await tool.execute(agent_type="research", task="find info about AI")

        runner.run.assert_called_once_with(agent_type="research", task="find info about AI")
        assert result == "Sub-agent result here"

    async def test_execute_passes_through_errors(self) -> None:
        runner = AsyncMock()
        runner.run = AsyncMock(return_value="Sub-Agent Fehler: something broke")

        tool = DelegateTool(runner=runner)
        result = await tool.execute(agent_type="code", task="review this")

        assert "Fehler" in result
