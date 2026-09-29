"""
PaperAnalyzer: generates the structured 15-section analysis (Research Problem,
Motivation, ... Key Takeaways), each item tagged EXPLICITLY_STATED / INFERRED /
NOT_FOUND with the supporting evidence and section it came from.
"""
import json
from typing import Dict
from db.database import db_cursor
from agent.llm_utils import call_llm_json, get_paper_context, format_evidence_note, NO_FABRICATION_RULE, evidence_in_text

ANALYSIS_SECTIONS = [
    "Research Problem", "Motivation", "Research Objective", "Research Questions",
    "Proposed Approach", "Methodology", "Dataset", "Experimental Setup",
    "Evaluation Metrics", "Results", "Contributions", "Limitations",
    "Threats to Validity", "Future Work", "Key Takeaways",
]

PROMPT_TEMPLATE = """Analyze the following academic paper and produce a structured breakdown.

For EACH of these {n} sections, produce one JSON object:
{sections}

Paper text:
---
{context}
---
{evidence_note}

Return a JSON array of exactly {n} objects, one per section above, each with this shape:
{{
  "section": "<one of the section names above, verbatim>",
  "claim": "<a concise 1-3 sentence summary for this section>",
  "evidence": "<a short supporting quote or close paraphrase from the paper text, or empty string if NOT_FOUND>",
  "evidence_location": "<paper section name / page mentioned in the text, or empty string if NOT_FOUND>",
  "status": "EXPLICITLY_STATED" | "INFERRED" | "NOT_FOUND"
}}
"""


VALID_STATUS = {"EXPLICITLY_STATED", "INFERRED", "NOT_FOUND"}
NOT_FOUND_CLAIM = "The imported paper text does not address this."


def validate_sections(raw, source_text: str):
    """Deterministic guardrails applied to whatever the LLM returned:
    - exactly the 15 expected sections, in order (missing ones become NOT_FOUND)
    - unknown/invalid statuses become NOT_FOUND
    - NOT_FOUND items carry no evidence and a fixed claim (no assumption can pass as a finding)
    - EXPLICITLY_STATED / INFERRED items must carry evidence that actually occurs in the paper text;
      an unverifiable 'explicit' quote is downgraded to INFERRED (flagged), an unsupported inference
      is downgraded to NOT_FOUND."""
    by_name = {}
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and item.get("section") in ANALYSIS_SECTIONS and item["section"] not in by_name:
            by_name[item["section"]] = item
    out = []
    for name in ANALYSIS_SECTIONS:
        item = by_name.get(name) or {}
        status = str(item.get("status", "NOT_FOUND")).upper().replace(" ", "_")
        if status not in VALID_STATUS:
            status = "NOT_FOUND"
        claim = str(item.get("claim") or "").strip()
        evidence = str(item.get("evidence") or "").strip()
        location = str(item.get("evidence_location") or "").strip()
        verified = None
        note = None
        if status != "NOT_FOUND":
            if not evidence or not claim:
                status, note = "NOT_FOUND", "No supporting evidence was provided, so the claim was discarded."
            else:
                verified = evidence_in_text(evidence, source_text)
                if not verified:
                    if status == "EXPLICITLY_STATED":
                        status, note = "INFERRED", "The quoted evidence could not be located in the paper text, so this is not treated as explicitly stated."
                    else:
                        status, note = "NOT_FOUND", "The cited evidence could not be located in the paper text, so the claim was discarded."
        if status == "NOT_FOUND":
            claim, evidence, location, verified = NOT_FOUND_CLAIM, "", "", None
        out.append({"section": name, "claim": claim, "evidence": evidence, "evidence_location": location,
                    "status": status, "evidence_verified": verified, "note": note})
    return out


def analyze_paper(paper_id: int, force: bool = False) -> Dict:
    if not force:
        cached = get_latest_analysis(paper_id)
        if cached:
            with db_cursor() as cur:
                cur.execute("SELECT updated_at FROM papers WHERE id = ?", (paper_id,))
                row = cur.fetchone()
            if row and cached["created_at"] >= row["updated_at"]:
                return {"id": cached["id"], "paper_id": paper_id, "sections": cached["sections"],
                        "model_used": cached["model_used"], "cached": True}
    ctx = get_paper_context(paper_id)
    prompt = PROMPT_TEMPLATE.format(
        n=len(ANALYSIS_SECTIONS),
        sections="\n".join(f"- {s}" for s in ANALYSIS_SECTIONS),
        context=ctx["context_text"],
        evidence_note=format_evidence_note(ctx["has_full_text"]),
    )
    result, model, provider_name = call_llm_json(system=NO_FABRICATION_RULE, prompt=prompt, max_tokens=3500)

    if not isinstance(result, list):
        raise ValueError("Analysis response was not a JSON array as required.")
    result = validate_sections(result, ctx["source_text"])

    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO analyses (paper_id, sections_json, model_used) VALUES (?, ?, ?)",
            (paper_id, json.dumps(result), f"{provider_name}:{model}"),
        )
        analysis_id = cur.lastrowid

    return {"id": analysis_id, "paper_id": paper_id, "sections": result, "model_used": f"{provider_name}:{model}", "cached": False}


def explain_simply(paper_id: int, technical_text: str) -> str:
    """'Explain Simply' mode: rewrites a technical passage in plain language
    while preserving technical accuracy (does not add new claims)."""
    from providers.llm.factory import get_llm_provider
    provider = get_llm_provider()
    system = (
        "You rewrite technical research language into beginner-friendly explanations. "
        "You must not add facts, numbers, or claims that are not already present in the "
        "input text - only simplify the language and structure."
    )
    from agent.llm_utils import wrap_untrusted, UNTRUSTED_CONTENT_RULE
    system += UNTRUSTED_CONTENT_RULE
    prompt = f"Rewrite this in plain, simple language for a beginner, in 2-4 sentences:\n\n{wrap_untrusted(technical_text)}"
    response = provider.complete(system=system, prompt=prompt, max_tokens=400, temperature=0.3)
    return response.text.strip()


def get_latest_analysis(paper_id: int):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM analyses WHERE paper_id = ? ORDER BY created_at DESC LIMIT 1", (paper_id,))
        row = cur.fetchone()
        if not row:
            return None
        row = dict(row)
        row["sections"] = json.loads(row["sections_json"])
        return row
