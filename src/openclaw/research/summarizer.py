"""Summarization of research results via LLM."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from openclaw.llm.router import TaskComplexity

if TYPE_CHECKING:
    from openclaw.llm.base import LLMResponse
    from openclaw.llm.router import LLMRouter
    from openclaw.research.citations import CitationCollection

logger = structlog.get_logger()

_SUMMARIZE_PROMPT = """\
Du bist ein Recherche-Assistent. Fasse die folgenden Recherche-Ergebnisse zu dem Thema "{topic}" zusammen.

Regeln:
- Fasse praegnant und informativ zusammen (max 500 Woerter)
- Nenne die wichtigsten Fakten und Erkenntnisse
- Verwende Quellenverweise im Format [1], [2] etc.
- Wenn sich Quellen widersprechen, erwaehne das
- Antworte in der Sprache der Suchanfrage
- Strukturiere mit Zwischenueberschriften wenn sinnvoll

Quellenverzeichnis:
{citations}

Recherche-Ergebnisse:
{content}
"""


async def summarize_research(
    llm: LLMRouter,
    topic: str,
    content: str,
    citations: CitationCollection,
) -> str:
    """Summarize research content with citations using the LLM.

    Uses Ollama (SIMPLE complexity) for cost efficiency, falls back to Claude.
    """
    prompt = _SUMMARIZE_PROMPT.format(
        topic=topic,
        citations=citations.format_all(),
        content=content[:15_000],  # Cap input to avoid huge token usage
    )

    try:
        response: LLMResponse = await llm.generate(
            messages=[{"role": "user", "content": prompt}],
            complexity=TaskComplexity.SIMPLE,  # Route to Ollama if available
            max_tokens=2048,
            temperature=0.3,
        )
        return response.content
    except Exception as e:
        logger.error("summarize_failed", error=str(e))
        # Return raw content as fallback
        return f"Zusammenfassung fehlgeschlagen. Rohdaten:\n\n{content[:5000]}"
