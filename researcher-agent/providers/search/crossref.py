"""
Crossref REST API (works search). No API key required.
Docs: https://api.crossref.org/swagger-ui/index.html
"""
import os
import logging
import re
import requests
from typing import List, Optional
from .base import PaperSearchProvider, PaperResult

logger = logging.getLogger(__name__)
API_URL = "https://api.crossref.org/works"
TIMEOUT = 20


def _strip_jats(text):
    """Crossref abstracts come as JATS XML (<jats:p>...). Return plain text, or None if empty."""
    if not text:
        return None
    text = re.sub(r"<jats:title>.*?</jats:title>", " ", text, flags=re.I | re.S)  # drop the "Abstract" heading only
    plain = re.sub(r"<[^>]+>", " ", text)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain or None


class CrossrefProvider(PaperSearchProvider):
    name = "crossref"

    def __init__(self):
        # Crossref's "polite pool" wants a contact email in the User-Agent for better reliability.
        self.contact_email = os.environ.get("CROSSREF_CONTACT_EMAIL", "")

    def search(self, query: str, year: Optional[int] = None, author: Optional[str] = None, limit: int = 20) -> List[PaperResult]:
        params = {"query.bibliographic": query, "rows": min(limit, 50)}
        if author:
            params["query.author"] = author
        if year:
            params["filter"] = f"from-pub-date:{year}-01-01,until-pub-date:{year}-12-31"
        ua = "ResearcherAgent/1.0"
        if self.contact_email:
            ua += f" (mailto:{self.contact_email})"
        headers = {"User-Agent": ua}
        try:
            resp = requests.get(API_URL, params=params, headers=headers, timeout=TIMEOUT)
        except requests.RequestException as exc:
            logger.warning("Crossref request failed: %s", exc)
            raise ConnectionError(f"Crossref is unreachable: {exc}") from exc

        if resp.status_code == 429:
            raise ConnectionError("Crossref rate limit reached. Try again shortly.")
        if resp.status_code >= 400:
            raise ConnectionError(f"Crossref API error {resp.status_code}")

        data = resp.json()
        items = (data.get("message") or {}).get("items", [])
        results = []
        for item in items:
            title_list = item.get("title") or []
            title = title_list[0] if title_list else None
            if not title:
                continue
            authors = []
            for a in item.get("author", []) or []:
                given = a.get("given", "")
                family = a.get("family", "")
                full = f"{given} {family}".strip()
                if full:
                    authors.append(full)
            year_val = None
            date_parts = (item.get("published") or item.get("published-print") or item.get("published-online") or {}).get("date-parts")
            if date_parts and date_parts[0]:
                year_val = date_parts[0][0]
            results.append(PaperResult(
                title=title,
                authors=authors,
                year=year_val,
                venue=(item.get("container-title") or [None])[0],
                abstract=_strip_jats(item.get("abstract")),  # often absent; never invented
                source=self.name,
                source_url=item.get("URL"),
                doi=item.get("DOI"),
                external_id=item.get("DOI"),
                citation_count=item.get("is-referenced-by-count"),
                pdf_url=None,
                open_access=False,
                raw=item,
            ))
        return results
