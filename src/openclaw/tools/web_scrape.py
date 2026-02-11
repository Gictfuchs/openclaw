"""Web scraping tool for extracting page content."""

import re
from typing import Any

import httpx
import structlog

from openclaw.integrations import check_response_size, validate_url
from openclaw.tools.base import BaseTool

logger = structlog.get_logger()

# Max content length to return (chars)
_MAX_CONTENT_LENGTH = 30_000

# Max raw HTTP response size (2 MB)
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024

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

        # Validate URL using the shared SSRF-prevention utility
        error = validate_url(url)
        if error:
            return f"Error: {error}"

        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            # Redirect-SSRF check: validate the final URL after redirects
            final_url = str(resp.url)
            if final_url != url:
                redirect_error = validate_url(final_url)
                if redirect_error:
                    logger.warning("web_scrape_redirect_ssrf", original=url, final=final_url)
                    return f"Error: Redirect target blocked — {redirect_error}"
            check_response_size(resp.content, _MAX_RESPONSE_BYTES, context="web_scrape")
        except httpx.HTTPStatusError as e:
            return f"HTTP error {e.response.status_code} fetching {url}"
        except httpx.TimeoutException:
            return f"Timeout fetching {url}"
        except ValueError as e:
            return f"Error: {e}"
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
