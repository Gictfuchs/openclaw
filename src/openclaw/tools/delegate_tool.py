"""Delegation tool: allows the main agent to spawn sub-agents."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from openclaw.sub_agents.config import SUB_AGENT_TYPES
from openclaw.tools.base import BaseTool

if TYPE_CHECKING:
    from openclaw.sub_agents.runner import SubAgentRunner

logger = structlog.get_logger()


class DelegateTool(BaseTool):
    """Delegate a task to a specialized sub-agent."""

    name = "delegate"
    description = (
        "Delegate a complex task to a specialized sub-agent. "
        "Available types: 'research' (deep web research with sources), "
        "'code' (code review, analysis, suggestions), "
        "'summary' (condense long texts or conversations). "
        "The sub-agent will work autonomously and return its result."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "agent_type": {
                "type": "string",
                "enum": list(SUB_AGENT_TYPES.keys()),
                "description": "Type of sub-agent to use.",
            },
            "task": {
                "type": "string",
                "description": "Detailed task description for the sub-agent. Be specific about what you need.",
            },
        },
        "required": ["agent_type", "task"],
    }

    def __init__(self, runner: SubAgentRunner) -> None:
        self._runner = runner

    async def execute(self, **kwargs: Any) -> str:
        agent_type = kwargs["agent_type"]
        task = kwargs["task"]

        logger.info("delegate_tool_called", agent_type=agent_type, task_length=len(task))
        result = await self._runner.run(agent_type=agent_type, task=task)
        return result
