"""
arXiv API (Atom XML feed). No API key required.
Docs: https://info.arxiv.org/help/api/user-manual.html
"""
import logging
import requests
import xml.etree.ElementTree as ET
from typing import List, Optional
from .base import PaperSearchProvider, PaperResult

logger = logging.getLogger(__name__)
API_URL = "http://export.arxiv.org/api/query"
TIMEOUT = 20
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class ArxivProvider(PaperSearchProvider):
    name = "arxiv"

    def search(self, query: str, year: Optional[int] = None, author: Optional[str] = None, limit: int = 20) -> List[PaperResult]:
        search_query = f"all:{query}"
        if author:
            search_query += f" AND au:{author}"
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": min(limit, 50),
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        try:
            resp = requests.get(API_URL, params=params, timeout=TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("arXiv request failed: %s", exc)
            raise ConnectionError(f"arXiv is unreachable: {exc}") from exc

        if resp.status_code >= 400:
            raise ConnectionError(f"arXiv API error {resp.status_code}")

        root = ET.fromstring(resp.text)
        results = []
        for entry in root.findall("atom:entry", NS):
            title_el = entry.find("atom:title", NS)
            title = (title_el.text or "").strip().replace("\n", " ") if title_el is not None else None
            if not title:
                continue
            published = entry.findtext("atom:published", default="", namespaces=NS)
            year_val = int(published[:4]) if published[:4].isdigit() else None
            if year and year_val and year_val != year:
                continue
            authors = [a.findtext("atom:name", default="", namespaces=NS) for a in entry.findall("atom:author", NS)]
            authors = [a for a in authors if a]
            summary = (entry.findtext("atom:summary", default="", namespaces=NS) or "").strip()
            arxiv_id = entry.findtext("atom:id", default="", namespaces=NS)
            pdf_url = None
            page_url = arxiv_id
            for link in entry.findall("atom:link", NS):
                if link.get("title") == "pdf":
                    pdf_url = link.get("href")
                if link.get("rel") == "alternate":
                    page_url = link.get("href")
            doi = entry.findtext("arxiv:doi", default=None, namespaces=NS)
            results.append(PaperResult(
                title=title,
                authors=authors,
                year=year_val,
                venue="arXiv preprint",
                abstract=summary or None,
                source=self.name,
                source_url=page_url,
                doi=doi,
                external_id=arxiv_id,
                citation_count=None,  # arXiv does not provide citation counts
                pdf_url=pdf_url,
                open_access=True,
                raw={"id": arxiv_id},
            ))
        return results
