"""Typed event system for cross-component communication."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class AgentEvent:
    """Base event class."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class ThinkingEvent(AgentEvent):
    """Agent is reasoning."""

    content: str = ""


@dataclass
class ToolCallEvent(AgentEvent):
    """Agent is calling a tool."""

    tool: str = ""
    input: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolResultEvent(AgentEvent):
    """Tool returned a result."""

    tool: str = ""
    output: str = ""


@dataclass
class ResponseEvent(AgentEvent):
    """Agent's final text response."""

    content: str = ""


@dataclass
class ErrorEvent(AgentEvent):
    """A recoverable error occurred."""

    message: str = ""
    recoverable: bool = True
