"""Smart LLM router - routes requests to the optimal provider."""

from enum import Enum
from typing import Any

import structlog

from openclaw.llm.base import BaseLLM, LLMResponse

logger = structlog.get_logger()


class TaskComplexity(Enum):
    """Task complexity determines which LLM to use."""

    TRIVIAL = "trivial"      # Classification, filtering → Ollama fast
    SIMPLE = "simple"        # Summarization, simple Q&A → Ollama default
    COMPLEX = "complex"      # Reasoning, planning, tool use → Claude
    WEB_SEARCH = "web_search"  # Google grounded search → Gemini
    SOCIAL = "social"        # X/Twitter analysis → Grok


class LLMRouter:
    """Routes LLM requests to the optimal provider based on task type.

    Routing strategy:
    - TRIVIAL/SIMPLE → Ollama (local, free)
    - COMPLEX/tool_use → Claude (primary API)
    - WEB_SEARCH → Gemini (Google Grounding)
    - SOCIAL → Grok (X/Twitter)
    - Fallback chain: Claude → Gemini → Ollama
    """

    def __init__(
        self,
        claude: BaseLLM | None = None,
        ollama: BaseLLM | None = None,
        gemini: BaseLLM | None = None,
        grok: BaseLLM | None = None,
    ) -> None:
        self.claude = claude
        self.ollama = ollama
        self.gemini = gemini
        self.grok = grok
        self._provider_map = {
            "claude": claude,
            "ollama": ollama,
            "gemini": gemini,
            "grok": grok,
        }

    async def generate(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        complexity: TaskComplexity = TaskComplexity.COMPLEX,
        preferred_provider: str | None = None,
    ) -> LLMResponse:
        """Route a request to the best available LLM."""
        provider = self._select_provider(complexity, tools, preferred_provider)

        if provider is None:
            raise RuntimeError("No LLM provider available")

        try:
            response = await provider.generate(
                messages=messages,
                tools=tools,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            logger.info(
                "llm_response",
                provider=provider.provider_name,
                complexity=complexity.value,
                tokens=response.usage.total_tokens if response.usage else 0,
            )
            return response

        except Exception as e:
            logger.warning("llm_provider_failed", provider=provider.provider_name, error=str(e))
            # Try fallback chain
            return await self._fallback(
                messages=messages,
                tools=tools,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                failed_provider=provider.provider_name,
            )

    def _select_provider(
        self,
        complexity: TaskComplexity,
        tools: list[dict] | None,
        preferred: str | None,
    ) -> BaseLLM | None:
        """Select the optimal LLM provider."""
        # Explicit provider override
        if preferred and preferred in self._provider_map:
            provider = self._provider_map[preferred]
            if provider is not None:
                return provider

        # Tool use requires Claude (best tool use support)
        if tools:
            return self.claude or self.gemini

        # Route by complexity
        match complexity:
            case TaskComplexity.TRIVIAL:
                return self.ollama or self.claude
            case TaskComplexity.SIMPLE:
                return self.ollama or self.claude
            case TaskComplexity.COMPLEX:
                return self.claude or self.gemini
            case TaskComplexity.WEB_SEARCH:
                return self.gemini or self.claude
            case TaskComplexity.SOCIAL:
                return self.grok or self.claude

        return self.claude or self.ollama

    async def _fallback(
        self,
        messages: list[dict],
        tools: list[dict] | None,
        system: str | None,
        max_tokens: int,
        temperature: float,
        failed_provider: str,
    ) -> LLMResponse:
        """Try fallback providers in order: Claude → Gemini → Ollama."""
        fallback_order = [self.claude, self.gemini, self.ollama]

        for provider in fallback_order:
            if provider is None or provider.provider_name == failed_provider:
                continue
            try:
                logger.info("llm_fallback", provider=provider.provider_name)
                return await provider.generate(
                    messages=messages,
                    tools=tools if provider.provider_name == "claude" else None,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                )
            except Exception as e:
                logger.warning("llm_fallback_failed", provider=provider.provider_name, error=str(e))
                continue

        raise RuntimeError("All LLM providers failed")

    async def check_availability(self) -> dict[str, bool]:
        """Check which providers are available."""
        result = {}
        for name, provider in self._provider_map.items():
            if provider is not None:
                result[name] = await provider.is_available()
            else:
                result[name] = False
        return result
