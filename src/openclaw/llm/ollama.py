"""Ollama local LLM implementation for routine tasks."""

from uuid import uuid4

import httpx
import structlog

from openclaw.llm.base import BaseLLM, LLMResponse, TokenUsage, ToolCall

logger = structlog.get_logger()


class OllamaLLM(BaseLLM):
    """Local Ollama models for classification, summarization, embeddings."""

    provider_name = "ollama"

    def __init__(self, host: str = "http://localhost:11434", model: str = "llama3.1:8b") -> None:
        self.host = host.rstrip("/")
        self.model = model
        self.client = httpx.AsyncClient(base_url=self.host, timeout=120.0)

    async def generate(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.7,
    ) -> LLMResponse:
        # Build Ollama messages format
        ollama_messages = []
        if system:
            ollama_messages.append({"role": "system", "content": system})

        for msg in messages:
            if isinstance(msg.get("content"), str):
                ollama_messages.append({"role": msg["role"], "content": msg["content"]})
            elif isinstance(msg.get("content"), list):
                # Handle tool results - flatten to text
                text_parts = []
                for part in msg["content"]:
                    if isinstance(part, dict) and part.get("type") == "tool_result":
                        text_parts.append(f"[Tool Result]: {part.get('content', '')}")
                    elif isinstance(part, dict) and part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                if text_parts:
                    ollama_messages.append({"role": msg["role"], "content": "\n".join(text_parts)})

        payload: dict = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }

        # Ollama supports tools natively
        if tools:
            payload["tools"] = tools

        response = await self.client.post("/api/chat", json=payload)
        response.raise_for_status()
        data = response.json()

        return self._parse_response(data)

    def _parse_response(self, data: dict) -> LLMResponse:
        message = data.get("message", {})
        content = message.get("content", "")
        tool_calls: list[ToolCall] = []

        # Parse tool calls if present
        for call in message.get("tool_calls", []):
            func = call.get("function", {})
            tool_calls.append(
                ToolCall(
                    id=str(uuid4()),
                    name=func.get("name", ""),
                    input=func.get("arguments", {}),
                )
            )

        # Estimate token usage from eval_count
        input_tokens = data.get("prompt_eval_count", 0)
        output_tokens = data.get("eval_count", 0)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=TokenUsage(input_tokens=input_tokens, output_tokens=output_tokens),
            stop_reason="end_turn" if not tool_calls else "tool_use",
            raw=data,
            model=self.model,
            provider=self.provider_name,
        )

    async def embed(self, text: str, model: str | None = None) -> list[float]:
        """Generate embeddings using a local model."""
        response = await self.client.post(
            "/api/embed",
            json={
                "model": model or self.model,
                "input": text,
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["embeddings"][0]

    async def is_available(self) -> bool:
        try:
            response = await self.client.get("/api/tags")
            return response.status_code == 200
        except Exception:
            return False

    async def close(self) -> None:
        await self.client.aclose()
