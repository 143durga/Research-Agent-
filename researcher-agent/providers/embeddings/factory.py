import os
from .openai_embeddings import OpenAIEmbeddingProvider
from .local_hash_embeddings import LocalHashEmbeddingProvider

_PROVIDERS = {
    "openai": OpenAIEmbeddingProvider,
    "local_hash": LocalHashEmbeddingProvider,
}


def get_embedding_provider():
    """Selects EMBEDDING_PROVIDER from env. Defaults to 'openai', but if that
    provider has no API key configured, falls back to the local offline
    provider so ingestion still works end-to-end (clearly labeled, never
    silently pretending to be a real embedding model)."""
    provider_name = os.environ.get("EMBEDDING_PROVIDER", "openai").lower()
    cls = _PROVIDERS.get(provider_name, OpenAIEmbeddingProvider)
    provider = cls()
    if not provider.is_configured():
        return LocalHashEmbeddingProvider()
    return provider
