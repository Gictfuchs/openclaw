"""Google Grounded Search tool via Gemini."""

from typing import Any

import structlog

from openclaw.llm.gemini import GeminiLLM
from openclaw.tools.base import BaseTool

logger = structlog.get_logger()


class GoogleSearchTool(BaseTool):
    """Search via Gemini with Google Search grounding.

    Uses Gemini's built-in Google Search to get grounded, up-to-date answers.
    Best for factual questions where you want a synthesized answer with sources.
    """

    name = "google_search"
    description = (
        "Search Google via Gemini grounding for a synthesized, up-to-date answer. "
        "Best for factual questions, current events, and topics where a direct answer is helpful. "
        "Returns a grounded answer (not raw search results)."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query or question.",
            },
        },
        "required": ["query"],
    }

    def __init__(self, gemini: GeminiLLM) -> None:
        self._gemini = gemini

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs["query"]

        try:
            response = await self._gemini.grounded_search(query)
        except Exception as e:
            return f"Google search failed: {e}"

        if not response.content:
            return "No answer found."

        # Extract grounding sources from raw response if available
        sources = self._extract_sources(response.raw)

        parts = [f"Google Search answer for: {query}\n", response.content]

        if sources:
            parts.append("\n\nSources:")
            for url, title in sources:
                parts.append(f"- [{title}]({url})")

        return "\n".join(parts)

    @staticmethod
    def _extract_sources(raw_response: Any) -> list[tuple[str, str]]:
        """Extract grounding source URLs from the raw Gemini response."""
        sources: list[tuple[str, str]] = []
        if raw_response is None:
            return sources

        try:
            # Navigate Gemini response structure for grounding metadata
            candidates = getattr(raw_response, "candidates", None)
            if not candidates:
                return sources

            candidate = candidates[0]
            grounding = getattr(candidate, "grounding_metadata", None)
            if not grounding:
                return sources

            chunks = getattr(grounding, "grounding_chunks", None) or []
            for chunk in chunks:
                web = getattr(chunk, "web", None)
                if web:
                    url = getattr(web, "uri", "")
                    title = getattr(web, "title", url)
                    if url:
                        sources.append((url, title))

        except (IndexError, AttributeError):
            pass

        return sources
