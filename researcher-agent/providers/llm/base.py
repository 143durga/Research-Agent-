"""
LLMProvider interface. Every concrete provider (Anthropic, OpenAI, ...) implements
this contract so the rest of the app never depends on a specific vendor's SDK
or request/response shape.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class LLMUnavailableError(Exception):
    """Raised when no LLM provider is configured, or the provider call fails."""


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str
    raw: Optional[dict] = None


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    def complete(self, system: str, prompt: str, max_tokens: int = 1500, temperature: float = 0.2) -> LLMResponse:
        """Send a single-turn (system + user) completion request and return the text response.

        Implementations MUST raise LLMUnavailableError (not return fabricated text) if the
        provider is unreachable, unauthenticated, or rate-limited, so callers can surface an
        honest error instead of silently degrading into fake content.
        """
        raise NotImplementedError

    def is_configured(self) -> bool:
        return True
