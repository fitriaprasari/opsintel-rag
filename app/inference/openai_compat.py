"""
OpenAI-compatible LLM provider.
Works with both llama.cpp (--server mode) and vLLM, both of which expose
the OpenAI /v1/chat/completions API.

Configuration:
  LLM_PROVIDER=llamacpp  →  LLM_BASE_URL=http://llamacpp:8080/v1
  LLM_PROVIDER=vllm      →  LLM_BASE_URL=http://vllm:8000/v1
"""
from __future__ import annotations

import json
import logging
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import get_settings
from app.inference.base import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(LLMProvider):
    """
    Shared implementation for any OpenAI-compatible /v1/chat/completions endpoint.
    Used by both LlamaCppProvider and VLLMProvider aliases.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model_name: str,
        max_tokens: int,
        temperature: float,
        timeout: int,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model_name = model_name
        self._default_max_tokens = max_tokens
        self._default_temperature = temperature
        self._timeout = timeout

    @property
    def model_name(self) -> str:
        return self._model_name

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        reraise=True,
    )
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self._model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": max_tokens or self._default_max_tokens,
            "temperature": temperature if temperature is not None else self._default_temperature,
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        url = f"{self._base_url}/chat/completions"

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            logger.debug("LLM request to %s (model=%s)", url, self._model_name)
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()

        data = response.json()
        choice = data["choices"][0]
        usage = data.get("usage", {})
        content = choice["message"]["content"]

        return LLMResponse(
            content=content,
            model=data.get("model", self._model_name),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
            finish_reason=choice.get("finish_reason", "stop"),
        )


# ── Named aliases for clarity ─────────────────────────────────────────────────

class LlamaCppProvider(OpenAICompatibleProvider):
    """llama.cpp server — local OpenAI-compatible endpoint."""
    pass


class VLLMProvider(OpenAICompatibleProvider):
    """vLLM server — high-throughput GPU inference endpoint."""
    pass


# ── Factory ───────────────────────────────────────────────────────────────────

def get_llm_provider() -> LLMProvider:
    """
    Return the configured LLM provider.
    Switched via LLM_PROVIDER env var: mock | llamacpp | vllm

    mock     → instant canned response, no LLM server needed (default for dev)
    llamacpp → local llama.cpp server (OpenAI-compatible)
    vllm     → vLLM GPU inference server (OpenAI-compatible)
    """
    s = get_settings()
    if s.llm_provider == "mock":
        from app.inference.mock import MockLLMProvider  # noqa: PLC0415
        return MockLLMProvider()
    kwargs = {
        "base_url": s.llm_base_url,
        "api_key": s.llm_api_key,
        "model_name": s.llm_model_name,
        "max_tokens": s.llm_max_tokens,
        "temperature": s.llm_temperature,
        "timeout": s.llm_timeout_seconds,
    }
    if s.llm_provider == "llamacpp":
        return LlamaCppProvider(**kwargs)
    if s.llm_provider == "vllm":
        return VLLMProvider(**kwargs)
    raise ValueError(f"Unknown LLM_PROVIDER: {s.llm_provider!r}")
