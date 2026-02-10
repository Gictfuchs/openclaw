"""Google Gemini LLM implementation."""

import structlog
from google import genai
from google.genai import types

from openclaw.llm.base import BaseLLM, LLMResponse, TokenUsage

logger = structlog.get_logger()


class GeminiLLM(BaseLLM):
    """Gemini for Google Grounded Search and as Claude fallback."""

    provider_name = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-2.5-flash") -> None:
        self.client = genai.Client(api_key=api_key)
        self.model = model

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        # Convert messages to Gemini format
        contents = []
        for msg in messages:
            role = "user" if msg["role"] == "user" else "model"
            content = msg.get("content", "")
            if isinstance(content, str):
                contents.append(types.Content(role=role, parts=[types.Part(text=content)]))

        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        if system:
            config.system_instruction = system

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=contents,
            config=config,
        )

        content_text = ""
        if response.text:
            content_text = response.text

        usage = TokenUsage()
        if response.usage_metadata:
            usage = TokenUsage(
                input_tokens=response.usage_metadata.prompt_token_count or 0,
                output_tokens=response.usage_metadata.candidates_token_count or 0,
            )

        return LLMResponse(
            content=content_text,
            usage=usage,
            stop_reason="end_turn",
            raw=response,
            model=self.model,
            provider=self.provider_name,
        )

    async def grounded_search(self, query: str) -> LLMResponse:
        """Use Gemini with Google Search grounding for web-augmented answers."""
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())],
        )

        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=query,
            config=config,
        )

        content_text = ""
        if response.text:
            content_text = response.text

        return LLMResponse(
            content=content_text,
            stop_reason="end_turn",
            raw=response,
            model=self.model,
            provider=f"{self.provider_name}+google_search",
        )

    async def is_available(self) -> bool:
        try:
            await self.client.aio.models.generate_content(
                model=self.model,
                contents="ping",
                config=types.GenerateContentConfig(max_output_tokens=10),
            )
            return True
        except Exception:
            return False
