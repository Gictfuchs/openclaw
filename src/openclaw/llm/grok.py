"""xAI Grok LLM implementation for X/Twitter tasks."""

import httpx
import structlog

from openclaw.llm.base import BaseLLM, LLMResponse, TokenUsage, ToolCall

logger = structlog.get_logger()


class GrokLLM(BaseLLM):
    """Grok for X/Twitter-specific tasks and social media analysis."""

    provider_name = "grok"

    def __init__(self, api_key: str, model: str = "grok-3") -> None:
        self.api_key = api_key
        self.model = model
        # xAI API is OpenAI-compatible
        self.client = httpx.AsyncClient(
            base_url="https://api.x.ai/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        # xAI uses OpenAI-compatible format
        api_messages = []
        if system:
            api_messages.append({"role": "system", "content": system})

        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                api_messages.append({"role": msg["role"], "content": content})

        payload: dict = {
            "model": self.model,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        response = await self.client.post("/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> LLMResponse:
        choice = data.get("choices", [{}])[0]
        message = choice.get("message", {})
        content = message.get("content", "")

        usage_data = data.get("usage", {})
        usage = TokenUsage(
            input_tokens=usage_data.get("prompt_tokens", 0),
            output_tokens=usage_data.get("completion_tokens", 0),
        )

        return LLMResponse(
            content=content,
            usage=usage,
            stop_reason=choice.get("finish_reason", "stop"),
            raw=data,
            model=self.model,
            provider=self.provider_name,
        )

    async def is_available(self) -> bool:
        try:
            response = await self.client.get("/models")
            return response.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self.client.aclose()
