"""
Local, offline embedding fallback.

This is NOT a semantic embedding model - it is a deterministic TF-IDF-weighted
hashing vectorizer that runs fully offline with no API key. It exists so paper
chunking/retrieval still works for local testing when no embedding API key is
configured, and it is clearly labeled as such everywhere it is used (stored as
embedding_provider = "local_hash" in paper_chunks, and surfaced in Settings).

Retrieval quality is meaningfully lower than a real embedding model - it is a
lexical-overlap approximation, not true semantic similarity. Configure
EMBEDDING_API_KEY for production-quality retrieval.
"""
from typing import List
import numpy as np
from sklearn.feature_extraction.text import HashingVectorizer
from .base import EmbeddingProvider

DIMENSION = 512


class LocalHashEmbeddingProvider(EmbeddingProvider):
    name = "local_hash"
    dimension = DIMENSION

    def __init__(self):
        self._vectorizer = HashingVectorizer(
            n_features=DIMENSION, alternate_sign=False, norm="l2", stop_words="english"
        )

    def is_configured(self) -> bool:
        return True  # always available, no network/key required

    def embed(self, texts: List[str]) -> List[List[float]]:
        matrix = self._vectorizer.transform(texts)
        dense = matrix.toarray().astype(np.float64)
        return [row.tolist() for row in dense]
