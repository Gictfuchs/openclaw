"""Tests for Brave Search client."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from openclaw.integrations.brave import BraveSearchClient, BraveSearchResponse


@pytest.fixture
def client():
    return BraveSearchClient(api_key="test-key")


class TestBraveSearchClient:
    async def test_search_returns_results(self, client: BraveSearchClient) -> None:
        mock_response = httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "title": "Test Result",
                            "url": "https://example.com",
                            "description": "A test result.",
                            "age": "2 hours ago",
                        },
                    ],
                },
                "news": {
                    "results": [
                        {
                            "title": "Test News",
                            "url": "https://news.example.com",
                            "description": "A news item.",
                        },
                    ],
                },
            },
            request=httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search"),
        )

        with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await client.search("test query")

        assert isinstance(result, BraveSearchResponse)
        assert result.query == "test query"
        assert len(result.results) == 1
        assert result.results[0].title == "Test Result"
        assert result.results[0].url == "https://example.com"
        assert result.results[0].age == "2 hours ago"
        assert len(result.news) == 1
        assert result.news[0].title == "Test News"

    async def test_search_handles_empty_response(self, client: BraveSearchClient) -> None:
        mock_response = httpx.Response(
            200,
            json={},
            request=httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search"),
        )

        with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await client.search("empty query")

        assert result.results == []
        assert result.news == []

    async def test_search_raises_on_http_error(self, client: BraveSearchClient) -> None:
        mock_response = httpx.Response(
            429,
            json={"error": "rate limited"},
            request=httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search"),
        )

        with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(httpx.HTTPStatusError):
                await client.search("rate limited")

    async def test_search_count_capped_at_20(self, client: BraveSearchClient) -> None:
        mock_response = httpx.Response(
            200,
            json={"web": {"results": []}, "news": {"results": []}},
            request=httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search"),
        )

        with patch.object(client._client, "get", new_callable=AsyncMock, return_value=mock_response) as mock_get:
            await client.search("test", count=50)
            call_args = mock_get.call_args
            assert call_args[1]["params"]["count"] == 20
