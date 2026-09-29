"""
Anthropic provider. Uses the plain /v1/messages REST endpoint via `requests`
so the app has no hard dependency on the anthropic SDK being installed.

Required env vars:
  LLM_API_KEY      - Anthropic API key (never sent to the frontend)
  LLM_MODEL        - e.g. "claude-sonnet-4-6" (defaults below)
"""
import os
import requests
from .base import LLMProvider, LLMResponse, LLMUnavailableError

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-4-6"
REQUEST_TIMEOUT_SECONDS = 60


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self):
        self.api_key = os.environ.get("LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        self.model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, prompt: str, max_tokens: int = 1500, temperature: float = 0.2) -> LLMResponse:
        if not self.is_configured():
            raise LLMUnavailableError(
                "No LLM provider is configured. Set LLM_API_KEY (Anthropic) in your .env file."
            )
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
        }
        try:
            resp = requests.post(ANTHROPIC_API_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise LLMUnavailableError(f"Could not reach Anthropic API: {exc}") from exc

        if resp.status_code == 429:
            raise LLMUnavailableError("Anthropic API rate limit reached. Please retry shortly.")
        if resp.status_code == 401:
            raise LLMUnavailableError("Anthropic API rejected the API key (401 Unauthorized).")
        if resp.status_code >= 400:
            raise LLMUnavailableError(f"Anthropic API error {resp.status_code}: {resp.text[:500]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise LLMUnavailableError("Anthropic API returned a non-JSON response.") from exc
        text_parts = [block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"]
        text = "\n".join(p for p in text_parts if p)
        if not text:
            raise LLMUnavailableError("Anthropic API returned an empty response.")

        return LLMResponse(text=text, model=self.model, provider=self.name, raw=data)
