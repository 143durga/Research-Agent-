"""
PaperSearchProvider aggregator ("PaperSearcher" agent capability's data layer).
Fans a query out to every enabled source, tags each result with any partial
failures so the UI can be honest about which sources actually answered.
"""
import logging
from typing import List, Optional
from .semantic_scholar import SemanticScholarProvider
from .crossref import CrossrefProvider
from .arxiv import ArxivProvider

logger = logging.getLogger(__name__)

ALL_PROVIDERS = {
    "semantic_scholar": SemanticScholarProvider,
    "crossref": CrossrefProvider,
    "arxiv": ArxivProvider,
}


def search_all(query: str, sources: Optional[List[str]] = None, year: Optional[int] = None,
                author: Optional[str] = None, limit_per_source: int = 15):
    """Returns (results, errors). `errors` maps source name -> error message for any
    source that failed, so the caller can show 'X was unavailable' rather than
    silently dropping results or pretending everything succeeded."""
    sources = sources or list(ALL_PROVIDERS.keys())
    results = []
    errors = {}
    for source_name in sources:
        provider_cls = ALL_PROVIDERS.get(source_name)
        if not provider_cls:
            continue
        try:
            provider = provider_cls()
            source_results = provider.search(query=query, year=year, author=author, limit=limit_per_source)
            results.extend(source_results)
        except Exception as exc:  # noqa: BLE001 - we want to isolate one source's failure from the rest
            logger.warning("Search provider %s failed: %s", source_name, exc)
            errors[source_name] = str(exc)
    return results, errors
