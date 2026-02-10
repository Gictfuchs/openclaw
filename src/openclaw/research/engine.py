"""Multi-source research engine.

Orchestrates: Search -> Scrape -> Summarize with citation tracking.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

from openclaw.research.citations import Citation, CitationCollection
from openclaw.research.summarizer import summarize_research

if TYPE_CHECKING:
    from openclaw.integrations.brave import BraveSearchClient
    from openclaw.llm.gemini import GeminiLLM
    from openclaw.llm.router import LLMRouter
    from openclaw.tools.web_scrape import WebScrapeTool

logger = structlog.get_logger()


@dataclass
class ResearchResult:
    """Complete research result with summary and sources."""

    query: str
    summary: str
    citations: CitationCollection
    raw_content: str = ""

    def format(self) -> str:
        """Format as a complete research report."""
        parts = [
            f"Recherche: {self.query}\n",
            self.summary,
            "",
            self.citations.format_all(),
        ]
        return "\n".join(parts)


class ResearchEngine:
    """Multi-source research engine.

    Pipeline:
    1. Brave Search - get web results
    2. Gemini Grounded Search - get Google-grounded answer
    3. Scrape top results for full content
    4. Summarize everything with LLM
    """

    def __init__(
        self,
        llm: LLMRouter,
        brave: BraveSearchClient | None = None,
        gemini: GeminiLLM | None = None,
        scraper: WebScrapeTool | None = None,
        max_scrape: int = 3,
    ) -> None:
        self.llm = llm
        self.brave = brave
        self.gemini = gemini
        self.scraper = scraper
        self.max_scrape = max_scrape

    async def research(self, query: str) -> ResearchResult:
        """Run a full multi-source research pipeline."""
        citations = CitationCollection(query=query)
        content_parts: list[str] = []

        # Step 1: Brave Search
        if self.brave:
            try:
                brave_results = await self.brave.search(query, count=8)
                for r in brave_results.results:
                    idx = citations.add(
                        Citation(
                            url=r.url,
                            title=r.title,
                            snippet=r.description,
                            source_type="web",
                        )
                    )
                    content_parts.append(f"[{idx}] {r.title}: {r.description}")

                for n in brave_results.news:
                    idx = citations.add(
                        Citation(
                            url=n.url,
                            title=n.title,
                            snippet=n.description,
                            source_type="news",
                        )
                    )
                    content_parts.append(f"[{idx}] (News) {n.title}: {n.description}")

            except Exception as e:
                logger.warning("research_brave_failed", error=str(e))

        # Step 2: Gemini Grounded Search
        if self.gemini:
            try:
                gemini_response = await self.gemini.grounded_search(query)
                if gemini_response.content:
                    content_parts.append(f"\n--- Google Grounded Answer ---\n{gemini_response.content}")
            except Exception as e:
                logger.warning("research_gemini_failed", error=str(e))

        # Step 3: Scrape top results for deeper content
        if self.scraper and citations.citations:
            scrape_urls = [c.url for c in citations.citations[: self.max_scrape]]
            for url in scrape_urls:
                try:
                    scraped = await self.scraper.execute(url=url)
                    if scraped and not scraped.startswith("Error"):
                        # Take first 3000 chars per page to keep total manageable
                        content_parts.append(f"\n--- Scraped: {url} ---\n{scraped[:3000]}")
                except Exception as e:
                    logger.debug("research_scrape_failed", url=url, error=str(e))

        raw_content = "\n\n".join(content_parts)

        # Step 4: Summarize
        if content_parts:
            summary = await summarize_research(
                llm=self.llm,
                topic=query,
                content=raw_content,
                citations=citations,
            )
        else:
            summary = "Keine Ergebnisse gefunden. Versuche eine andere Suchanfrage."

        logger.info("research_complete", query=query, sources=len(citations.citations))

        return ResearchResult(
            query=query,
            summary=summary,
            citations=citations,
            raw_content=raw_content,
        )
