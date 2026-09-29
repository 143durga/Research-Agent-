"""
GapFinder: surfaces POTENTIAL research gaps from limitation / future-work statements in a set of
papers. Every evidence item is typed so the UI can tell apart:
  AUTHOR_STATED_LIMITATION | AUTHOR_STATED_FUTURE_WORK | AGENT_IDENTIFIED_POTENTIAL_GAP
Deterministic guardrails (validate_gaps) enforce that the LLM cannot:
  - cite paper ids that were not selected
  - present an unverifiable quote as an author statement (it is downgraded to agent-identified)
  - emit a gap with no valid supporting evidence (dropped)
  - assert certainty ("definitely a research gap")
"""
import json
import re
from typing import List, Dict, Optional, Tuple
from db.database import db_cursor
from agent.llm_utils import call_llm_json, get_paper_context, NO_FABRICATION_RULE, evidence_in_text, wrap_untrusted

GAP_TYPES = [
    "dataset", "methodological", "evaluation", "generalization", "security",
    "reproducibility", "deployment", "scalability", "theoretical", "application",
]
STATEMENT_TYPES = ("AUTHOR_STATED_LIMITATION", "AUTHOR_STATED_FUTURE_WORK", "AGENT_IDENTIFIED_POTENTIAL_GAP")
PREFIX = "Potential research gap based on the reviewed literature: "

SYSTEM = NO_FABRICATION_RULE + (
    " You identify POTENTIAL research gaps strictly from limitations and future-work "
    "statements actually present in the provided papers - never from what you personally "
    "find 'interesting'. Every gap must cite which paper(s) and which quoted statement it is "
    "based on, and label each piece of evidence with a statement_type. Never say a gap is "
    "definite, certain or proven."
)

PROMPT_TEMPLATE = """Given the limitations and future-work content of these {n} papers, identify
candidate research gaps. Look for: repeated unresolved problems, differing approaches,
underexplored datasets, missing evaluation dimensions, contradictions, and areas with
limited evidence.

{papers_block}

Classify each gap using ONE of these types: {gap_types}.

Return a JSON array of gap objects, each shaped as:
{{
  "gap_type": "<one of the types above>",
  "description": "<neutral description of the potential gap>",
  "supporting_paper_ids": [<int>, ...],
  "evidence": [{{"paper_id": <int>, "quote_or_paraphrase": "<exact quote from that paper>", "section": "limitations|future_work|...",
                 "statement_type": "AUTHOR_STATED_LIMITATION" | "AUTHOR_STATED_FUTURE_WORK" | "AGENT_IDENTIFIED_POTENTIAL_GAP"}}],
  "why_unresolved": "<why this appears unresolved across the reviewed papers; state your reasoning as reasoning, not as a finding>",
  "potential_research_question": "<a single candidate research question this gap suggests>"
}}
Use AUTHOR_STATED_LIMITATION / AUTHOR_STATED_FUTURE_WORK only for quotes copied from the papers'
own limitation / future-work text. Use AGENT_IDENTIFIED_POTENTIAL_GAP for your own synthesis
across papers. Only produce a gap if you can cite at least one specific supporting statement.
If the papers give no usable limitations/future-work content, return an empty array.
"""

_CERTAINTY = re.compile(r"\b(definitely|certainly|undoubtedly|unquestionably|proven|conclusively)\b\s*", re.I)


def _neutral_description(text: str) -> str:
    text = _CERTAINTY.sub("", str(text or "").strip())
    text = re.sub(r"^potential research gap[^:]*:\s*", "", text, flags=re.I)
    text = re.sub(r"\b(is|are) a (clear |definite )?research gap\b", "may be a research gap", text, flags=re.I)
    return PREFIX + text[0].lower() + text[1:] if text else ""


def validate_gaps(raw, paper_ids: List[int], source_texts: Dict[int, str]) -> Tuple[List[Dict], Dict]:
    valid = set(paper_ids)
    kept, dropped = [], {"no_valid_evidence": 0, "malformed": 0, "invalid_paper_refs": 0, "unverified_quotes_downgraded": 0}
    for gap in raw if isinstance(raw, list) else []:
        if not isinstance(gap, dict) or not str(gap.get("description") or "").strip():
            dropped["malformed"] += 1
            continue
        evidence = []
        for ev in gap.get("evidence") or []:
            try:
                pid = int(ev.get("paper_id"))
            except (TypeError, ValueError, AttributeError):
                dropped["invalid_paper_refs"] += 1
                continue
            quote = str(ev.get("quote_or_paraphrase") or "").strip()
            if pid not in valid:
                dropped["invalid_paper_refs"] += 1
                continue
            if not quote:
                continue
            stype = ev.get("statement_type")
            if stype not in STATEMENT_TYPES:
                stype = "AGENT_IDENTIFIED_POTENTIAL_GAP"
            verified = evidence_in_text(quote, source_texts.get(pid, ""))
            if stype != "AGENT_IDENTIFIED_POTENTIAL_GAP" and not verified:
                stype = "AGENT_IDENTIFIED_POTENTIAL_GAP"  # cannot be presented as an author statement
                dropped["unverified_quotes_downgraded"] += 1
            evidence.append({"paper_id": pid, "quote_or_paraphrase": quote, "section": str(ev.get("section") or ""),
                             "statement_type": stype, "quote_verified": verified})
        if not evidence:
            dropped["no_valid_evidence"] += 1
            continue
        gtype = gap.get("gap_type") if gap.get("gap_type") in GAP_TYPES else "unclassified"
        kept.append({
            "gap_type": gtype,
            "description": _neutral_description(gap["description"]),
            "supporting_paper_ids": sorted({e["paper_id"] for e in evidence}),
            "evidence": evidence,
            "why_unresolved": str(gap.get("why_unresolved") or ""),
            "potential_research_question": str(gap.get("potential_research_question") or ""),
        })
    return kept, dropped


def find_gaps_with_report(paper_ids: List[int], project_id: Optional[int] = None) -> Tuple[List[Dict], Dict]:
    paper_ids = list(dict.fromkeys(paper_ids))
    if len(paper_ids) < 1:
        raise ValueError("Gap finding requires at least one paper (ideally several, for comparison).")

    parts, source_texts = [], {}
    for pid in paper_ids:
        ctx = get_paper_context(pid, max_chars=4000)
        source_texts[pid] = ctx["source_text"]
        picked = [s for s in ctx["sections"] if s["section_name"] in ("limitations", "future_work", "discussion", "conclusion")]
        if picked:
            text = "\n".join(f"[{s['section_name']}] {s['content'][:1500]}" for s in picked)
        else:
            text = "(No explicit limitations/future-work section was extracted for this paper - abstract only.)\n" + (ctx["paper"].get("abstract") or "")
        parts.append(f"=== PAPER ID {pid}: {ctx['paper']['title']} ===\n{wrap_untrusted(text, f'paper_id={pid}')}")

    prompt = PROMPT_TEMPLATE.format(n=len(paper_ids), gap_types=", ".join(GAP_TYPES), papers_block="\n\n".join(parts))
    result, model, provider_name = call_llm_json(system=SYSTEM, prompt=prompt, max_tokens=3500)
    if not isinstance(result, list):
        raise ValueError("Gap finder response was not a JSON array as required.")

    gaps, report = validate_gaps(result, paper_ids, source_texts)
    report["returned_by_model"] = len(result)
    report["kept"] = len(gaps)
    report["model_used"] = f"{provider_name}:{model}"
    with db_cursor(commit=True) as cur:
        for gap in gaps:
            cur.execute(
                """INSERT INTO research_gaps (project_id, gap_type, description, supporting_papers_json,
                                                evidence_json, rationale, potential_question)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (project_id, gap["gap_type"], gap["description"], json.dumps(gap["supporting_paper_ids"]),
                 json.dumps(gap["evidence"]), gap["why_unresolved"], gap["potential_research_question"]),
            )
            gap["id"] = cur.lastrowid
    return gaps, report


def find_gaps(paper_ids: List[int], project_id: Optional[int] = None) -> List[Dict]:
    return find_gaps_with_report(paper_ids, project_id)[0]


def link_gap_to_project(gap_id: int, project_id: Optional[int]) -> bool:
    with db_cursor(commit=True) as cur:
        if project_id is not None:
            cur.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,))
            if not cur.fetchone():
                raise ValueError("Project not found.")
        cur.execute("UPDATE research_gaps SET project_id = ? WHERE id = ?", (project_id, gap_id))
        return cur.rowcount == 1


def list_gaps(project_id: int = None):
    with db_cursor() as cur:
        if project_id:
            cur.execute("SELECT * FROM research_gaps WHERE project_id = ? ORDER BY created_at DESC, id DESC", (project_id,))
        else:
            cur.execute("SELECT * FROM research_gaps ORDER BY created_at DESC, id DESC")
        rows = []
        for r in cur.fetchall():
            row = dict(r)
            row["supporting_paper_ids"] = json.loads(row["supporting_papers_json"])
            row["evidence"] = json.loads(row["evidence_json"])
            rows.append(row)
        return rows
