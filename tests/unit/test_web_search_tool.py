"""Tests for the web search tool."""

from unittest.mock import AsyncMock

import pytest

from openclaw.integrations.brave import BraveSearchClient, BraveSearchResponse, SearchResult
from openclaw.tools.web_search import WebSearchTool


@pytest.fixture
def mock_client():
    return AsyncMock(spec=BraveSearchClient)


class TestWebSearchTool:
    async def test_execute_formats_results(self, mock_client: AsyncMock) -> None:
        mock_client.search.return_value = BraveSearchResponse(
            query="test",
            results=[
                SearchResult(title="Result 1", url="https://a.com", description="Desc 1", age="1h ago"),
                SearchResult(title="Result 2", url="https://b.com", description="Desc 2"),
            ],
        )

        tool = WebSearchTool(client=mock_client)
        result = await tool.execute(query="test")

        assert "Result 1" in result
        assert "https://a.com" in result
        assert "1h ago" in result
        assert "Result 2" in result

    async def test_execute_includes_news(self, mock_client: AsyncMock) -> None:
        mock_client.search.return_value = BraveSearchResponse(
            query="test",
            results=[SearchResult(title="Web", url="https://a.com", description="Web result")],
            news=[SearchResult(title="News Item", url="https://news.com", description="News desc")],
        )

        tool = WebSearchTool(client=mock_client)
        result = await tool.execute(query="test")

        assert "News" in result
        assert "News Item" in result

    async def test_execute_handles_no_results(self, mock_client: AsyncMock) -> None:
        mock_client.search.return_value = BraveSearchResponse(query="nothing")

        tool = WebSearchTool(client=mock_client)
        result = await tool.execute(query="nothing")

        assert "No results found" in result

    async def test_execute_handles_api_error(self, mock_client: AsyncMock) -> None:
        mock_client.search.side_effect = Exception("API down")

        tool = WebSearchTool(client=mock_client)
        result = await tool.execute(query="fail")

        assert "Search failed" in result

    async def test_count_capped_at_10(self, mock_client: AsyncMock) -> None:
        mock_client.search.return_value = BraveSearchResponse(query="test")

        tool = WebSearchTool(client=mock_client)
        await tool.execute(query="test", count=50)

        mock_client.search.assert_called_once_with(query="test", count=10, freshness=None)

    def test_tool_definition(self, mock_client: AsyncMock) -> None:
        tool = WebSearchTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "web_search"
        assert "input_schema" in defn
        assert "query" in defn["input_schema"]["properties"]
