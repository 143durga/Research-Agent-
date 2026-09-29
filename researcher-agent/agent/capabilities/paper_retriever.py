"""
PaperRetriever: the RAG retrieval capability. Loads chunk embeddings for one or
more papers and ranks them by cosine similarity to a query embedding.

This is a lightweight, in-process vector store (numpy cosine similarity over
rows pulled from SQLite) rather than a dedicated vector database - appropriate
for a personal research library's scale, and documented as such in
docs/ARCHITECTURE.md. Swapping in a real vector DB later only requires
reimplementing this module's `retrieve()` function.
"""
import json
from typing import List, Dict, Optional
import numpy as np

from db.database import db_cursor
from providers.embeddings.factory import get_embedding_provider
from providers.embeddings.base import EmbeddingUnavailableError


class RetrievalUnavailableError(Exception):
    pass


def retrieval_mode() -> dict:
    """Which retrieval mode is active right now (surfaced in Settings and chat responses)."""
    prov = get_embedding_provider()
    lexical = prov.name == "local_hash"
    return {"mode": "lexical_fallback" if lexical else "semantic", "provider": prov.name,
            "model": getattr(prov, "model", None),
            "description": ("Offline lexical hashing (keyword overlap, NOT semantic similarity)" if lexical
                            else "Semantic embeddings via a remote embedding model")}


def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return 0.0
    return float(np.dot(a, b) / denom)


def retrieve(query: str, paper_ids: List[int], top_k: int = 6) -> List[Dict]:
    """Returns the top_k most relevant chunks across the given papers, each with
    paper_id, section, page and content, sorted by similarity descending.
    Raises RetrievalUnavailableError if no chunk in scope has an embedding
    (e.g. ingestion hasn't completed), so callers can say so rather than
    silently returning nothing and letting the LLM guess."""
    if not paper_ids:
        return []

    placeholders = ",".join("?" for _ in paper_ids)
    with db_cursor() as cur:
        cur.execute(
            f"""SELECT id, paper_id, section_name, page, content, embedding_json, embedding_provider
                FROM paper_chunks WHERE paper_id IN ({placeholders}) AND embedding_json IS NOT NULL""",
            paper_ids,
        )
        rows = [dict(r) for r in cur.fetchall()]

    if not rows:
        raise RetrievalUnavailableError(
            "No embedded content is available for the selected paper(s) yet. "
            "Import/ingest the PDF first so it can be chunked and embedded."
        )

    embedding_provider = get_embedding_provider()
    try:
        query_vec = np.array(embedding_provider.embed([query])[0])
    except EmbeddingUnavailableError as exc:
        raise RetrievalUnavailableError(str(exc)) from exc

    scored, skipped = [], 0
    for row in rows:
        vec = np.array(json.loads(row["embedding_json"]))
        if vec.shape != query_vec.shape:
            skipped += 1  # embedded with a different provider/dimension: not comparable
            continue
        scored.append((_cosine_sim(query_vec, vec), row))
    if not scored:
        raise RetrievalUnavailableError(
            "This paper's stored vectors were created with a different embedding provider/model than the one "
            "now configured, so they cannot be compared. Re-embed the paper (POST /api/papers/<id>/reembed).")

    scored.sort(key=lambda t: t[0], reverse=True)
    top = scored[:top_k]
    return [
        {
            "chunk_id": row["id"],
            "paper_id": row["paper_id"],
            "section": row["section_name"],
            "page": row["page"],
            "content": row["content"],
            "score": round(score, 4),
        }
        for score, row in top
    ]
