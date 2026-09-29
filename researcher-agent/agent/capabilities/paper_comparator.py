"""
PaperComparator: compares 2-10 papers across problem, methodology, dataset,
metrics, results, limitations, contributions, future work - plus a narrative
synthesis of common themes, differences, conflicts, and research opportunities.
Never ranks papers as "best".
"""
from typing import List, Dict
from agent.llm_utils import call_llm_json, get_paper_context, format_evidence_note, NO_FABRICATION_RULE, evidence_in_text

COMPARE_DIMENSIONS = [
    "problem", "objective", "methodology", "model", "dataset",
    "evaluation_metrics", "results", "limitations", "contributions", "future_work",
]

SYSTEM = NO_FABRICATION_RULE + (
    " You are comparing multiple papers. You must never declare one paper objectively "
    "\"best\" or \"better\" - only describe differences, trade-offs, and what each reports."
)

PROMPT_TEMPLATE = """Compare the following {n} papers across these dimensions: {dims}.

{papers_block}

Return a JSON object with this exact shape:
{{
  "comparison_table": [
    {{
      "paper_id": <int>,
      "title": "<title>",
      "problem": {{"value": "...", "status": "EXPLICITLY_STATED|INFERRED|NOT_FOUND", "evidence": "..."}},
      "objective": {{...same shape...}},
      "methodology": {{...}},
      "model": {{...}},
      "dataset": {{...}},
      "evaluation_metrics": {{...}},
      "results": {{...}},
      "limitations": {{...}},
      "contributions": {{...}},
      "future_work": {{...}}
    }}
  ],
  "common_themes": ["..."],
  "differences": ["..."],
  "conflicting_findings": ["..."],
  "different_datasets": ["..."],
  "different_evaluation_approaches": ["..."],
  "research_opportunities": ["..."]
}}
Do not include a "best paper" or ranking field. If two papers report seemingly conflicting
results, describe both sides in conflicting_findings without resolving which is correct.
"""


def _cell(raw, own_text, other_texts):
    """Validate one table cell against the paper it is attributed to."""
    raw = raw if isinstance(raw, dict) else {}
    status = str(raw.get("status", "NOT_FOUND")).upper().replace(" ", "_")
    value = str(raw.get("value") or "").strip()
    evidence = str(raw.get("evidence") or "").strip()
    flag = None
    if status not in ("EXPLICITLY_STATED", "INFERRED", "NOT_FOUND") or not value:
        status = "NOT_FOUND"
    if status != "NOT_FOUND":
        if not evidence:
            status, flag = "NOT_FOUND", "no_evidence"
        elif not evidence_in_text(evidence, own_text):
            if any(evidence_in_text(evidence, t) for t in other_texts):
                status, flag = "NOT_FOUND", "misattributed_to_other_paper"
            else:
                status, flag = ("INFERRED" if status == "EXPLICITLY_STATED" else "NOT_FOUND"), "evidence_not_found_in_paper"
    if status == "NOT_FOUND":
        value, evidence = "Not found in this paper's imported text.", ""
    return {"value": value, "status": status, "evidence": evidence, "flag": flag}


def validate_comparison(result, paper_ids, contexts):
    """Rebuild the table strictly per requested paper id: titles come from the database, rows for ids
    that were not requested are dropped, every cell's evidence must occur in ITS OWN paper's text
    (evidence found only in a different paper marks a misattribution and the cell is discarded)."""
    rows_in = {}
    for row in (result.get("comparison_table") or []) if isinstance(result, dict) else []:
        try:
            pid = int(row.get("paper_id"))
        except (TypeError, ValueError, AttributeError):
            continue
        if pid in paper_ids and pid not in rows_in:
            rows_in[pid] = row
    table, flags = [], 0
    for pid in paper_ids:
        ctx = contexts[pid]
        others = [contexts[o]["source_text"] for o in paper_ids if o != pid]
        row = rows_in.get(pid, {})
        out = {"paper_id": pid, "title": ctx["paper"]["title"], "missing_from_model_output": pid not in rows_in}
        for d in COMPARE_DIMENSIONS:
            out[d] = _cell(row.get(d), ctx["source_text"], others)
            flags += 1 if out[d]["flag"] in ("misattributed_to_other_paper", "evidence_not_found_in_paper") else 0
        table.append(out)
    def _list(k):
        v = result.get(k) if isinstance(result, dict) else None
        return [str(x) for x in v] if isinstance(v, list) else []
    return {"comparison_table": table, "flagged_cells": flags,
            **{k: _list(k) for k in ("common_themes", "differences", "conflicting_findings", "different_datasets",
                                     "different_evaluation_approaches", "research_opportunities")}}


def compare_papers(paper_ids: List[int]) -> Dict:
    paper_ids = list(dict.fromkeys(paper_ids))
    if not (2 <= len(paper_ids) <= 10):
        raise ValueError("Comparison requires between 2 and 10 distinct papers.")

    contexts, papers_block_parts = {}, []
    any_missing_full_text = False
    for pid in paper_ids:
        ctx = get_paper_context(pid, max_chars=6000)
        contexts[pid] = ctx
        if not ctx["has_full_text"]:
            any_missing_full_text = True
        papers_block_parts.append(f"=== PAPER ID {pid} ===\n{ctx['context_text']}")

    prompt = PROMPT_TEMPLATE.format(
        n=len(paper_ids),
        dims=", ".join(COMPARE_DIMENSIONS),
        papers_block="\n\n".join(papers_block_parts),
    ) + format_evidence_note(not any_missing_full_text)

    result, model, provider_name = call_llm_json(system=SYSTEM, prompt=prompt, max_tokens=4000)
    out = validate_comparison(result, paper_ids, contexts)
    out["model_used"] = f"{provider_name}:{model}"
    return out
