"""
Semantic Scholar Academic Graph API.
Docs: https://api.semanticscholar.org/api-docs/graph
No API key strictly required (public rate limits apply); an optional
SEMANTIC_SCHOLAR_API_KEY raises those limits.
"""
import os
import logging
import requests
from typing import List, Optional
from .base import PaperSearchProvider, PaperResult

logger = logging.getLogger(__name__)
API_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
FIELDS = "title,authors,year,venue,abstract,externalIds,citationCount,openAccessPdf,url"
TIMEOUT = 20


class SemanticScholarProvider(PaperSearchProvider):
    name = "semantic_scholar"

    def __init__(self):
        self.api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")

    def search(self, query: str, year: Optional[int] = None, author: Optional[str] = None, limit: int = 20) -> List[PaperResult]:
        params = {"query": query, "limit": min(limit, 100), "fields": FIELDS}
        if year:
            params["year"] = str(year)
        headers = {"x-api-key": self.api_key} if self.api_key else {}
        try:
            resp = requests.get(API_URL, params=params, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("Semantic Scholar request failed: %s", exc)
            raise ConnectionError(f"Semantic Scholar is unreachable: {exc}") from exc

        if resp.status_code == 429:
            raise ConnectionError("Semantic Scholar rate limit reached. Try again shortly.")
        if resp.status_code >= 400:
            raise ConnectionError(f"Semantic Scholar API error {resp.status_code}")

        data = resp.json()
        results = []
        for item in data.get("data", []):
            authors = [a.get("name") for a in (item.get("authors") or []) if a.get("name")]
            if author and not any(author.lower() in a.lower() for a in authors):
                continue
            oa_pdf = (item.get("openAccessPdf") or {}).get("url")
            external_ids = item.get("externalIds") or {}
            results.append(PaperResult(
                title=item.get("title") or "Untitled",
                authors=authors,
                year=item.get("year"),
                venue=item.get("venue") or None,
                abstract=item.get("abstract"),
                source=self.name,
                source_url=item.get("url"),
                doi=external_ids.get("DOI"),
                external_id=item.get("paperId"),
                citation_count=item.get("citationCount"),
                pdf_url=oa_pdf,
                open_access=bool(oa_pdf),
                raw=item,
            ))
        return results
