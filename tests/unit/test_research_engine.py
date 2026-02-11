"""Tests for the research engine."""

from unittest.mock import AsyncMock

import pytest

from openclaw.integrations.brave import BraveSearchResponse, SearchResult
from openclaw.llm.base import LLMResponse, TokenUsage
from openclaw.research.engine import ResearchEngine


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.generate.return_value = LLMResponse(
        content="Zusammenfassung: Test topic ist wichtig.",
        usage=TokenUsage(input_tokens=100, output_tokens=50),
        model="test",
        provider="test",
    )
    llm.budget = None
    return llm


@pytest.fixture
def mock_brave():
    brave = AsyncMock()
    brave.search.return_value = BraveSearchResponse(
        query="test topic",
        results=[
            SearchResult(title="Source A", url="https://a.com", description="Info about A"),
            SearchResult(title="Source B", url="https://b.com", description="Info about B"),
        ],
    )
    return brave


@pytest.fixture
def mock_gemini():
    gemini = AsyncMock()
    gemini.grounded_search.return_value = LLMResponse(
        content="Google says: test topic is relevant.",
        model="gemini",
        provider="gemini",
    )
    return gemini


@pytest.fixture
def mock_scraper():
    scraper = AsyncMock()
    scraper.execute.return_value = "Content from https://a.com:\n\nFull article text here."
    return scraper


class TestResearchEngine:
    async def test_full_pipeline(
        self, mock_llm: AsyncMock, mock_brave: AsyncMock, mock_gemini: AsyncMock, mock_scraper: AsyncMock
    ) -> None:
        engine = ResearchEngine(
            llm=mock_llm,
            brave=mock_brave,
            gemini=mock_gemini,
            scraper=mock_scraper,
        )
        result = await engine.research("test topic")

        assert result.query == "test topic"
        assert result.summary  # Should have LLM summary
        assert len(result.citations.citations) == 2  # Source A and Source B
        mock_brave.search.assert_called_once()
        mock_gemini.grounded_search.assert_called_once()
        assert mock_scraper.execute.call_count <= 3  # max_scrape default

    async def test_brave_only(self, mock_llm: AsyncMock, mock_brave: AsyncMock) -> None:
        engine = ResearchEngine(llm=mock_llm, brave=mock_brave)
        result = await engine.research("test")

        assert len(result.citations.citations) == 2
        assert result.summary

    async def test_no_sources_available(self, mock_llm: AsyncMock) -> None:
        engine = ResearchEngine(llm=mock_llm)
        result = await engine.research("nothing")

        assert "Keine Ergebnisse" in result.summary

    async def test_brave_failure_continues(
        self, mock_llm: AsyncMock, mock_brave: AsyncMock, mock_gemini: AsyncMock
    ) -> None:
        mock_brave.search.side_effect = Exception("API down")

        engine = ResearchEngine(llm=mock_llm, brave=mock_brave, gemini=mock_gemini)
        result = await engine.research("test")

        # Should still have Gemini content
        assert result.summary

    async def test_format_includes_citations(self, mock_llm: AsyncMock, mock_brave: AsyncMock) -> None:
        engine = ResearchEngine(llm=mock_llm, brave=mock_brave)
        result = await engine.research("test")
        formatted = result.format()

        assert "Recherche: test" in formatted
        assert "Zusammenfassung" in formatted  # LLM summary must appear
        assert "Sources:" in formatted
        assert "https://a.com" in formatted
