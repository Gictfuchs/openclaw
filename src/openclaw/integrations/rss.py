"""RSS feed parser client.

Security:
- URL validation prevents SSRF (Server-Side Request Forgery)
- Response size is capped to prevent memory exhaustion
"""

from __future__ import annotations

from dataclasses import dataclass, field

import feedparser
import httpx
import structlog

from openclaw.integrations import validate_url

logger = structlog.get_logger()

# Maximum RSS response size (2 MB) — feeds larger than this are rejected
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


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
            max_redirects=5,
            headers={"User-Agent": "FochsBot/0.1 (+https://github.com/Gictfuchs/openclaw)"},
        )

    async def fetch_feed(self, url: str, limit: int = 10) -> FeedResult:
        """Fetch and parse an RSS/Atom feed."""
        # --- SSRF validation ---
        url_error = validate_url(url)
        if url_error:
            raise ValueError(f"Unsafe feed URL: {url_error}")

        try:
            resp = await self._http.get(url)
            resp.raise_for_status()
        except Exception as e:
            logger.error("rss_fetch_error", url=url, error=str(e))
            raise

        # --- Redirect-SSRF check: validate final URL after redirects ---
        final_url = str(resp.url)
        if final_url != url:
            redirect_error = validate_url(final_url)
            if redirect_error:
                logger.warning("rss_redirect_ssrf", original=url, final=final_url)
                raise ValueError(f"Redirect target blocked — {redirect_error}")

        # --- Response size check ---
        content_length = len(resp.content)
        if content_length > _MAX_RESPONSE_BYTES:
            msg = f"RSS response too large: {content_length} bytes (max {_MAX_RESPONSE_BYTES})"
            logger.warning("rss_response_too_large", url=url, size=content_length)
            raise ValueError(msg)

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
