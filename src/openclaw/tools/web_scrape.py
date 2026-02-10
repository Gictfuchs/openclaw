"""Web scraping tool for extracting page content."""

import re
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

from openclaw.tools.base import BaseTool

logger = structlog.get_logger()

# Max content length to return (chars)
_MAX_CONTENT_LENGTH = 30_000

# Blocked domains that should never be scraped
_BLOCKED_DOMAINS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "169.254.169.254",  # AWS metadata
        "metadata.google.internal",  # GCP metadata
    }
)

# Request headers to look like a regular browser
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FochsBot/0.1; +https://github.com/Gictfuchs/openclaw)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


class WebScrapeTool(BaseTool):
    """Scrape and extract text content from a web page."""

    name = "web_scrape"
    description = (
        "Fetch and extract the text content from a web page URL. "
        "Returns the main text content, stripped of HTML. "
        "Use after web_search to read full articles or pages."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL of the web page to scrape.",
            },
        },
        "required": ["url"],
    }

    def __init__(self, timeout: float = 20.0) -> None:
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers=_HEADERS,
            follow_redirects=True,
            max_redirects=5,
        )

    async def execute(self, **kwargs: Any) -> str:
        url = kwargs["url"]

        # Validate URL
        error = self._validate_url(url)
        if error:
            return f"Error: {error}"

        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            return f"HTTP error {e.response.status_code} fetching {url}"
        except httpx.TimeoutException:
            return f"Timeout fetching {url}"
        except Exception as e:
            return f"Error fetching {url}: {e}"

        content_type = resp.headers.get("content-type", "")
        if "text/html" not in content_type and "text/plain" not in content_type:
            return f"Unsupported content type: {content_type}"

        html = resp.text
        text = self._html_to_text(html)

        if not text.strip():
            return "Page returned no readable text content."

        if len(text) > _MAX_CONTENT_LENGTH:
            text = text[:_MAX_CONTENT_LENGTH] + f"\n\n[Content truncated at {_MAX_CONTENT_LENGTH} chars]"

        return f"Content from {url}:\n\n{text}"

    @staticmethod
    def _validate_url(url: str) -> str | None:
        """Validate URL for safety. Returns error message or None."""
        try:
            parsed = urlparse(url)
        except Exception:
            return "Invalid URL"

        if parsed.scheme not in ("http", "https"):
            return f"Unsupported scheme: {parsed.scheme}. Only http/https allowed."

        hostname = parsed.hostname or ""
        if hostname in _BLOCKED_DOMAINS:
            return f"Blocked domain: {hostname}"

        # Block private IP ranges
        if hostname.startswith("10.") or hostname.startswith("192.168.") or hostname.startswith("172."):
            return "Private IP addresses are not allowed."

        return None

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Convert HTML to readable text. Lightweight extraction without heavy dependencies."""
        # Remove script and style blocks
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<nav[^>]*>.*?</nav>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<footer[^>]*>.*?</footer>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<header[^>]*>.*?</header>", "", text, flags=re.DOTALL | re.IGNORECASE)

        # Convert common elements to text markers
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</?p[^>]*>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</?div[^>]*>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<h[1-6][^>]*>", "\n\n## ", text, flags=re.IGNORECASE)
        text = re.sub(r"</h[1-6]>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.IGNORECASE)

        # Strip remaining HTML tags
        text = re.sub(r"<[^>]+>", "", text)

        # Decode common HTML entities
        text = text.replace("&amp;", "&")
        text = text.replace("&lt;", "<")
        text = text.replace("&gt;", ">")
        text = text.replace("&quot;", '"')
        text = text.replace("&#39;", "'")
        text = text.replace("&nbsp;", " ")

        # Clean up whitespace
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

        return text

    async def close(self) -> None:
        await self._client.aclose()
