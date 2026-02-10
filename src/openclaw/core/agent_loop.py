"""The central agent loop: plan → act → observe → repeat."""

from collections.abc import AsyncIterator
from typing import Any

import structlog

from openclaw.core.events import (
    AgentEvent,
    ErrorEvent,
    ResponseEvent,
    ToolCallEvent,
    ToolResultEvent,
)
from openclaw.llm.router import LLMRouter, TaskComplexity
from openclaw.tools.registry import ToolRegistry

logger = structlog.get_logger()


class AgentLoop:
    """The agentic loop that drives Fochs."""

    def __init__(
        self,
        llm: LLMRouter,
        tool_registry: ToolRegistry,
        system_prompt: str,
        max_iterations: int = 10,
    ) -> None:
        self.llm = llm
        self.tools = tool_registry
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations

    async def run(
        self,
        user_message: str,
        conversation_history: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[AgentEvent]:
        """Run the agent loop, yielding events as they happen."""
        messages = list(conversation_history) if conversation_history else []
        messages.append({"role": "user", "content": user_message})

        tool_defs = self.tools.get_definitions() if self.tools.tool_names else None

        for iteration in range(self.max_iterations):
            logger.debug("agent_loop_iteration", iteration=iteration)

            response = await self.llm.generate(
                messages=messages,
                tools=tool_defs,
                system=self.system_prompt,
                complexity=TaskComplexity.COMPLEX,
            )

            # If the response has no tool calls, it's the final response
            if not response.tool_calls:
                yield ResponseEvent(content=response.content)
                return

            # Build assistant message with text + tool_use blocks
            assistant_content: list[dict[str, Any]] = []
            if response.content:
                assistant_content.append({"type": "text", "text": response.content})
            for call in response.tool_calls:
                assistant_content.append({
                    "type": "tool_use",
                    "id": call.id,
                    "name": call.name,
                    "input": call.input,
                })
            messages.append({"role": "assistant", "content": assistant_content})

            # Execute each tool call
            tool_results: list[dict[str, Any]] = []
            for call in response.tool_calls:
                yield ToolCallEvent(tool=call.name, input=call.input)

                result = await self.tools.execute(call.name, call.input)
                yield ToolResultEvent(tool=call.name, output=result)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": result,
                })

            messages.append({"role": "user", "content": tool_results})

        yield ErrorEvent(message=f"Max iterations ({self.max_iterations}) reached")
