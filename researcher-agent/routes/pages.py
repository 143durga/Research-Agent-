import json
from flask import Blueprint, render_template, abort, current_app
from db.database import db_cursor
from agent.capabilities import paper_analyzer, paper_chat, gap_finder, question_generator, experiment_planner, citation_verifier
from providers.llm.factory import get_llm_provider
from providers.embeddings.factory import get_embedding_provider
from agent.capabilities.paper_retriever import retrieval_mode
from urllib.parse import urlparse

pages = Blueprint("pages", __name__)


@pages.app_template_filter("safe_url")
def safe_url(value):
    """Only http(s) links are rendered as hrefs (blocks javascript:/data: URLs from external metadata)."""
    if isinstance(value, str):
        p = urlparse(value.strip())
        if p.scheme in ("http", "https") and p.netloc:
            return value.strip()
    return "#"


def _projects():
    with db_cursor() as cur:
        cur.execute("SELECT id, title FROM projects ORDER BY updated_at DESC")
        return [dict(r) for r in cur.fetchall()]


def _paper_row_to_dict(row):
    d = dict(row)
    d["keywords"] = json.loads(d.get("keywords") or "[]")
    with db_cursor() as cur:
        cur.execute(
            "SELECT a.name FROM authors a JOIN paper_authors pa ON pa.author_id = a.id WHERE pa.paper_id = ? ORDER BY pa.position",
            (d["id"],),
        )
        d["authors"] = [r["name"] for r in cur.fetchall()]
        cur.execute("SELECT t.name FROM tags t JOIN paper_tags pt ON pt.tag_id = t.id WHERE pt.paper_id = ?", (d["id"],))
        d["tags"] = [r["name"] for r in cur.fetchall()]
    return d


@pages.route("/")
def dashboard():
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) c FROM papers")
        total_papers = cur.fetchone()["c"]
        cur.execute("SELECT * FROM papers ORDER BY created_at DESC LIMIT 6")
        recent_papers = [_paper_row_to_dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM projects ORDER BY updated_at DESC LIMIT 6")
        projects = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT a.*, p.title as paper_title FROM analyses a JOIN papers p ON p.id = a.paper_id ORDER BY a.created_at DESC LIMIT 5"
        )
        recent_analyses = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM research_questions ORDER BY created_at DESC LIMIT 5")
        recent_questions = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT DISTINCT venue FROM papers WHERE venue IS NOT NULL AND venue != '' LIMIT 12")
        topics = [r["venue"] for r in cur.fetchall()]

    llm = get_llm_provider()
    embed = get_embedding_provider()
    return render_template(
        "dashboard.html", total_papers=total_papers, recent_papers=recent_papers, projects=projects,
        recent_analyses=recent_analyses, recent_questions=recent_questions, topics=topics,
        llm_configured=llm.is_configured(), llm_provider_name=llm.name, embedding_provider_name=embed.name,
    )


@pages.route("/search")
def search_page():
    with db_cursor() as cur:
        cur.execute("SELECT * FROM search_history ORDER BY created_at DESC LIMIT 8")
        history = [dict(r) for r in cur.fetchall()]
    return render_template("search.html", history=history)


@pages.route("/library")
def library():
    with db_cursor() as cur:
        cur.execute("SELECT * FROM papers ORDER BY created_at DESC")
        papers = [_paper_row_to_dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM tags ORDER BY name")
        tags = [dict(r) for r in cur.fetchall()]
    return render_template("library.html", papers=papers, tags=tags)


@pages.route("/paper/<int:paper_id>")
def reader(paper_id):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
        row = cur.fetchone()
        if not row:
            abort(404)
        cur.execute("SELECT * FROM paper_sections WHERE paper_id = ? ORDER BY order_index", (paper_id,))
        sections = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM notes WHERE paper_id = ? ORDER BY created_at DESC", (paper_id,))
        notes = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM highlights WHERE paper_id = ? ORDER BY created_at DESC", (paper_id,))
        highlights = [dict(r) for r in cur.fetchall()]
    paper = _paper_row_to_dict(row)
    citations = citation_verifier.verify_citation_record(paper_id)
    return render_template("reader.html", paper=paper, sections=sections, notes=notes, highlights=highlights, citations=citations)


@pages.route("/paper/<int:paper_id>/analysis")
def analysis_page(paper_id):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
        row = cur.fetchone()
        if not row:
            abort(404)
    paper = _paper_row_to_dict(row)
    latest = paper_analyzer.get_latest_analysis(paper_id)
    return render_template("analysis.html", paper=paper, analysis=latest)


@pages.route("/paper/<int:paper_id>/chat")
def chat_page(paper_id):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM papers WHERE id = ?", (paper_id,))
        row = cur.fetchone()
        if not row:
            abort(404)
    paper = _paper_row_to_dict(row)
    history = paper_chat.get_history(paper_id)
    return render_template("chat.html", paper=paper, history=history)


@pages.route("/compare")
def compare_page():
    with db_cursor() as cur:
        cur.execute("SELECT id, title, year, venue FROM papers ORDER BY created_at DESC")
        papers = [dict(r) for r in cur.fetchall()]
    return render_template("compare.html", papers=papers)


@pages.route("/gaps")
def gaps_page():
    with db_cursor() as cur:
        cur.execute("SELECT id, title, year FROM papers ORDER BY created_at DESC")
        papers = [dict(r) for r in cur.fetchall()]
    gaps = gap_finder.list_gaps()
    return render_template("gaps.html", papers=papers, gaps=gaps, projects=_projects())


@pages.route("/questions")
def questions_page():
    with db_cursor() as cur:
        cur.execute("SELECT id, title, year FROM papers ORDER BY created_at DESC")
        papers = [dict(r) for r in cur.fetchall()]
    questions = question_generator.list_questions()
    gaps = gap_finder.list_gaps()
    return render_template("questions.html", papers=papers, questions=questions, gaps=gaps, projects=_projects())


@pages.route("/experiments")
def experiments_page():
    questions = question_generator.list_questions()
    plans = experiment_planner.list_plans()
    return render_template("experiments.html", questions=questions, plans=plans, projects=_projects())


@pages.route("/literature-review")
def literature_review_page():
    with db_cursor() as cur:
        cur.execute("SELECT * FROM projects ORDER BY updated_at DESC")
        projects = [dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM literature_reviews ORDER BY created_at DESC")
        reviews = [dict(r) for r in cur.fetchall()]
        for r in reviews:
            r["papers"] = json.loads(r["papers_json"] or "[]")
        cur.execute("SELECT id, title FROM papers ORDER BY created_at DESC")
        papers = [dict(r) for r in cur.fetchall()]
    return render_template("literature_review.html", projects=projects, reviews=reviews, papers=papers)


@pages.route("/projects")
def projects_page():
    with db_cursor() as cur:
        cur.execute("SELECT * FROM projects ORDER BY updated_at DESC")
        projects = [dict(r) for r in cur.fetchall()]
        for p in projects:
            cur.execute(
                "SELECT p2.id, p2.title FROM project_papers pp JOIN papers p2 ON p2.id = pp.paper_id WHERE pp.project_id = ?",
                (p["id"],),
            )
            p["papers"] = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT COUNT(*) c FROM research_gaps WHERE project_id = ?", (p["id"],))
            p["gap_count"] = cur.fetchone()["c"]
            cur.execute("SELECT COUNT(*) c FROM research_questions WHERE project_id = ?", (p["id"],))
            p["question_count"] = cur.fetchone()["c"]
        cur.execute("SELECT id, title FROM papers ORDER BY created_at DESC")
        all_papers = [dict(r) for r in cur.fetchall()]
    return render_template("projects.html", projects=projects, all_papers=all_papers)


@pages.route("/projects/<int:project_id>")
def project_detail(project_id):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM projects WHERE id = ?", (project_id,))
        project = cur.fetchone()
        if not project:
            abort(404)
        project = dict(project)
        cur.execute(
            "SELECT p2.* FROM project_papers pp JOIN papers p2 ON p2.id = pp.paper_id WHERE pp.project_id = ?",
            (project_id,),
        )
        project["papers"] = [_paper_row_to_dict(r) for r in cur.fetchall()]
        cur.execute("SELECT * FROM notes WHERE project_id = ? ORDER BY created_at DESC", (project_id,))
        project["notes"] = [dict(r) for r in cur.fetchall()]
    gaps = gap_finder.list_gaps(project_id)
    questions = question_generator.list_questions(project_id)
    plans = experiment_planner.list_plans(project_id)
    return render_template("project_detail.html", project=project, gaps=gaps, questions=questions, plans=plans)


@pages.route("/settings")
def settings_page():
    llm = get_llm_provider()
    embed = get_embedding_provider()
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) c FROM papers")
        total_papers = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM papers WHERE ingestion_status = 'chunked'")
        chunked_papers = cur.fetchone()["c"]
    return render_template(
        "settings.html",
        llm_provider_name=llm.name, llm_configured=llm.is_configured(), llm_model=getattr(llm, "model", "n/a"),
        embedding_provider_name=embed.name, embedding_configured=embed.is_configured(),
        total_papers=total_papers, chunked_papers=chunked_papers, retrieval=retrieval_mode(),
        api_locked=bool(current_app.config.get("APP_API_KEY")),
    )
