"""RSS feed tools for the agent."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from openclaw.tools.base import BaseTool

if TYPE_CHECKING:
    from openclaw.integrations.rss import RSSClient

logger = structlog.get_logger()


class CheckFeedTool(BaseTool):
    """Check an RSS/Atom feed for recent entries."""

    name = "check_feed"
    description = (
        "Fetch and display recent entries from an RSS or Atom feed URL. "
        "Use for news sites, blogs, podcasts, or any RSS-enabled source."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The RSS/Atom feed URL.",
            },
            "limit": {
                "type": "integer",
                "description": "Number of entries to return (default 5, max 15).",
            },
        },
        "required": ["url"],
    }

    def __init__(self, client: RSSClient) -> None:
        self._client = client

    async def execute(self, **kwargs: Any) -> str:
        url = kwargs["url"]
        limit = min(kwargs.get("limit", 5), 15)

        try:
            feed = await self._client.fetch_feed(url, limit=limit)
        except Exception as e:
            return f"Error fetching feed '{url}': {e}"

        if not feed.entries:
            return f"Feed '{feed.title}' has no entries."

        parts = [f"Feed: {feed.title}\n"]
        for i, entry in enumerate(feed.entries, 1):
            published = f" ({entry.published})" if entry.published else ""
            author = f" - {entry.author}" if entry.author else ""
            parts.append(f"{i}. [{entry.title}]({entry.url}){published}{author}\n   {entry.summary}\n")

        return "\n".join(parts)
