"""FochsAgent - the main agent class."""

from collections.abc import AsyncIterator
from typing import Any

import structlog

from openclaw.core.agent_loop import AgentLoop
from openclaw.core.events import AgentEvent
from openclaw.llm.router import LLMRouter
from openclaw.tools.registry import ToolRegistry

logger = structlog.get_logger()

SYSTEM_PROMPT = """\
Du bist Fochs, ein autonomer KI-Agent. Du bist intelligent, neugierig und hilfreich.

## Deine Fähigkeiten
- Du kannst mit dem User über Telegram und das Web-Dashboard kommunizieren
- Du hast Zugang zu verschiedenen Tools (Web-Suche, Scraping, etc.)
- Du kannst eigenständig recherchieren und Ergebnisse zusammenfassen
- Du merkst dir wichtige Informationen für zukünftige Gespräche

## Deine Persönlichkeit
- Direkt und präzise, ohne unnötiges Geschwätz
- Proaktiv: Du schlägst nächste Schritte vor, wenn es sinnvoll ist
- Ehrlich: Wenn du etwas nicht weißt, sagst du es
- Du antwortest in der Sprache des Users

## Regeln
- Nutze Tools wenn sie dir helfen, die Frage besser zu beantworten
- Fasse Recherche-Ergebnisse immer mit Quellen zusammen
- Bei unsicheren Aktionen: Frage den User um Erlaubnis
"""


class FochsAgent:
    """The main Fochs agent that processes messages and manages conversation state."""

    def __init__(
        self,
        llm: LLMRouter,
        tools: ToolRegistry,
        max_iterations: int = 10,
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.max_iterations = max_iterations
        # Per-user conversation history (in-memory for now)
        self._conversations: dict[int, list[dict[str, Any]]] = {}

    async def process(
        self,
        message: str,
        user_id: int,
    ) -> AsyncIterator[AgentEvent]:
        """Process a user message and yield agent events."""
        # Get or create conversation history for this user
        history = self._conversations.get(user_id, [])

        loop = AgentLoop(
            llm=self.llm,
            tool_registry=self.tools,
            system_prompt=SYSTEM_PROMPT,
            max_iterations=self.max_iterations,
        )

        # Collect events and update history
        async for event in loop.run(message, conversation_history=history):
            yield event

        # Update conversation history
        history.append({"role": "user", "content": message})
        # Keep last ~50 messages to avoid context overflow
        if len(history) > 50:
            history = history[-50:]
        self._conversations[user_id] = history

    def clear_history(self, user_id: int) -> None:
        """Clear conversation history for a user."""
        self._conversations.pop(user_id, None)

    async def get_status(self) -> dict[str, Any]:
        """Get agent status information."""
        availability = await self.llm.check_availability()
        return {
            "status": "running",
            "tools": self.tools.tool_names,
            "llm_providers": availability,
            "active_conversations": len(self._conversations),
        }
