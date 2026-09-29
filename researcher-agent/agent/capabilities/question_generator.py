"""
QuestionGenerator: turns evidence (and optionally a saved gap) into research questions.
validate_questions() rejects generic questions and questions without grounded evidence;
method / dataset / metrics are PROPOSED suggestions (labelled as such in the UI), not claims
made by the papers.
"""
import json
import re
from typing import List, Dict, Optional, Tuple
from db.database import db_cursor
from agent.llm_utils import call_llm_json, get_paper_context, NO_FABRICATION_RULE, evidence_in_text, wrap_untrusted

SYSTEM = NO_FABRICATION_RULE + (
    " You generate SPECIFIC, actionable research questions grounded in the evidence "
    "provided - never generic or vague questions like 'more research is needed'. Each "
    "question must be answerable by a concrete study design, and must state what "
    "assumptions it depends on that are not yet verified. Method, dataset and metrics are "
    "your PROPOSALS, not statements from the papers."
)

PROMPT_TEMPLATE = """Based on the following evidence, generate {count} specific, actionable
research questions.

{evidence_block}

Return a JSON array of question objects shaped as:
{{
  "question": "<specific research question ending in a question mark>",
  "motivation": "<why this question matters, grounded in the evidence above>",
  "supporting_paper_ids": [<int>, ...],
  "evidence": "<an exact quote from a supporting paper that this question responds to>",
  "possible_method": "<a PROPOSED method/approach to investigate this>",
  "possible_dataset": "<a PROPOSED dataset, or 'none identified - would need to be sourced'>",
  "possible_metrics": "<PROPOSED evaluation metrics>",
  "difficulty": "low" | "medium" | "high",
  "open_assumptions": "<assumptions this question depends on that have not been verified>"
}}
"""

_GENERIC = re.compile(r"(more research is needed|further research|future research should|what are the (challenges|issues|benefits)|"
                      r"how can (we|ai|llms?) (be )?improve[sd]?\??$|what is the (impact|future) of)", re.I)
REQUIRED = ("question", "motivation", "possible_method", "possible_dataset", "possible_metrics", "open_assumptions")


def is_generic(question: str) -> bool:
    q = (question or "").strip()
    return len(q.split()) < 9 or not q.endswith("?") or bool(_GENERIC.search(q))


def validate_questions(raw, paper_ids: List[int], source_texts: Dict[int, str]) -> Tuple[List[Dict], Dict]:
    valid = set(paper_ids)
    kept, rejected = [], {"generic": 0, "missing_fields": 0, "no_supporting_paper": 0}
    for q in raw if isinstance(raw, list) else []:
        if not isinstance(q, dict):
            rejected["missing_fields"] += 1
            continue
        if any(not str(q.get(f) or "").strip() for f in REQUIRED) or not str(q.get("evidence") or "").strip():
            rejected["missing_fields"] += 1
            continue
        if is_generic(q["question"]):
            rejected["generic"] += 1
            continue
        ids = []
        for x in q.get("supporting_paper_ids") or []:
            try:
                if int(x) in valid:
                    ids.append(int(x))
            except (TypeError, ValueError):
                pass
        if not ids:
            rejected["no_supporting_paper"] += 1
            continue
        ids = sorted(set(ids))
        ev_text = str(q["evidence"]).strip()
        verified = any(evidence_in_text(ev_text, source_texts.get(i, "")) for i in ids)
        d = str(q.get("difficulty") or "medium").lower()
        kept.append({
            "question": q["question"].strip(), "motivation": str(q["motivation"]).strip(),
            "supporting_paper_ids": ids, "evidence": {"text": ev_text, "verified": verified},
            "possible_method": str(q["possible_method"]).strip(), "possible_dataset": str(q["possible_dataset"]).strip(),
            "possible_metrics": str(q["possible_metrics"]).strip(), "difficulty": d if d in ("low", "medium", "high") else "medium",
            "open_assumptions": str(q["open_assumptions"]).strip(),
            "proposal_note": "Method, dataset and metrics are proposed suggestions, not claims made by the papers.",
        })
    return kept, rejected


def generate_questions_with_report(paper_ids: List[int], project_id: Optional[int] = None,
                                   gap_id: Optional[int] = None, count: int = 5) -> Tuple[List[Dict], Dict]:
    paper_ids = list(dict.fromkeys(paper_ids))
    count = max(1, min(int(count), 10))
    parts, source_texts = [], {}
    if gap_id:
        with db_cursor() as cur:
            cur.execute("SELECT * FROM research_gaps WHERE id = ?", (gap_id,))
            gap = cur.fetchone()
        if not gap:
            raise ValueError("Gap not found.")
        gap = dict(gap)
        parts.append(f"IDENTIFIED POTENTIAL GAP ({gap['gap_type']}): {gap['description']}\nRationale: {gap['rationale']}")
        if project_id is None:
            project_id = gap["project_id"]
        for pid in json.loads(gap["supporting_papers_json"] or "[]"):
            if pid not in paper_ids:
                paper_ids.append(pid)
    if not paper_ids:
        raise ValueError("Select at least one paper (or a gap that cites papers).")
    for pid in paper_ids:
        ctx = get_paper_context(pid, max_chars=3000)
        source_texts[pid] = ctx["source_text"]
        relevant = [s for s in ctx["sections"] if s["section_name"] in ("limitations", "future_work", "results", "discussion")]
        text = "\n".join(f"[{s['section_name']}] {s['content'][:1200]}" for s in relevant) or (ctx["paper"].get("abstract") or "")
        parts.append(f"=== PAPER ID {pid}: {ctx['paper']['title']} ===\n{wrap_untrusted(text, f'paper_id={pid}')}")

    prompt = PROMPT_TEMPLATE.format(count=count, evidence_block="\n\n".join(parts))
    result, model, provider_name = call_llm_json(system=SYSTEM, prompt=prompt, max_tokens=3000)
    if not isinstance(result, list):
        raise ValueError("Question generator response was not a JSON array as required.")
    questions, rejected = validate_questions(result, paper_ids, source_texts)
    with db_cursor(commit=True) as cur:
        for q in questions:
            cur.execute(
                """INSERT INTO research_questions (project_id, question, motivation, supporting_papers_json,
                                                     evidence_json, possible_method, possible_dataset,
                                                     possible_metrics, difficulty, open_assumptions, source_gap_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (project_id, q["question"], q["motivation"], json.dumps(q["supporting_paper_ids"]),
                 json.dumps(q["evidence"]), q["possible_method"], q["possible_dataset"], q["possible_metrics"],
                 q["difficulty"], q["open_assumptions"], gap_id),
            )
            q["id"] = cur.lastrowid
    rejected.update(returned_by_model=len(result), kept=len(questions), model_used=f"{provider_name}:{model}")
    return questions, rejected


def generate_questions(paper_ids, project_id=None, gap_id=None, count=5):
    return generate_questions_with_report(paper_ids, project_id, gap_id, count)[0]


def link_question_to_project(question_id: int, project_id: Optional[int]) -> bool:
    with db_cursor(commit=True) as cur:
        if project_id is not None:
            cur.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,))
            if not cur.fetchone():
                raise ValueError("Project not found.")
        cur.execute("UPDATE research_questions SET project_id = ? WHERE id = ?", (project_id, question_id))
        return cur.rowcount == 1


def _parse_evidence(raw):
    try:
        val = json.loads(raw) if raw else ""
    except (TypeError, ValueError):
        val = raw
    if isinstance(val, dict):
        return val
    return {"text": val or "", "verified": None}


def list_questions(project_id: Optional[int] = None):
    with db_cursor() as cur:
        if project_id:
            cur.execute("SELECT * FROM research_questions WHERE project_id = ? ORDER BY created_at DESC, id DESC", (project_id,))
        else:
            cur.execute("SELECT * FROM research_questions ORDER BY created_at DESC, id DESC")
        rows = []
        for r in cur.fetchall():
            row = dict(r)
            row["supporting_paper_ids"] = json.loads(row["supporting_papers_json"] or "[]")
            row["evidence"] = _parse_evidence(row.get("evidence_json"))
            rows.append(row)
        return rows
