"""
RAG chat over a single imported paper. Retrieves the most relevant chunks for
the user's question, then asks the LLM to answer using ONLY those chunks,
citing [Paper: Section X, page Y] and explicitly saying so when it cannot find
supporting evidence.
"""
import json
from typing import Dict
from db.database import db_cursor
from providers.llm.factory import get_llm_provider
from providers.llm.base import LLMUnavailableError
from .paper_retriever import retrieve, retrieval_mode, RetrievalUnavailableError
from agent.llm_utils import wrap_untrusted, UNTRUSTED_CONTENT_RULE

CHAT_SYSTEM = (
    "You answer questions about a specific academic paper using ONLY the excerpts "
    "provided below, which were retrieved from that paper. Never use outside "
    "knowledge about the topic, and never invent details, numbers, datasets, or "
    "findings that are not in the excerpts. If the excerpts do not contain the "
    "answer, you must reply exactly: \"I could not find evidence for this in the "
    "paper.\" Every factual sentence in your answer must end with a citation tag "
    "in the form [Paper: <section>, page <page>] referencing the excerpt it came from."
) + UNTRUSTED_CONTENT_RULE

NOT_FOUND_ANSWER = "I could not find evidence for this in the paper."


def ask(paper_id: int, question: str, top_k: int = 6) -> Dict:
    with db_cursor(commit=True) as cur:
        cur.execute("INSERT INTO chat_messages (paper_id, role, content) VALUES (?, 'user', ?)", (paper_id, question))
    mode = retrieval_mode()

    try:
        chunks = retrieve(question, [paper_id], top_k=top_k)
    except RetrievalUnavailableError as exc:
        answer = f"{NOT_FOUND_ANSWER} ({exc})"
        _save_assistant_message(paper_id, answer, [])
        return {"answer": answer, "evidence": [], "retrieval_mode": mode["mode"], "grounded": False}

    chunks = [c for c in chunks if c["score"] > 0]
    if not chunks:
        # nothing in the paper overlaps the question at all: do not spend an LLM call, do not guess
        _save_assistant_message(paper_id, NOT_FOUND_ANSWER, [])
        return {"answer": NOT_FOUND_ANSWER, "evidence": [], "retrieval_mode": mode["mode"], "grounded": False}

    excerpt_block = "\n\n".join(
        f"[Excerpt {i+1} | section={c['section'] or 'unknown'} | page={c['page'] or 'unknown'}]\n{c['content']}"
        for i, c in enumerate(chunks)
    )
    prompt = (f"Question: {question}\n\nRetrieved excerpts from the paper:\n"
              f"{wrap_untrusted(excerpt_block, f'paper_id={paper_id}')}\n\nAnswer the question.")

    grounded = True
    try:
        provider = get_llm_provider()
        response = provider.complete(system=CHAT_SYSTEM, prompt=prompt, max_tokens=900, temperature=0.1)
        answer = response.text.strip()
        if NOT_FOUND_ANSWER.lower() in answer.lower():
            grounded = False
        elif "[Paper:" not in answer:
            grounded = False
            answer += "\n\n(Warning: this answer did not include citations to the paper, so treat it as unverified.)"
    except LLMUnavailableError as exc:
        answer = f"I could not generate an answer: {exc}"
        grounded = False

    evidence = [{"chunk_id": c["chunk_id"], "section": c["section"], "page": c["page"], "snippet": c["content"][:280], "score": c["score"]} for c in chunks]
    _save_assistant_message(paper_id, answer, evidence)
    return {"answer": answer, "evidence": evidence, "retrieval_mode": mode["mode"], "grounded": grounded}


def _save_assistant_message(paper_id: int, answer: str, evidence: list):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO chat_messages (paper_id, role, content, evidence_json) VALUES (?, 'assistant', ?, ?)",
            (paper_id, answer, json.dumps(evidence)),
        )


def get_history(paper_id: int):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM chat_messages WHERE paper_id = ? ORDER BY created_at ASC", (paper_id,))
        rows = []
        for r in cur.fetchall():
            row = dict(r)
            row["evidence"] = json.loads(row["evidence_json"]) if row.get("evidence_json") else []
            rows.append(row)
        return rows
