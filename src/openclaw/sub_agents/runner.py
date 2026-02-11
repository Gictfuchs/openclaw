"""Sub-agent runner: spawns AgentLoop instances for delegated tasks."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from openclaw.core.agent_loop import AgentLoop
from openclaw.core.events import ErrorEvent, ResponseEvent
from openclaw.sub_agents.config import SUB_AGENT_TYPES, SubAgentConfig

if TYPE_CHECKING:
    from openclaw.llm.router import LLMRouter
    from openclaw.tools.registry import ToolRegistry

logger = structlog.get_logger()

# Hard limit: max concurrent sub-agents across all users
_MAX_CONCURRENT = 3
# Default timeout for a sub-agent run (seconds)
_DEFAULT_TIMEOUT = 120


class SubAgentRunner:
    """Manages sub-agent execution with concurrency and timeout guards."""

    def __init__(
        self,
        llm: LLMRouter,
        tools: ToolRegistry,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self._semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
        self._active: int = 0

    async def run(
        self,
        agent_type: str,
        task: str,
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> str:
        """Run a sub-agent and return its text response.

        Args:
            agent_type: Name of the sub-agent type (e.g. "research", "code", "summary").
            task: The task description / user message for the sub-agent.
            timeout: Max seconds before the sub-agent is cancelled.

        Returns:
            The sub-agent's final text response, or an error message.
        """
        config = SUB_AGENT_TYPES.get(agent_type)
        if config is None:
            available = ", ".join(sorted(SUB_AGENT_TYPES.keys()))
            return f"Unbekannter Sub-Agent Typ: '{agent_type}'. Verfuegbar: {available}"

        # Build a restricted tool registry for this sub-agent
        sub_tools = self.tools.get_subset(config.allowed_tools)

        logger.info(
            "sub_agent_starting",
            type=agent_type,
            tools=sub_tools.tool_names,
            max_iterations=config.max_iterations,
        )

        try:
            async with asyncio.timeout(timeout):
                return await self._execute(config, sub_tools, task)
        except TimeoutError:
            logger.warning("sub_agent_timeout", type=agent_type, timeout=timeout)
            return f"Sub-Agent '{agent_type}' hat das Zeitlimit ({timeout}s) ueberschritten."

    async def _execute(
        self,
        config: SubAgentConfig,
        sub_tools: ToolRegistry,
        task: str,
    ) -> str:
        """Execute the sub-agent loop under the concurrency semaphore."""
        async with self._semaphore:
            self._active += 1
            try:
                loop = AgentLoop(
                    llm=self.llm,
                    tool_registry=sub_tools,
                    system_prompt=config.system_prompt,
                    max_iterations=config.max_iterations,
                )

                # Collect the final response from the sub-agent
                response_parts: list[str] = []
                async for event in loop.run(task):
                    if isinstance(event, ResponseEvent):
                        response_parts.append(event.content)
                    elif isinstance(event, ErrorEvent):
                        response_parts.append(f"[Fehler] {event.message}")

                result = "\n".join(response_parts) if response_parts else "Sub-Agent lieferte keine Antwort."
                logger.info("sub_agent_completed", type=config.name, result_length=len(result))
                return result
            except Exception as e:
                logger.error("sub_agent_error", type=config.name, error=str(e))
                return f"Sub-Agent Fehler: {e}"
            finally:
                self._active -= 1

    def get_status(self) -> dict[str, Any]:
        """Return current sub-agent runner status."""
        return {
            "active": self._active,
            "max_concurrent": _MAX_CONCURRENT,
            "available_types": list(SUB_AGENT_TYPES.keys()),
        }
