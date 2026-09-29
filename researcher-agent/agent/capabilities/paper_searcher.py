import json
from typing import List, Optional
from db.database import db_cursor, get_default_user_id
from providers.search.aggregator import search_all


def search(query: str, sources: Optional[List[str]] = None, year: Optional[int] = None,
           author: Optional[str] = None, open_access_only: bool = False):
    results, errors = search_all(query=query, sources=sources, year=year, author=author)

    if open_access_only:
        results = [r for r in results if r.open_access]

    # De-duplicate across sources by DOI first, then title, keeping the richest record.
    by_key = {}
    for r in results:
        key = r.doi or r.title.strip().lower()
        if key not in by_key:
            by_key[key] = r
        else:
            existing = by_key[key]
            if (r.abstract and not existing.abstract) or (r.citation_count and not existing.citation_count):
                by_key[key] = r
    deduped = list(by_key.values())
    deduped.sort(key=lambda r: (r.citation_count or 0), reverse=True)

    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO search_history (user_id, query, filters_json, sources_json, result_count) VALUES (?, ?, ?, ?, ?)",
            (
                get_default_user_id(), query,
                json.dumps({"year": year, "author": author, "open_access_only": open_access_only}),
                json.dumps(sources or list(errors.keys()) or ["semantic_scholar", "crossref", "arxiv"]),
                len(deduped),
            ),
        )

    return deduped, errors


def recent_searches(limit: int = 10):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM search_history ORDER BY created_at DESC LIMIT ?", (limit,))
        return [dict(r) for r in cur.fetchall()]
