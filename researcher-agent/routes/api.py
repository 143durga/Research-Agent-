import os
import json
import logging
import sqlite3
import uuid
from urllib.parse import urlparse

from flask import Blueprint, request, jsonify, current_app
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from db.database import db_cursor, get_default_user_id
from config import allowed_file
from security import rate_limit, require_api_key
from safe_fetch import fetch_pdf, UnsafeURLError, FetchError
from agent.orchestrator import agent
from agent.capabilities import gap_finder, question_generator, paper_analyzer
from ingestion.pipeline import find_existing_paper, reembed_paper
from providers.llm.base import LLMUnavailableError
from providers.embeddings.base import EmbeddingUnavailableError
from providers.search.aggregator import ALL_PROVIDERS
from agent.capabilities.paper_retriever import RetrievalUnavailableError
from ingestion.pdf_extractor import PDFExtractionError

logger = logging.getLogger(__name__)
api = Blueprint("api", __name__, url_prefix="/api")


def _err(message, status=400):
    return jsonify({"error": message}), status


def _ids(value, minimum=0, maximum=50):
    """Coerce a JSON list into a de-duplicated list of positive ints (rejects anything else)."""
    if value is None:
        value = []
    if not isinstance(value, list):
        raise ValueError("paper_ids must be a list of integers.")
    out = []
    for v in value:
        if isinstance(v, bool) or not isinstance(v, int) or v <= 0:
            raise ValueError("paper_ids must be a list of positive integers.")
        if v not in out:
            out.append(v)
    if len(out) > maximum:
        raise ValueError(f"At most {maximum} papers can be selected.")
    if len(out) < minimum:
        raise ValueError(f"Select at least {minimum} paper(s).")
    return out


def _http_url(value):
    """Only http(s) URLs are ever stored/rendered as links (blocks javascript:, data:, file: ...)."""
    if not value or not isinstance(value, str) or len(value) > 2048:
        return None
    p = urlparse(value.strip())
    return value.strip() if p.scheme in ("http", "https") and p.netloc else None


def _require_paper(paper_id):
    with db_cursor() as cur:
        cur.execute("SELECT 1 FROM papers WHERE id = ?", (paper_id,))
        return cur.fetchone() is not None


# ---------- error mapping (never leak stack traces, never fabricate content) ----------
@api.errorhandler(LLMUnavailableError)
def handle_llm_unavailable(e):
    return _err(str(e), 503)


@api.errorhandler(EmbeddingUnavailableError)
def handle_embedding_unavailable(e):
    return _err(str(e), 503)


@api.errorhandler(RetrievalUnavailableError)
def handle_retrieval_unavailable(e):
    return _err(str(e), 503)


@api.errorhandler(PDFExtractionError)
def handle_pdf_error(e):
    return _err(str(e), 422)


@api.errorhandler(ValueError)
def handle_value_error(e):
    return _err(str(e), 400)


@api.errorhandler(sqlite3.IntegrityError)
def handle_integrity(e):
    return _err("A referenced paper, project or item does not exist.", 404)


@api.errorhandler(sqlite3.Error)
def handle_db(e):
    logger.exception("database error")
    return _err("A database error occurred. Your data was not changed by this request.", 500)


@api.errorhandler(Exception)
def handle_unexpected(e):
    if isinstance(e, HTTPException):
        return e
    logger.exception("unhandled API error")
    return _err("Unexpected server error. Nothing was fabricated or saved for this request.", 500)


# ---------- Search ----------
@api.route("/search", methods=["POST"])
@require_api_key
@rate_limit("search")
def search_papers():
    body = request.get_json(force=True, silent=True) or {}
    query = (body.get("query") or "").strip()
    if not query:
        return _err("A search query is required.")
    if len(query) > 300:
        return _err("The search query is too long (max 300 characters).")
    sources = body.get("sources") or None
    if sources is not None:
        if not isinstance(sources, list) or not sources or any(s not in ALL_PROVIDERS for s in sources):
            return _err(f"sources must be a non-empty subset of {sorted(ALL_PROVIDERS)}.")
    year = body.get("year")
    if year is not None and (isinstance(year, bool) or not isinstance(year, int) or not 1800 <= year <= 2100):
        return _err("year must be a four-digit integer.")
    author = body.get("author")
    if author is not None and not isinstance(author, str):
        return _err("author must be text.")
    results, errors = agent.search_papers(query, sources=sources, year=year, author=(author or None),
                                           open_access_only=bool(body.get("open_access_only")))
    if not results and errors and len(errors) >= len(sources or ALL_PROVIDERS):
        # every requested source failed: say so explicitly (503) rather than showing "no results"
        return jsonify({"error": "All selected sources were unavailable.", "source_errors": errors,
                        "results": [], "count": 0}), 503
    return jsonify({"results": [r.__dict__ for r in results], "source_errors": errors, "count": len(results)})


# ---------- Import / Save ----------
@api.route("/papers/import", methods=["POST"])
@require_api_key
@rate_limit("import")
def import_paper():
    body = request.get_json(force=True, silent=True) or {}
    title = body.get("title")
    if not isinstance(title, str) or not title.strip():
        return _err("Missing required field: title")
    authors = body.get("authors") or []
    if not isinstance(authors, list) or any(not isinstance(a, str) for a in authors):
        return _err("authors must be a list of names.")
    year = body.get("year")
    cc = body.get("citation_count")
    clean = {
        "title": title.strip()[:1000], "authors": [a.strip()[:200] for a in authors if a.strip()][:200],
        "abstract": body.get("abstract") if isinstance(body.get("abstract"), str) else None,
        "year": year if isinstance(year, int) and not isinstance(year, bool) else None,
        "venue": body.get("venue") if isinstance(body.get("venue"), str) else None,
        "doi": (body.get("doi").strip().lower() if isinstance(body.get("doi"), str) and body.get("doi").strip() else None),
        "external_id": body.get("external_id") if isinstance(body.get("external_id"), str) else None,
        "source": body.get("source") if body.get("source") in ("semantic_scholar", "crossref", "arxiv", "upload", "url") else "url",
        "source_url": _http_url(body.get("source_url")), "pdf_url": _http_url(body.get("pdf_url")),
        "citation_count": cc if isinstance(cc, int) and not isinstance(cc, bool) else None,
        "open_access": bool(body.get("open_access")), "raw": body.get("raw") if isinstance(body.get("raw"), dict) else {},
    }
    existed = find_existing_paper(clean["doi"], clean["external_id"], clean["title"]) is not None
    paper_id = agent.import_paper_metadata(clean)
    return jsonify({"paper_id": paper_id, "duplicate": existed})


@api.route("/papers/<int:paper_id>/import-pdf-from-url", methods=["POST"])
@require_api_key
@rate_limit("import")
def import_pdf_from_url(paper_id):
    if not _require_paper(paper_id):
        return _err("Paper not found.", 404)
    body = request.get_json(force=True, silent=True) or {}
    url = body.get("url")
    filename = f"{uuid.uuid4().hex}.pdf"
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    try:
        fetch_pdf(url, path, max_bytes=current_app.config["MAX_CONTENT_LENGTH"])
    except UnsafeURLError as exc:
        return _err(f"URL rejected: {exc}", 400)
    except FetchError as exc:
        return _err(str(exc), 502)
    try:
        summary = agent.ingest_pdf(paper_id, path)
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        raise
    return jsonify({"status": "ingested", "summary": summary})


@api.route("/papers/upload", methods=["POST"])
@require_api_key
@rate_limit("upload")
def upload_pdf():
    if "file" not in request.files:
        return _err("No file part in request.")
    file = request.files["file"]
    if file.filename == "":
        return _err("No file selected.")
    if not allowed_file(file.filename):
        return _err("Only PDF files are allowed.", 415)

    filename = secure_filename(f"{uuid.uuid4().hex}_{file.filename}") or f"{uuid.uuid4().hex}.pdf"
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], filename)
    file.save(path)
    with open(path, "rb") as f:
        header = f.read(5)
    if header[:4] != b"%PDF":
        os.remove(path)
        return _err("The uploaded file is not a valid PDF.", 415)

    title = (request.form.get("title") or file.filename.rsplit(".", 1)[0]).strip()[:1000] or "Untitled upload"
    existing = find_existing_paper(None, None, title)
    if existing:
        with db_cursor() as cur:
            cur.execute("SELECT ingestion_status FROM papers WHERE id = ?", (existing,))
            status = cur.fetchone()["ingestion_status"]
        if status in ("chunked", "text_only"):
            os.remove(path)
            return jsonify({"paper_id": existing, "status": "duplicate", "duplicate": True,
                            "message": "A paper with this title is already in your library with full text; nothing was re-imported."})
    paper_id = existing or agent.import_paper_metadata({"title": title, "source": "upload", "authors": [], "raw": {}})
    try:
        summary = agent.ingest_pdf(paper_id, path)
    except Exception:
        if os.path.exists(path):
            os.remove(path)
        if not existing:  # don't leave an empty phantom record behind after a failed new upload
            with db_cursor(commit=True) as cur:
                cur.execute("DELETE FROM papers WHERE id = ?", (paper_id,))
        raise
    return jsonify({"paper_id": paper_id, "status": "ingested", "duplicate": False, "summary": summary})


@api.route("/papers/<int:paper_id>/reembed", methods=["POST"])
@require_api_key
@rate_limit("reembed")
def reembed(paper_id):
    if not _require_paper(paper_id):
        return _err("Paper not found.", 404)
    return jsonify(reembed_paper(paper_id))


# ---------- Analysis ----------
@api.route("/papers/<int:paper_id>/analyze", methods=["POST"])
@require_api_key
@rate_limit("analyze")
def analyze_paper(paper_id):
    if not _require_paper(paper_id):
        return _err("Paper not found.", 404)
    body = request.get_json(force=True, silent=True) or {}
    return jsonify(agent.analyze_paper(paper_id, force=bool(body.get("force"))))


@api.route("/papers/<int:paper_id>/explain-simply", methods=["POST"])
@require_api_key
@rate_limit("explain")
def explain_simply(paper_id):
    if not _require_paper(paper_id):
        return _err("Paper not found.", 404)
    body = request.get_json(force=True, silent=True) or {}
    text = body.get("text", "")
    if not isinstance(text, str) or not text.strip():
        return _err("text is required.")
    return jsonify({"simplified": agent.explain_simply(paper_id, text[:4000])})


# ---------- Chat ----------
@api.route("/papers/<int:paper_id>/chat", methods=["POST"])
@require_api_key
@rate_limit("chat")
def chat_with_paper(paper_id):
    if not _require_paper(paper_id):
        return _err("Paper not found.", 404)
    body = request.get_json(force=True, silent=True) or {}
    question = body.get("question")
    if not isinstance(question, str) or not question.strip():
        return _err("A question is required.")
    if len(question) > 1000:
        return _err("The question is too long (max 1000 characters).")
    return jsonify(agent.chat(paper_id, question.strip()))


# ---------- Compare / Gaps / Questions / Experiments ----------
@api.route("/compare", methods=["POST"])
@require_api_key
@rate_limit("compare")
def compare_papers():
    body = request.get_json(force=True, silent=True) or {}
    return jsonify(agent.compare(_ids(body.get("paper_ids"), minimum=2, maximum=10)))


@api.route("/gaps/find", methods=["POST"])
@require_api_key
@rate_limit("gaps")
def find_gaps():
    body = request.get_json(force=True, silent=True) or {}
    ids = _ids(body.get("paper_ids"), minimum=1)
    missing = [p for p in ids if not _require_paper(p)]
    if missing:
        return _err(f"Paper id(s) not found: {missing}", 404)
    gaps, report = gap_finder.find_gaps_with_report(ids, body.get("project_id"))
    return jsonify({"gaps": gaps, "report": report})


@api.route("/gaps/<int:gap_id>/project", methods=["POST"])
@require_api_key
def link_gap(gap_id):
    body = request.get_json(force=True, silent=True) or {}
    pid = body.get("project_id")
    if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int)):
        return _err("project_id must be an integer or null.")
    if not gap_finder.link_gap_to_project(gap_id, pid):
        return _err("Gap not found.", 404)
    return jsonify({"gap_id": gap_id, "project_id": pid})


@api.route("/questions/generate", methods=["POST"])
@require_api_key
@rate_limit("questions")
def generate_questions():
    body = request.get_json(force=True, silent=True) or {}
    ids = _ids(body.get("paper_ids"))
    for p in ids:
        if not _require_paper(p):
            return _err(f"Paper id {p} not found.", 404)
    count = body.get("count", 5)
    if isinstance(count, bool) or not isinstance(count, int):
        return _err("count must be an integer.")
    questions, report = question_generator.generate_questions_with_report(ids, body.get("project_id"), body.get("gap_id"), count)
    return jsonify({"questions": questions, "report": report})


@api.route("/questions/<int:question_id>/project", methods=["POST"])
@require_api_key
def link_question(question_id):
    body = request.get_json(force=True, silent=True) or {}
    pid = body.get("project_id")
    if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int)):
        return _err("project_id must be an integer or null.")
    if not question_generator.link_question_to_project(question_id, pid):
        return _err("Question not found.", 404)
    return jsonify({"question_id": question_id, "project_id": pid})


@api.route("/experiments/plan", methods=["POST"])
@require_api_key
@rate_limit("experiments")
def plan_experiment():
    body = request.get_json(force=True, silent=True) or {}
    question_id = body.get("question_id")
    if not isinstance(question_id, int) or isinstance(question_id, bool):
        return _err("question_id is required.")
    with db_cursor() as cur:
        cur.execute("SELECT * FROM research_questions WHERE id = ?", (question_id,))
        row = cur.fetchone()
    if not row:
        return _err("Research question not found.", 404)
    return jsonify(agent.plan_experiment(dict(row), body.get("project_id")))


# ---------- Notes / Highlights / Tags ----------
def _text_field(body, key, limit=20000):
    v = body.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ValueError(f"{key} is required.")
    return v.strip()[:limit]


@api.route("/papers/<int:paper_id>/notes", methods=["POST"])
@require_api_key
@rate_limit("write")
def add_note(paper_id):
    body = request.get_json(force=True, silent=True) or {}
    content = _text_field(body, "content")
    if not _require_paper(paper_id):
        return _err("Paper not found.", 404)
    with db_cursor(commit=True) as cur:
        cur.execute("INSERT INTO notes (paper_id, project_id, content) VALUES (?, ?, ?)", (paper_id, body.get("project_id"), content))
        return jsonify({"id": cur.lastrowid})


@api.route("/papers/<int:paper_id>/highlights", methods=["POST"])
@require_api_key
@rate_limit("write")
def add_highlight(paper_id):
    body = request.get_json(force=True, silent=True) or {}
    quote = _text_field(body, "quote")
    if not _require_paper(paper_id):
        return _err("Paper not found.", 404)
    with db_cursor(commit=True) as cur:
        cur.execute("INSERT INTO highlights (paper_id, quote, section, page) VALUES (?, ?, ?, ?)",
                    (paper_id, quote, body.get("section") if isinstance(body.get("section"), str) else None,
                     body.get("page") if isinstance(body.get("page"), int) else None))
        return jsonify({"id": cur.lastrowid})


@api.route("/papers/<int:paper_id>/tags", methods=["POST"])
@require_api_key
@rate_limit("write")
def add_tag(paper_id):
    body = request.get_json(force=True, silent=True) or {}
    name = _text_field(body, "name", 60).lower()
    if not _require_paper(paper_id):
        return _err("Paper not found.", 404)
    with db_cursor(commit=True) as cur:
        cur.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        cur.execute("SELECT id FROM tags WHERE name = ?", (name,))
        tag_id = cur.fetchone()["id"]
        cur.execute("INSERT OR IGNORE INTO paper_tags (paper_id, tag_id) VALUES (?, ?)", (paper_id, tag_id))
    return jsonify({"tag_id": tag_id, "name": name})


# ---------- Projects ----------
@api.route("/projects", methods=["POST"])
@require_api_key
@rate_limit("write")
def create_project():
    body = request.get_json(force=True, silent=True) or {}
    title = _text_field(body, "title", 300)
    with db_cursor(commit=True) as cur:
        cur.execute("INSERT INTO projects (user_id, title, objective) VALUES (?, ?, ?)",
                    (get_default_user_id(), title, (body.get("objective") or "")[:5000] if isinstance(body.get("objective", ""), str) else ""))
        return jsonify({"id": cur.lastrowid})


@api.route("/projects/<int:project_id>/papers", methods=["POST"])
@require_api_key
@rate_limit("write")
def add_paper_to_project(project_id):
    body = request.get_json(force=True, silent=True) or {}
    paper_id = body.get("paper_id")
    if not isinstance(paper_id, int) or isinstance(paper_id, bool):
        return _err("paper_id is required.")
    with db_cursor(commit=True) as cur:
        cur.execute("INSERT OR IGNORE INTO project_papers (project_id, paper_id) VALUES (?, ?)", (project_id, paper_id))
    return jsonify({"status": "added"})


@api.route("/projects/<int:project_id>/notes", methods=["POST"])
@require_api_key
@rate_limit("write")
def add_project_note(project_id):
    body = request.get_json(force=True, silent=True) or {}
    content = _text_field(body, "content")
    with db_cursor(commit=True) as cur:
        cur.execute("INSERT INTO notes (project_id, content) VALUES (?, ?)", (project_id, content))
        return jsonify({"id": cur.lastrowid})


# ---------- Literature Review ----------
@api.route("/literature-review", methods=["POST"])
@require_api_key
@rate_limit("write")
def save_literature_review():
    body = request.get_json(force=True, silent=True) or {}
    project_id = body.get("project_id")
    if not isinstance(project_id, int) or isinstance(project_id, bool):
        return _err("Missing required field: project_id")
    theme = _text_field(body, "theme", 300)
    ids = _ids(body.get("paper_ids"))
    s = lambda k: body.get(k, "") if isinstance(body.get(k, ""), str) else ""
    with db_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO literature_reviews (project_id, theme, papers_json, agreement, disagreement,
                                                  evolution, limitations, open_questions, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, theme, json.dumps(ids), s("agreement"), s("disagreement"), s("evolution"),
             s("limitations"), s("open_questions"), s("notes")),
        )
        return jsonify({"id": cur.lastrowid})
