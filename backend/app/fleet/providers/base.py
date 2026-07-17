"""LLMProvider ABC — provider-agnostic interface used by model_router."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMResponse:
    content: str
    tokens_in: int
    tokens_out: int
    model: str
    stop_reason: str


class LLMProvider(ABC):
    """Provider-agnostic LLM call interface."""

    @abstractmethod
    def supports(self, provider_name: str) -> bool:
        """Return True if this provider handles provider_name."""
        ...

    @abstractmethod
    def call(
        self,
        model: str,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
        temperature: float,
        **kwargs: Any,
    ) -> LLMResponse:
        """Synchronous LLM call. Returns LLMResponse."""
        ...
