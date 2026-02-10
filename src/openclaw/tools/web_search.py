"""Brave Search tool for the agent."""

from typing import Any

import structlog

from openclaw.integrations.brave import BraveSearchClient
from openclaw.tools.base import BaseTool

logger = structlog.get_logger()


class WebSearchTool(BaseTool):
    """Search the web using Brave Search API."""

    name = "web_search"
    description = (
        "Search the web for current information. Returns titles, URLs, and descriptions. "
        "Use for general knowledge, news, technical questions, etc."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "count": {
                "type": "integer",
                "description": "Number of results to return (1-10, default 5).",
            },
            "freshness": {
                "type": "string",
                "description": "Time filter: 'pd' (past day), 'pw' (past week), 'pm' (past month), 'py' (past year).",
                "enum": ["pd", "pw", "pm", "py"],
            },
        },
        "required": ["query"],
    }

    def __init__(self, client: BraveSearchClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs["query"]
        count = min(kwargs.get("count", 5), 10)
        freshness = kwargs.get("freshness")

        try:
            response = await self._client.search(
                query=query,
                count=count,
                freshness=freshness,
            )
        except Exception as e:
            return f"Search failed: {e}"

        parts: list[str] = [f"Web search results for: {query}\n"]

        for i, r in enumerate(response.results[:count], 1):
            age_str = f" ({r.age})" if r.age else ""
            parts.append(f"{i}. [{r.title}]({r.url}){age_str}\n   {r.description}\n")

        if response.news:
            parts.append("\n--- News ---\n")
            for i, n in enumerate(response.news[:3], 1):
                age_str = f" ({n.age})" if n.age else ""
                parts.append(f"{i}. [{n.title}]({n.url}){age_str}\n   {n.description}\n")

        if not response.results and not response.news:
            parts.append("No results found.")

        return "\n".join(parts)
