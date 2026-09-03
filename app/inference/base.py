"""
LLM provider interface.
All LLM backends must implement this protocol.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    finish_reason: str = "stop"


class LLMProvider(ABC):
    """
    Abstract base for LLM inference backends.
    Implementations: LlamaCppProvider, VLLMProvider.
    """

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        """
        Send a chat completion request.

        Args:
            system_prompt: The system / instruction prompt.
            user_message: The user message (incident context injected here).
            max_tokens: Override default max tokens.
            temperature: Override default temperature.

        Returns:
            LLMResponse with generated content and token counts.
        """
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier string."""
        ...
