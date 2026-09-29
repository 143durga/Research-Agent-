"""
CitationVerifier: a deterministic (non-LLM) capability that checks whether a
paper referenced anywhere in the app (analysis, comparison, gaps, questions)
actually corresponds to a stored paper record with real source metadata. This
is the guardrail that prevents an LLM hallucination like "Smith et al. 2023"
from silently being treated as a real citation.
"""
from typing import List, Dict
from db.database import db_cursor


def verify_paper_ids(paper_ids: List[int]) -> Dict[int, Dict]:
    """Returns {paper_id: {"exists": bool, "title": ..., "doi": ..., "source": ...}}
    for each id. Any id not found in the database is flagged exists=False so the
    caller can strip/flag it rather than display it as a real citation."""
    if not paper_ids:
        return {}
    placeholders = ",".join("?" for _ in paper_ids)
    with db_cursor() as cur:
        cur.execute(f"SELECT id, title, doi, source, source_url FROM papers WHERE id IN ({placeholders})", paper_ids)
        found = {row["id"]: dict(row) for row in cur.fetchall()}

    result = {}
    for pid in paper_ids:
        if pid in found:
            result[pid] = {"exists": True, **found[pid]}
        else:
            result[pid] = {"exists": False}
    return result


def verify_citation_record(paper_id: int) -> List[Dict]:
    """Returns the stored citation/source records for a paper (its provenance chain)."""
    with db_cursor() as cur:
        cur.execute("SELECT * FROM citations WHERE paper_id = ? ORDER BY created_at", (paper_id,))
        return [dict(r) for r in cur.fetchall()]
