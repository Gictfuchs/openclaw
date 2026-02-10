"""Tool registry for discovering and executing tools."""

import json
from typing import Any

import structlog

from openclaw.tools.base import BaseTool

logger = structlog.get_logger()

# Maximum result size to prevent memory issues from tool output
_MAX_RESULT_LENGTH = 50_000


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
        """Execute a tool by name with input validation."""
        tool = self._tools.get(name)
        if tool is None:
            return f"Error: Unknown tool '{name}'"

        # Validate input against tool schema
        validation_error = self._validate_input(tool, input_data)
        if validation_error:
            logger.warning("tool_input_invalid", tool=name, error=validation_error)
            return f"Error: Invalid input for tool '{name}': {validation_error}"

        try:
            result = await tool.execute(**input_data)
            # Truncate oversized results
            if len(result) > _MAX_RESULT_LENGTH:
                result = result[:_MAX_RESULT_LENGTH] + f"\n[truncated at {_MAX_RESULT_LENGTH} chars]"
            logger.info("tool_executed", tool=name, result_length=len(result))
            return result
        except Exception as e:
            error_msg = f"Error executing tool '{name}': {type(e).__name__}: {e}"
            logger.error("tool_error", tool=name, error=str(e))
            return error_msg

    @staticmethod
    def _validate_input(tool: BaseTool, input_data: dict[str, Any]) -> str | None:
        """Basic validation of tool input against its schema. Returns error or None."""
        schema = tool.parameters
        if not schema:
            return None

        # Check required fields
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        for field in required:
            if field not in input_data:
                return f"Missing required field: {field}"

        # Check no unexpected fields (prevents injection of extra params)
        if properties:
            for key in input_data:
                if key not in properties:
                    return f"Unexpected field: {key}"

        return None

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
