"""
ResearchAgent orchestrator.

Deliberately NOT an autonomous multi-agent loop: the task instructions call for
"deterministic workflows wherever possible" and warn against unnecessary
autonomous agents. This orchestrator is a thin, explicit dispatch layer - each
capability is a plain function, and the orchestrator's job is only to:
  1. validate that the requested workflow makes sense (e.g. enough papers selected)
  2. call the right capability function(s) in the right order
  3. return a uniform result/error shape to the Flask routes

Flask routes could call the capability modules directly; the orchestrator exists
so the full pipeline (e.g. "import -> analyze -> chat") has one documented,
testable entry point per the CORE USER FLOW.
"""
from typing import List, Optional, Dict
from ingestion.pipeline import upsert_paper_metadata, ingest_pdf_for_paper
from .capabilities import (
    paper_searcher, paper_analyzer, paper_chat, paper_comparator,
    gap_finder, question_generator, experiment_planner, citation_verifier,
)


class ResearchAgent:
    """Facade used by Flask routes. Each method corresponds to one node in the
    CORE USER FLOW (search -> import -> analyze -> chat -> compare -> gaps ->
    questions -> experiment plan)."""

    # --- PaperSearcher ---
    def search_papers(self, query: str, **kwargs):
        return paper_searcher.search(query, **kwargs)

    # --- Import / ingestion ---
    def import_paper_metadata(self, paper_dict: Dict) -> int:
        return upsert_paper_metadata(paper_dict)

    def ingest_pdf(self, paper_id: int, pdf_path: str) -> Dict:
        return ingest_pdf_for_paper(paper_id, pdf_path)

    # --- PaperAnalyzer ---
    def analyze_paper(self, paper_id: int, force: bool = False) -> Dict:
        return paper_analyzer.analyze_paper(paper_id, force=force)

    def explain_simply(self, paper_id: int, text: str) -> str:
        return paper_analyzer.explain_simply(paper_id, text)

    # --- PaperRetriever + Chat ---
    def chat(self, paper_id: int, question: str) -> Dict:
        return paper_chat.ask(paper_id, question)

    # --- PaperComparator ---
    def compare(self, paper_ids: List[int]) -> Dict:
        verification = citation_verifier.verify_paper_ids(paper_ids)
        missing = [pid for pid, v in verification.items() if not v["exists"]]
        if missing:
            raise ValueError(f"Cannot compare: paper id(s) not found in library: {missing}")
        return paper_comparator.compare_papers(paper_ids)

    # --- GapFinder ---
    def find_gaps(self, paper_ids: List[int], project_id: Optional[int] = None):
        return gap_finder.find_gaps(paper_ids, project_id)

    # --- QuestionGenerator ---
    def generate_questions(self, paper_ids: List[int], project_id: Optional[int] = None, gap_id: Optional[int] = None, count: int = 5):
        return question_generator.generate_questions(paper_ids, project_id, gap_id, count)

    # --- ExperimentPlanner ---
    def plan_experiment(self, research_question: Dict, project_id: Optional[int] = None):
        return experiment_planner.create_plan(research_question, project_id)


agent = ResearchAgent()
