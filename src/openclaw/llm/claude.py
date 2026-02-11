"""Anthropic Claude LLM implementation."""

import structlog
from anthropic import AsyncAnthropic

from openclaw.llm.base import BaseLLM, LLMResponse, TokenUsage, ToolCall

logger = structlog.get_logger()


class ClaudeLLM(BaseLLM):
    """Claude API for complex reasoning, tool use, and multi-step planning."""

    provider_name = "claude"

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5-20250929") -> None:
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
        if system:
            kwargs["system"] = system

        response = await self.client.messages.create(**kwargs)
        return self._parse_response(response)

    def _parse_response(self, response) -> LLMResponse:  # type: ignore[no-untyped-def]
        content = ""
        tool_calls: list[ToolCall] = []

        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(
                        id=block.id,
                        name=block.name,
                        input=block.input,
                    )
                )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            stop_reason=response.stop_reason,
            raw=response,
            model=self.model,
            provider=self.provider_name,
        )

    async def is_available(self) -> bool:
        try:
            await self.client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            return False

    async def close(self) -> None:
        await self.client.close()
