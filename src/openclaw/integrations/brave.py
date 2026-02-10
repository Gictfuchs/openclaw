"""Brave Search API client."""

from dataclasses import dataclass, field

import httpx
import structlog

logger = structlog.get_logger()

_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


@dataclass
class SearchResult:
    """A single search result."""

    title: str
    url: str
    description: str
    age: str = ""  # e.g. "2 hours ago"


@dataclass
class BraveSearchResponse:
    """Parsed Brave Search response."""

    query: str
    results: list[SearchResult] = field(default_factory=list)
    news: list[SearchResult] = field(default_factory=list)


class BraveSearchClient:
    """Client for the Brave Search API."""

    def __init__(self, api_key: str, timeout: float = 15.0) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "gzip",
                "X-Subscription-Token": api_key,
            },
        )

    async def search(
        self,
        query: str,
        count: int = 10,
        country: str = "DE",
        search_lang: str = "de",
        freshness: str | None = None,
    ) -> BraveSearchResponse:
        """Search the web via Brave Search API.

        Args:
            query: Search query string.
            count: Number of results (max 20).
            country: Country code for results.
            search_lang: Language for search.
            freshness: Time filter - pd (past day), pw (past week), pm (past month), py (past year).
        """
        params: dict[str, str | int] = {
            "q": query,
            "count": min(count, 20),
            "country": country,
            "search_lang": search_lang,
            "text_decorations": "false",
        }
        if freshness:
            params["freshness"] = freshness

        try:
            resp = await self._client.get(_BRAVE_SEARCH_URL, params=params)
            resp.raise_for_status()
            data = resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("brave_search_http_error", status=e.response.status_code, query=query)
            raise
        except Exception as e:
            logger.error("brave_search_error", error=str(e), query=query)
            raise

        results = []
        for item in data.get("web", {}).get("results", []):
            results.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                description=item.get("description", ""),
                age=item.get("age", ""),
            ))

        news = []
        for item in data.get("news", {}).get("results", []):
            news.append(SearchResult(
                title=item.get("title", ""),
                url=item.get("url", ""),
                description=item.get("description", ""),
                age=item.get("age", ""),
            ))

        logger.info("brave_search", query=query, results=len(results), news=len(news))
        return BraveSearchResponse(query=query, results=results, news=news)

    async def close(self) -> None:
        await self._client.aclose()
