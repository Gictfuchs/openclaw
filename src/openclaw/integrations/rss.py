"""RSS feed parser client."""

from __future__ import annotations

from dataclasses import dataclass, field

import feedparser
import httpx
import structlog

logger = structlog.get_logger()


@dataclass
class FeedEntry:
    """A single RSS feed entry."""

    title: str
    url: str
    summary: str
    published: str = ""
    author: str = ""


@dataclass
class FeedResult:
    """Parsed RSS feed."""

    title: str
    url: str
    entries: list[FeedEntry] = field(default_factory=list)


class RSSClient:
    """Async RSS feed reader."""

    def __init__(self, timeout: float = 15.0) -> None:
        self._http = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": "FochsBot/0.1 (+https://github.com/Gictfuchs/openclaw)"},
        )

    async def fetch_feed(self, url: str, limit: int = 10) -> FeedResult:
        """Fetch and parse an RSS/Atom feed."""
        try:
            resp = await self._http.get(url)
            resp.raise_for_status()
        except Exception as e:
            logger.error("rss_fetch_error", url=url, error=str(e))
            raise

        feed = feedparser.parse(resp.text)

        entries = []
        for entry in feed.entries[:limit]:
            summary = entry.get("summary", "")
            # Strip HTML tags from summary
            if "<" in summary:
                import re

                summary = re.sub(r"<[^>]+>", "", summary)
            summary = summary[:500]

            entries.append(
                FeedEntry(
                    title=entry.get("title", ""),
                    url=entry.get("link", ""),
                    summary=summary,
                    published=entry.get("published", ""),
                    author=entry.get("author", ""),
                )
            )

        feed_title = feed.feed.get("title", url)
        logger.info("rss_fetched", feed=feed_title, entries=len(entries))

        return FeedResult(title=feed_title, url=url, entries=entries)

    async def close(self) -> None:
        await self._http.aclose()
