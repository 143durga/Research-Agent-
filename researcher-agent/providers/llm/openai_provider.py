"""
OpenAI (or any OpenAI-compatible /chat/completions endpoint) provider.
Also works with local OpenAI-compatible servers (e.g. vLLM, Ollama's OpenAI
shim) by overriding LLM_BASE_URL.

Required env vars:
  LLM_API_KEY   - OpenAI-compatible API key
  LLM_MODEL     - e.g. "gpt-4o-mini"
  LLM_BASE_URL  - optional, defaults to https://api.openai.com/v1
"""
import os
import requests
from .base import LLMProvider, LLMResponse, LLMUnavailableError

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
REQUEST_TIMEOUT_SECONDS = 60


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self):
        self.api_key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
        self.base_url = os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def complete(self, system: str, prompt: str, max_tokens: int = 1500, temperature: float = 0.2) -> LLMResponse:
        if not self.is_configured():
            raise LLMUnavailableError(
                "No LLM provider is configured. Set LLM_API_KEY (OpenAI-compatible) in your .env file."
            )
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            resp = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise LLMUnavailableError(f"Could not reach LLM API: {exc}") from exc

        if resp.status_code == 429:
            raise LLMUnavailableError("LLM API rate limit reached. Please retry shortly.")
        if resp.status_code == 401:
            raise LLMUnavailableError("LLM API rejected the API key (401 Unauthorized).")
        if resp.status_code >= 400:
            raise LLMUnavailableError(f"LLM API error {resp.status_code}: {resp.text[:500]}")

        try:
            data = resp.json()
        except ValueError as exc:
            raise LLMUnavailableError("LLM API returned a non-JSON response.") from exc
        try:
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMUnavailableError("LLM API returned an unexpected response shape.") from exc
        if not text:
            raise LLMUnavailableError("LLM API returned an empty response.")

        return LLMResponse(text=text, model=self.model, provider=self.name, raw=data)
