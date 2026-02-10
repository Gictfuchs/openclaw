"""Citation tracking for research results."""

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Citation:
    """A single source citation."""

    url: str
    title: str
    snippet: str = ""
    source_type: str = "web"  # web, news, google, x, scrape
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def format(self, index: int) -> str:
        """Format as a numbered citation."""
        return f"[{index}] {self.title} - {self.url}"


@dataclass
class CitationCollection:
    """Collection of citations for a research task."""

    query: str
    citations: list[Citation] = field(default_factory=list)

    def add(self, citation: Citation) -> int:
        """Add a citation and return its index (1-based)."""
        # Deduplicate by URL
        for i, existing in enumerate(self.citations):
            if existing.url == citation.url:
                return i + 1
        self.citations.append(citation)
        return len(self.citations)

    def format_all(self) -> str:
        """Format all citations as a numbered list."""
        if not self.citations:
            return "No sources."
        lines = ["Sources:"]
        for i, c in enumerate(self.citations, 1):
            lines.append(c.format(i))
        return "\n".join(lines)
