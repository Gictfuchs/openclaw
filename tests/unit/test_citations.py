"""Tests for citation tracking."""

from openclaw.research.citations import Citation, CitationCollection


class TestCitationCollection:
    def test_add_citation(self) -> None:
        coll = CitationCollection(query="test")
        idx = coll.add(Citation(url="https://a.com", title="Site A"))
        assert idx == 1
        assert len(coll.citations) == 1

    def test_deduplication_by_url(self) -> None:
        coll = CitationCollection(query="test")
        idx1 = coll.add(Citation(url="https://a.com", title="Site A"))
        idx2 = coll.add(Citation(url="https://a.com", title="Site A again"))
        assert idx1 == 1
        assert idx2 == 1
        assert len(coll.citations) == 1

    def test_multiple_citations(self) -> None:
        coll = CitationCollection(query="test")
        coll.add(Citation(url="https://a.com", title="A"))
        coll.add(Citation(url="https://b.com", title="B"))
        coll.add(Citation(url="https://c.com", title="C"))
        assert len(coll.citations) == 3

    def test_format_all(self) -> None:
        coll = CitationCollection(query="test")
        coll.add(Citation(url="https://a.com", title="Site A"))
        coll.add(Citation(url="https://b.com", title="Site B"))
        formatted = coll.format_all()
        assert "Sources:" in formatted
        assert "[1] Site A - https://a.com" in formatted
        assert "[2] Site B - https://b.com" in formatted

    def test_format_all_empty(self) -> None:
        coll = CitationCollection(query="test")
        assert coll.format_all() == "No sources."
