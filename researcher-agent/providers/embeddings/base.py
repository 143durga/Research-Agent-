from abc import ABC, abstractmethod
from typing import List


class EmbeddingUnavailableError(Exception):
    pass


class EmbeddingProvider(ABC):
    name: str = "base"
    dimension: int = 0

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """Return one embedding vector per input text, same order."""
        raise NotImplementedError

    def is_configured(self) -> bool:
        return True
