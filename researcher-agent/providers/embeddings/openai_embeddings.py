"""
OpenAI (or OpenAI-compatible) embeddings provider.

Required env vars:
  EMBEDDING_API_KEY  - falls back to LLM_API_KEY / OPENAI_API_KEY if unset
  EMBEDDING_MODEL    - e.g. "text-embedding-3-small" (default)
  EMBEDDING_BASE_URL - optional, defaults to https://api.openai.com/v1
"""
import os
import requests
from .base import EmbeddingProvider, EmbeddingUnavailableError

DEFAULT_MODEL = "text-embedding-3-small"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
REQUEST_TIMEOUT_SECONDS = 60


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"
    dimension = 1536

    def __init__(self):
        self.api_key = (
            os.environ.get("EMBEDDING_API_KEY")
            or os.environ.get("LLM_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
        )
        self.model = os.environ.get("EMBEDDING_MODEL", DEFAULT_MODEL)
        self.base_url = os.environ.get("EMBEDDING_BASE_URL", DEFAULT_BASE_URL)

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def embed(self, texts):
        if not self.is_configured():
            raise EmbeddingUnavailableError("No embedding API key configured (EMBEDDING_API_KEY).")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {"model": self.model, "input": texts}
        try:
            resp = requests.post(f"{self.base_url}/embeddings", headers=headers, json=payload, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise EmbeddingUnavailableError(f"Could not reach embeddings API: {exc}") from exc
        if resp.status_code == 401:
            raise EmbeddingUnavailableError("Embeddings API rejected the API key (401 Unauthorized).")
        if resp.status_code == 429:
            raise EmbeddingUnavailableError("Embeddings API rate limit reached. Please retry shortly.")
        if resp.status_code >= 400:
            raise EmbeddingUnavailableError(f"Embeddings API error {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise EmbeddingUnavailableError("Embeddings API returned a non-JSON response.") from exc
        try:
            items = sorted(data["data"], key=lambda d: d["index"])
            return [item["embedding"] for item in items]
        except (KeyError, TypeError) as exc:
            raise EmbeddingUnavailableError("Embeddings API returned an unexpected response shape.") from exc
