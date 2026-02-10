"""Tool registry for discovering and executing tools."""

from typing import Any

import structlog

from openclaw.tools.base import BaseTool

logger = structlog.get_logger()


class ToolRegistry:
    """Registry for agent tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool
        logger.debug("tool_registered", name=tool.name)

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def get_definitions(self) -> list[dict[str, Any]]:
        """Return all tool definitions for the LLM."""
        return [tool.to_definition() for tool in self._tools.values()]

    async def execute(self, name: str, input_data: dict[str, Any]) -> str:
        """Execute a tool by name."""
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: Unknown tool '{name}'"

        try:
            result = await tool.execute(**input_data)
            logger.info("tool_executed", tool=name, result_length=len(result))
            return result
        except Exception as e:
            error_msg = f"Error executing tool '{name}': {e}"
            logger.error("tool_error", tool=name, error=str(e))
            return error_msg

    def get_subset(self, names: list[str]) -> "ToolRegistry":
        """Return a new registry with only the specified tools."""
        subset = ToolRegistry()
        for name in names:
            tool = self._tools.get(name)
            if tool:
                subset.register(tool)
        return subset

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools.keys())
