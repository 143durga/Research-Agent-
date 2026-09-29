"""
Full ingestion pipeline: PDF -> text extraction -> section detection -> chunking
-> embeddings -> storage. Also handles paper metadata de-duplication.
"""
import hashlib
import json
import logging
from typing import Optional, Dict, Any

from db.database import db_cursor
from .pdf_extractor import extract_pages, PDFExtractionError
from .section_detector import detect_sections
from .chunker import chunk_sections
from providers.embeddings.factory import get_embedding_provider
from providers.embeddings.base import EmbeddingUnavailableError

logger = logging.getLogger(__name__)


def find_existing_paper(doi: Optional[str] = None, external_id: Optional[str] = None, title: Optional[str] = None) -> Optional[int]:
    """De-duplication: prefer DOI match, then external_id (e.g. arXiv id), then
    an exact case-insensitive title match as a last resort."""
    with db_cursor() as cur:
        if doi:
            cur.execute("SELECT id FROM papers WHERE doi = ?", (doi,))
            row = cur.fetchone()
            if row:
                return row["id"]
        if external_id:
            cur.execute("SELECT id FROM papers WHERE external_id = ?", (external_id,))
            row = cur.fetchone()
            if row:
                return row["id"]
        if title:
            cur.execute("SELECT id FROM papers WHERE lower(trim(title)) = lower(trim(?))", (title,))
            row = cur.fetchone()
            if row:
                return row["id"]
    return None


def upsert_paper_metadata(paper: Dict[str, Any]) -> int:
    """Insert a paper if it doesn't already exist (by DOI/external_id/title);
    otherwise return the existing paper's id. Never creates duplicate rows for
    the same underlying paper."""
    existing_id = find_existing_paper(paper.get("doi"), paper.get("external_id"), paper.get("title"))
    if existing_id:
        return existing_id

    with db_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO papers (doi, external_id, title, abstract, year, venue, source, source_url,
                                     pdf_url, citation_count, open_access, keywords, raw_metadata_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                paper.get("doi"), paper.get("external_id"), paper["title"], paper.get("abstract"),
                paper.get("year"), paper.get("venue"), paper.get("source"), paper.get("source_url"),
                paper.get("pdf_url"), paper.get("citation_count"), int(bool(paper.get("open_access"))),
                json.dumps(paper.get("keywords") or []), json.dumps(paper.get("raw") or {}),
            ),
        )
        paper_id = cur.lastrowid

        for position, author_name in enumerate(paper.get("authors") or []):
            cur.execute("INSERT OR IGNORE INTO authors (name) VALUES (?)", (author_name,))
            cur.execute("SELECT id FROM authors WHERE name = ?", (author_name,))
            author_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT OR IGNORE INTO paper_authors (paper_id, author_id, position) VALUES (?, ?, ?)",
                (paper_id, author_id, position),
            )

        if paper.get("doi") or paper.get("source_url"):
            cur.execute(
                """INSERT INTO citations (paper_id, source_type, source_url, title, authors, publication, year, doi)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    paper_id, paper.get("source"), paper.get("source_url"), paper["title"],
                    ", ".join(paper.get("authors") or []), paper.get("venue"), paper.get("year"), paper.get("doi"),
                ),
            )
    return paper_id


def ingest_pdf_for_paper(paper_id: int, pdf_path: str) -> Dict[str, Any]:
    """Runs extraction -> sectioning -> chunking -> embedding for an uploaded/downloaded
    PDF and persists everything against the given paper_id. Returns a summary dict.
    Raises on unrecoverable extraction failure (caller should surface the error to the user,
    not fabricate paper content)."""
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE papers SET ingestion_status = 'extracting', pdf_path = ? WHERE id = ?", (pdf_path, paper_id))

    try:
        pages = extract_pages(pdf_path)
    except PDFExtractionError as exc:
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE papers SET ingestion_status = 'failed', ingestion_error = ? WHERE id = ?", (str(exc), paper_id))
        raise

    if not any(p["text"].strip() for p in pages):
        msg = ("No extractable text was found in this PDF. It is probably a scanned image without a "
               "text layer (OCR is not supported).")
        with db_cursor(commit=True) as cur:
            cur.execute("UPDATE papers SET ingestion_status = 'failed', ingestion_error = ? WHERE id = ?", (msg, paper_id))
        raise PDFExtractionError(msg)

    sections = detect_sections(pages)
    chunks = chunk_sections(sections)
    for c in chunks:
        c["content_hash"] = hashlib.sha256(c["content"].encode("utf-8")).hexdigest()

    embedding_provider = get_embedding_provider()
    provider_model = getattr(embedding_provider, "model", embedding_provider.name)
    embedding_error = None
    vectors = [None] * len(chunks)
    reused = 0
    if chunks:
        # Reuse existing vectors for identical chunk text (same provider+model): no repeated API calls.
        with db_cursor() as cur:
            cur.execute(
                "SELECT content_hash, embedding_json FROM paper_chunks WHERE embedding_json IS NOT NULL "
                "AND embedding_provider = ? AND embedding_model = ? AND content_hash IS NOT NULL",
                (embedding_provider.name, provider_model),
            )
            cache = {}
            for r in cur.fetchall():
                cache.setdefault(r["content_hash"], r["embedding_json"])
        todo = []
        for i, c in enumerate(chunks):
            hit = cache.get(c["content_hash"])
            if hit:
                vectors[i] = json.loads(hit)
                reused += 1
            else:
                todo.append(i)
        if todo:
            try:
                new_vecs = embedding_provider.embed([chunks[i]["content"] for i in todo])
                if len(new_vecs) != len(todo):
                    raise EmbeddingUnavailableError("Embedding provider returned the wrong number of vectors.")
                for i, v in zip(todo, new_vecs):
                    vectors[i] = v
            except EmbeddingUnavailableError as exc:
                embedding_error = str(exc)

    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM paper_sections WHERE paper_id = ?", (paper_id,))
        cur.execute("DELETE FROM paper_chunks WHERE paper_id = ?", (paper_id,))

        for s in sections:
            cur.execute(
                """INSERT INTO paper_sections (paper_id, section_name, content, page_start, page_end, order_index)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (paper_id, s["section_name"], s["content"].strip(), s.get("page_start"), s.get("page_end"), s.get("order_index", 0)),
            )

        for chunk, vector in zip(chunks, vectors):
            cur.execute(
                """INSERT INTO paper_chunks (paper_id, section_name, page, chunk_index, content, token_count,
                                               embedding_json, embedding_provider, embedding_model, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    paper_id, chunk["section_name"], chunk.get("page"), chunk["chunk_index"], chunk["content"],
                    chunk["token_count"], json.dumps(vector) if vector else None,
                    embedding_provider.name if vector else None,
                    provider_model if vector else None,
                    chunk["content_hash"],
                ),
            )

        # 'chunked' = text + embeddings usable for retrieval; 'text_only' = text extracted but some
        # vectors are missing (embedding failure) so chat retrieval is incomplete until re-embedded.
        status = "text_only" if (embedding_error or any(v is None for v in vectors)) else "chunked"
        cur.execute(
            "UPDATE papers SET ingestion_status = ?, full_text_extracted = 1, ingestion_error = ?, updated_at = datetime('now') WHERE id = ?",
            (status, embedding_error, paper_id),
        )

    return {
        "pages": len(pages),
        "sections_found": len(sections),
        "chunks_created": len(chunks),
        "embedding_provider": embedding_provider.name,
        "embeddings_reused": reused,
        "embedding_error": embedding_error,
    }


def reembed_paper(paper_id: int) -> Dict[str, Any]:
    """Recompute embeddings for an already-ingested paper with the CURRENTLY configured provider
    (needed after switching between the lexical fallback and a semantic embedding model)."""
    with db_cursor() as cur:
        cur.execute("SELECT id, content FROM paper_chunks WHERE paper_id = ? ORDER BY chunk_index", (paper_id,))
        rows = [dict(r) for r in cur.fetchall()]
    if not rows:
        raise EmbeddingUnavailableError("This paper has no chunks yet - import its PDF first.")
    provider = get_embedding_provider()
    vectors = provider.embed([r["content"] for r in rows])
    if len(vectors) != len(rows):
        raise EmbeddingUnavailableError("Embedding provider returned the wrong number of vectors.")
    model = getattr(provider, "model", provider.name)
    with db_cursor(commit=True) as cur:
        for r, v in zip(rows, vectors):
            cur.execute("UPDATE paper_chunks SET embedding_json = ?, embedding_provider = ?, embedding_model = ? WHERE id = ?",
                        (json.dumps(v), provider.name, model, r["id"]))
        cur.execute("UPDATE papers SET ingestion_status = 'chunked', ingestion_error = NULL WHERE id = ?", (paper_id,))
    return {"chunks": len(rows), "embedding_provider": provider.name}
