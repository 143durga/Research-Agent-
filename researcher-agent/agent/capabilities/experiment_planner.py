"""
ExperimentPlanner: for a selected research question, generates a full proposed
experimental design. Plans are always stored/labeled as "proposed" - the
system never invents outcomes/results for a plan that hasn't been run.
"""
import json
from typing import Dict
from db.database import db_cursor
from agent.llm_utils import call_llm_json, NO_FABRICATION_RULE, wrap_untrusted

SYSTEM = NO_FABRICATION_RULE + (
    " You design a PROPOSED experiment plan for a research question. You must never "
    "state or imply any results, since no experiment has been run. Every field describes "
    "what SHOULD be done, not what was found."
)

PROMPT_TEMPLATE = """Design a proposed experiment plan for this research question:

{question_block}

Return a JSON object shaped as:
{{
  "hypothesis": "<a testable hypothesis>",
  "independent_variables": "<...>",
  "dependent_variables": "<...>",
  "dataset": "<proposed dataset(s), noting these are proposals not confirmed availability>",
  "baseline": "<baseline(s) to compare against>",
  "proposed_method": "<the method being proposed>",
  "experimental_groups": ["<group 1>", "<group 2>", "..."],
  "metrics": ["<metric 1>", "..."],
  "evaluation_procedure": "<step by step procedure>",
  "ablation_study": "<proposed ablations>",
  "reproducibility_requirements": "<what would need to be shared/documented for reproducibility>",
  "threats_to_validity": "<internal/external/construct validity threats to consider>"
}}
Do not include any "results" or "findings" field - none exist yet.
"""


ALLOWED_KEYS = ("hypothesis", "independent_variables", "dependent_variables", "dataset", "baseline", "proposed_method",
                "experimental_groups", "metrics", "evaluation_procedure", "ablation_study",
                "reproducibility_requirements", "threats_to_validity")
_RESULT_LIKE = ("result", "finding", "outcome", "accuracy_achieved", "observed", "conclusion")


def _txt(v):
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v)
    return str(v or "").strip()


def sanitize_plan(raw: Dict) -> Dict:
    """Keep only the planning fields. Any results-like key the model adds is dropped: no experiment
    has been run, so a plan can never carry outcomes."""
    raw = raw if isinstance(raw, dict) else {}
    plan = {k: raw.get(k) for k in ALLOWED_KEYS}
    plan["dropped_result_like_fields"] = sorted(k for k in raw if k not in ALLOWED_KEYS and any(w in k.lower() for w in _RESULT_LIKE))
    return plan


def create_plan(research_question: Dict, project_id: int = None) -> Dict:
    qtext = (
        f"Research Question: {research_question.get('question', '')}\n"
        f"Motivation: {research_question.get('motivation', '')}\n"
        f"Possible Method (proposed): {research_question.get('possible_method', '')}\n"
        f"Possible Dataset (proposed): {research_question.get('possible_dataset', '')}\n"
        f"Possible Metrics (proposed): {research_question.get('possible_metrics', '')}\n"
        f"Open Assumptions: {research_question.get('open_assumptions', '')}"
    )
    prompt = PROMPT_TEMPLATE.format(question_block=wrap_untrusted(qtext, "research_question"))
    raw, model, provider_name = call_llm_json(system=SYSTEM, prompt=prompt, max_tokens=2000)
    result = sanitize_plan(raw)
    if not _txt(result.get("hypothesis")):
        raise ValueError("The model did not return a hypothesis, so no plan was saved.")
    if project_id is None:
        project_id = research_question.get("project_id")

    with db_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO experiment_plans (research_question_id, project_id, hypothesis, independent_variables,
                        dependent_variables, dataset, baseline, proposed_method, experimental_groups_json,
                        metrics_json, evaluation_procedure, ablation_study, reproducibility_requirements,
                        threats_to_validity, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'proposed')""",
            (
                research_question.get("id"), project_id, _txt(result["hypothesis"]),
                _txt(result["independent_variables"]), _txt(result["dependent_variables"]),
                _txt(result["dataset"]), _txt(result["baseline"]), _txt(result["proposed_method"]),
                json.dumps(result["experimental_groups"] if isinstance(result["experimental_groups"], list) else [_txt(result["experimental_groups"])]),
                json.dumps(result["metrics"] if isinstance(result["metrics"], list) else [_txt(result["metrics"])]),
                _txt(result["evaluation_procedure"]), _txt(result["ablation_study"]),
                _txt(result["reproducibility_requirements"]), _txt(result["threats_to_validity"]),
            ),
        )
        result["id"] = cur.lastrowid
    result["research_question"] = research_question.get("question", "")
    result["project_id"] = project_id
    result["status"] = "proposed"
    return result


def list_plans(project_id: int = None):
    with db_cursor() as cur:
        if project_id:
            cur.execute("SELECT e.*, q.question AS research_question FROM experiment_plans e LEFT JOIN research_questions q ON q.id = e.research_question_id WHERE e.project_id = ? ORDER BY e.created_at DESC, e.id DESC", (project_id,))
        else:
            cur.execute("SELECT e.*, q.question AS research_question FROM experiment_plans e LEFT JOIN research_questions q ON q.id = e.research_question_id ORDER BY e.created_at DESC, e.id DESC")
        rows = []
        for r in cur.fetchall():
            row = dict(r)
            row["experimental_groups"] = json.loads(row["experimental_groups_json"] or "[]")
            row["metrics"] = json.loads(row["metrics_json"] or "[]")
            rows.append(row)
        return rows
