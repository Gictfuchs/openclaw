"""Tests for RSS integration and tools."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from openclaw.integrations.rss import FeedEntry, FeedResult, RSSClient
from openclaw.tools.rss_tools import CheckFeedTool

_SAMPLE_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>
    <link>https://example.com</link>
    <item>
      <title>Article One</title>
      <link>https://example.com/article-1</link>
      <description>First article summary.</description>
      <pubDate>Mon, 01 Jan 2025 12:00:00 GMT</pubDate>
      <author>Author A</author>
    </item>
    <item>
      <title>Article Two</title>
      <link>https://example.com/article-2</link>
      <description>&lt;p&gt;HTML in summary&lt;/p&gt;</description>
    </item>
  </channel>
</rss>
"""


@pytest.fixture
def rss_client():
    return RSSClient()


class TestRSSClient:
    async def test_fetch_feed_parses_entries(self, rss_client: RSSClient) -> None:
        mock_response = httpx.Response(
            200,
            text=_SAMPLE_RSS,
            request=httpx.Request("GET", "https://example.com/feed"),
        )

        with patch.object(rss_client._http, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await rss_client.fetch_feed("https://example.com/feed")

        assert result.title == "Test Feed"
        assert len(result.entries) == 2
        assert result.entries[0].title == "Article One"
        assert result.entries[0].author == "Author A"
        # HTML should be stripped from summary
        assert "<p>" not in result.entries[1].summary
        assert "HTML in summary" in result.entries[1].summary

    async def test_fetch_feed_limit(self, rss_client: RSSClient) -> None:
        mock_response = httpx.Response(
            200,
            text=_SAMPLE_RSS,
            request=httpx.Request("GET", "https://example.com/feed"),
        )

        with patch.object(rss_client._http, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await rss_client.fetch_feed("https://example.com/feed", limit=1)

        assert len(result.entries) == 1

    async def test_fetch_feed_http_error(self, rss_client: RSSClient) -> None:
        mock_response = httpx.Response(
            404,
            request=httpx.Request("GET", "https://example.com/feed"),
        )

        with (
            patch.object(rss_client._http, "get", new_callable=AsyncMock, return_value=mock_response),
            pytest.raises(httpx.HTTPStatusError),
        ):
            await rss_client.fetch_feed("https://example.com/feed")


class TestCheckFeedTool:
    async def test_formats_feed_entries(self) -> None:
        mock_client = AsyncMock(spec=RSSClient)
        mock_client.fetch_feed.return_value = FeedResult(
            title="Tech News",
            url="https://news.example.com/rss",
            entries=[
                FeedEntry(
                    title="New Python Release",
                    url="https://news.example.com/python",
                    summary="Python 3.14 released.",
                    published="2025-01-01",
                    author="Editor",
                ),
            ],
        )

        tool = CheckFeedTool(client=mock_client)
        result = await tool.execute(url="https://news.example.com/rss")

        assert "Tech News" in result
        assert "New Python Release" in result
        assert "Python 3.14" in result
        assert "2025-01-01" in result

    async def test_empty_feed(self) -> None:
        mock_client = AsyncMock(spec=RSSClient)
        mock_client.fetch_feed.return_value = FeedResult(
            title="Empty Feed",
            url="https://empty.example.com/rss",
            entries=[],
        )

        tool = CheckFeedTool(client=mock_client)
        result = await tool.execute(url="https://empty.example.com/rss")

        assert "no entries" in result

    async def test_error_handling(self) -> None:
        mock_client = AsyncMock(spec=RSSClient)
        mock_client.fetch_feed.side_effect = Exception("Connection timeout")

        tool = CheckFeedTool(client=mock_client)
        result = await tool.execute(url="https://broken.example.com/rss")

        assert "Error" in result

    def test_tool_definition(self) -> None:
        mock_client = AsyncMock(spec=RSSClient)
        tool = CheckFeedTool(client=mock_client)
        defn = tool.to_definition()
        assert defn["name"] == "check_feed"
        assert "url" in defn["input_schema"]["properties"]
