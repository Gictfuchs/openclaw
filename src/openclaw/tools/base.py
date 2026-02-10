"""Abstract tool interface."""

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """Base class for all agent tools."""

    name: str = ""
    description: str = ""
    parameters: dict[str, Any] = {}

    def to_definition(self) -> dict[str, Any]:
        """Return Claude-compatible tool definition."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """Execute the tool and return a string result."""
        ...
