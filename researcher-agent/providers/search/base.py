from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PaperResult:
    """Normalized search result. Any field the source did not provide stays
    None/empty - we never invent metadata to fill gaps."""
    title: str
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    abstract: Optional[str] = None
    source: str = ""
    source_url: Optional[str] = None
    doi: Optional[str] = None
    external_id: Optional[str] = None
    citation_count: Optional[int] = None
    pdf_url: Optional[str] = None
    open_access: bool = False
    raw: Optional[dict] = None


class PaperSearchProvider(ABC):
    name: str = "base"

    @abstractmethod
    def search(self, query: str, year: Optional[int] = None, author: Optional[str] = None, limit: int = 20) -> List[PaperResult]:
        raise NotImplementedError
