"""Abstract LLM interface and shared types."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    """A tool call from the LLM."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class TokenUsage:
    """Token usage statistics."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""

    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: TokenUsage | None = None
    stop_reason: str = "end_turn"
    raw: Any = None  # Original provider response
    model: str = ""
    provider: str = ""


class BaseLLM(ABC):
    """Abstract base class for LLM providers."""

    provider_name: str = "unknown"

    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        """Generate a response from the LLM."""
        ...

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if this LLM provider is currently reachable."""
        ...
