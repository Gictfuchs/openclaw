"""Tests for the web scrape tool."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from openclaw.tools.web_scrape import WebScrapeTool


@pytest.fixture
def scraper():
    return WebScrapeTool()


class TestWebScrapeTool:
    async def test_scrape_extracts_text(self, scraper: WebScrapeTool) -> None:
        html = """
        <html><body>
        <h1>Test Title</h1>
        <p>This is a paragraph.</p>
        <p>Another paragraph.</p>
        </body></html>
        """
        mock_response = httpx.Response(
            200,
            text=html,
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", "https://example.com"),
        )

        with patch.object(scraper._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await scraper.execute(url="https://example.com")

        assert "Test Title" in result
        assert "This is a paragraph" in result
        assert result.startswith("Content from https://example.com")

    async def test_scrape_strips_script_and_style(self, scraper: WebScrapeTool) -> None:
        html = """
        <html><body>
        <script>alert('xss')</script>
        <style>.hidden { display: none; }</style>
        <p>Visible content</p>
        </body></html>
        """
        mock_response = httpx.Response(
            200,
            text=html,
            headers={"content-type": "text/html"},
            request=httpx.Request("GET", "https://example.com"),
        )

        with patch.object(scraper._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await scraper.execute(url="https://example.com")

        assert "alert" not in result
        assert "display: none" not in result
        assert "Visible content" in result

    async def test_validate_url_blocks_private_ips(self, scraper: WebScrapeTool) -> None:
        result = await scraper.execute(url="http://192.168.1.1/admin")
        assert "Error" in result
        assert "Private IP" in result

    async def test_validate_url_blocks_metadata(self, scraper: WebScrapeTool) -> None:
        result = await scraper.execute(url="http://169.254.169.254/latest/meta-data")
        assert "Error" in result
        assert "Blocked domain" in result

    async def test_validate_url_blocks_localhost(self, scraper: WebScrapeTool) -> None:
        result = await scraper.execute(url="http://localhost:8080/secret")
        assert "Error" in result

    async def test_validate_url_rejects_non_http(self, scraper: WebScrapeTool) -> None:
        result = await scraper.execute(url="file:///etc/passwd")
        assert "Error" in result
        assert "Unsupported scheme" in result

    async def test_scrape_handles_http_error(self, scraper: WebScrapeTool) -> None:
        mock_response = httpx.Response(
            404,
            request=httpx.Request("GET", "https://example.com/missing"),
        )

        with patch.object(scraper._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await scraper.execute(url="https://example.com/missing")

        assert "HTTP error 404" in result

    async def test_scrape_rejects_non_text_content(self, scraper: WebScrapeTool) -> None:
        mock_response = httpx.Response(
            200,
            content=b"\x89PNG",
            headers={"content-type": "image/png"},
            request=httpx.Request("GET", "https://example.com/image.png"),
        )

        with patch.object(scraper._client, "get", new_callable=AsyncMock, return_value=mock_response):
            result = await scraper.execute(url="https://example.com/image.png")

        assert "Unsupported content type" in result

    def test_html_to_text_decodes_entities(self) -> None:
        html = "<p>&amp; &lt; &gt; &quot; &#39; &nbsp;</p>"
        text = WebScrapeTool._html_to_text(html)
        assert "& < > \" '" in text
