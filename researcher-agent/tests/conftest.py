import os, re, tempfile, json
_tmp = tempfile.mkdtemp()
os.environ["DATABASE_PATH"] = os.path.join(_tmp, "test.db")
os.environ["UPLOAD_FOLDER"] = os.path.join(_tmp, "uploads")
os.environ["EMBEDDING_PROVIDER"] = "local_hash"
os.environ["RATE_LIMIT_PER_MINUTE"] = "1000"

import pytest
from providers.llm.base import LLMProvider, LLMResponse


class FakeLLM(LLMProvider):
    name = "fake"
    model = "fake-1"

    def __init__(self):
        self.calls = []  # (system, prompt) for every request, so tests can assert what was sent

    def complete(self, system, prompt, max_tokens=1500, temperature=0.2):
        self.calls.append((system, prompt))
        if "Analyze the following academic paper" in prompt:
            from agent.capabilities.paper_analyzer import ANALYSIS_SECTIONS
            out = [{"section": s, "claim": f"claim for {s}", "evidence": "", "evidence_location": "",
                    "status": "NOT_FOUND"} for s in ANALYSIS_SECTIONS]
            out[0].update(evidence="We study prompt injection.", evidence_location="introduction", status="EXPLICITLY_STATED")
            text = json.dumps(out)
        elif "Compare the following" in prompt:
            ids = [int(x) for x in re.findall(r"=== PAPER ID (\d+) ===", prompt)]
            dims = ["problem","objective","methodology","model","dataset","evaluation_metrics","results","limitations","contributions","future_work"]
            row = lambda pid: {"paper_id": pid, "title": "WRONG-TITLE-FROM-MODEL", **{d: {"value": "x", "status": "EXPLICITLY_STATED", "evidence": "We study prompt injection attacks"} for d in dims}}
            text = json.dumps({"comparison_table": [row(i) for i in ids], "common_themes": ["t"], "differences": ["d"],
                               "conflicting_findings": [], "different_datasets": [], "different_evaluation_approaches": [], "research_opportunities": ["r"]})
        elif "candidate research gaps" in prompt:
            ids = [int(x) for x in re.findall(r"=== PAPER ID (\d+):", prompt)]
            text = json.dumps([{"gap_type": "dataset", "description": "Potential research gap based on the limitations/future-work statements found in these papers: small data",
                                "supporting_paper_ids": ids[:1], "evidence": [{"paper_id": ids[0], "quote_or_paraphrase": "Our dataset is small and covers only English documents.",
                                "section": "limitations", "statement_type": "AUTHOR_STATED_LIMITATION"}],
                                "why_unresolved": "stated as future work", "potential_research_question": "Can larger data help?"}])
        elif "specific, actionable" in prompt:
            ids = [int(x) for x in re.findall(r"=== PAPER ID (\d+):", prompt)]
            text = json.dumps([{"question": "Does sanitizing retrieved passages reduce prompt injection success across languages beyond English?", "motivation": "m",
                                "supporting_paper_ids": ids[:1], "evidence": "Our dataset is small and covers only English documents.",
                                "possible_method": "pm", "possible_dataset": "pd", "possible_metrics": "acc", "difficulty": "medium", "open_assumptions": "a"}])
        elif "Design a proposed experiment plan" in prompt:
            text = json.dumps({"hypothesis": "H", "independent_variables": "iv", "dependent_variables": "dv", "dataset": "d", "baseline": "b",
                               "proposed_method": "pm", "experimental_groups": ["g1"], "metrics": ["m1"], "evaluation_procedure": "ep",
                               "ablation_study": "ab", "reproducibility_requirements": "rr", "threats_to_validity": "tv"})
        else:
            text = "The paper studies prompt injection. [Paper: introduction, page 1]"
        return LLMResponse(text=text, model=self.model, provider=self.name)


@pytest.fixture(scope="session", autouse=True)
def _db():
    from db.database import run_migrations
    run_migrations(verbose=False)


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    import agent.llm_utils as lu
    import agent.capabilities.paper_chat as pc
    monkeypatch.setattr(lu, "get_llm_provider", lambda: fake)
    monkeypatch.setattr(pc, "get_llm_provider", lambda: fake)
    monkeypatch.setattr("providers.llm.factory.get_llm_provider", lambda: fake)
    return fake


@pytest.fixture
def sample_pdf(tmp_path):
    from reportlab.pdfgen import canvas
    path = str(tmp_path / "sample.pdf")
    c = canvas.Canvas(path)
    def page(lines):
        y = 800
        for l in lines:
            c.drawString(50, y, l); y -= 18
        c.showPage()
    page(["Abstract", "We study prompt injection attacks against retrieval augmented generation systems.",
          "Introduction", "Prompt injection is a growing security concern for cloud deployed language models."])
    page(["Methodology", "We build a benchmark of adversarial documents and evaluate three retrieval pipelines.",
          "Results", "Detection accuracy improves when retrieved passages are sanitized before generation."])
    page(["Limitations", "Our dataset is small and covers only English documents.",
          "Conclusion", "Future work includes multilingual evaluation."])
    c.save()
    return path


@pytest.fixture
def client():
    from app import app
    app.config["TESTING"] = True
    return app.test_client()
