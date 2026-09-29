import io, json
from db.database import db_cursor
from agent.capabilities import citation_verifier
from providers.llm.base import LLMUnavailableError


def _upload(client, pdf, title):
    with open(pdf, "rb") as f:
        return client.post("/api/papers/upload", data={"file": (io.BytesIO(f.read()), "s.pdf"), "title": title},
                           content_type="multipart/form-data")


def test_upload_validation(client):
    r = client.post("/api/papers/upload", data={"file": (io.BytesIO(b"hello"), "x.txt")}, content_type="multipart/form-data")
    assert r.status_code == 415
    r = client.post("/api/papers/upload", data={"file": (io.BytesIO(b"not a pdf"), "x.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 415


def test_malformed_pdf_is_reported(client, tmp_path):
    bad = io.BytesIO(b"%PDF-1.4 garbage")
    r = client.post("/api/papers/upload", data={"file": (bad, "x.pdf")}, content_type="multipart/form-data")
    assert r.status_code == 422 and "error" in r.get_json()


def test_primary_flow(client, fake_llm, sample_pdf, monkeypatch):
    # Search (mocked source) -> save
    from providers.search.base import PaperResult
    monkeypatch.setattr("agent.capabilities.paper_searcher.search_all",
                        lambda **k: ([PaperResult(title="Flow Paper", source="arxiv", doi="10.1/flow", authors=["A"])], {"crossref": "down"}))
    r = client.post("/api/search", json={"query": "rag"}).get_json()
    assert r["count"] == 1 and r["source_errors"] == {"crossref": "down"}
    saved = client.post("/api/papers/import", json=r["results"][0]).get_json()["paper_id"]
    assert client.post("/api/papers/import", json=r["results"][0]).get_json()["paper_id"] == saved  # dedup

    # Import PDFs
    up = _upload(client, sample_pdf, "Uploaded Paper One").get_json()
    up2 = _upload(client, sample_pdf, "Uploaded Paper Two").get_json()
    pid, pid2 = up["paper_id"], up2["paper_id"]
    assert up["summary"]["chunks_created"] > 0
    with db_cursor() as cur:
        cur.execute("SELECT DISTINCT section_name FROM paper_sections WHERE paper_id=?", (pid,))
        names = {r["section_name"] for r in cur.fetchall()}
    assert {"abstract", "methodology", "limitations", "conclusion"} <= names

    # Analyze
    a = client.post(f"/api/papers/{pid}/analyze").get_json()
    assert len(a["sections"]) == 15
    assert {s["status"] for s in a["sections"]} <= {"EXPLICITLY_STATED", "INFERRED", "NOT_FOUND"}
    assert client.get(f"/paper/{pid}/analysis").status_code == 200

    # Chat (retrieval returns source metadata)
    c = client.post(f"/api/papers/{pid}/chat", json={"question": "What dataset limitations exist?"}).get_json()
    assert c["evidence"] and {"section", "page", "chunk_id"} <= set(c["evidence"][0])
    assert "[Paper:" in c["answer"]

    # Chat on paper without full text -> honest refusal, no LLM call
    c2 = client.post(f"/api/papers/{saved}/chat", json={"question": "anything"}).get_json()
    assert "could not find evidence" in c2["answer"].lower()

    # Compare
    assert client.post("/api/compare", json={"paper_ids": [pid]}).status_code == 400
    assert client.post("/api/compare", json={"paper_ids": [pid, 99999]}).status_code == 400
    cmp_ = client.post("/api/compare", json={"paper_ids": [pid, pid2]}).get_json()
    assert "comparison_table" in cmp_ and "best" not in json.dumps(cmp_).lower()

    # Gaps -> questions -> experiment plan
    gaps = client.post("/api/gaps/find", json={"paper_ids": [pid, pid2]}).get_json()["gaps"]
    assert gaps[0]["gap_type"] == "dataset"
    qs = client.post("/api/questions/generate", json={"paper_ids": [pid], "gap_id": gaps[0]["id"]}).get_json()["questions"]
    plan = client.post("/api/experiments/plan", json={"question_id": qs[0]["id"]}).get_json()
    assert plan["status"] == "proposed" and "results" not in plan

    for path in ["/", "/library", "/gaps", "/questions", "/experiments", f"/paper/{pid}", f"/paper/{pid}/chat"]:
        assert client.get(path).status_code == 200


def test_citation_verifier_flags_unknown_ids():
    v = citation_verifier.verify_paper_ids([1, 424242])
    assert v[424242]["exists"] is False


def test_llm_not_configured_gives_error(client, monkeypatch, sample_pdf):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    pid = _upload(client, sample_pdf, "No LLM Paper").get_json()["paper_id"]
    r = client.post(f"/api/papers/{pid}/analyze")
    assert r.status_code == 503 and "LLM" in r.get_json()["error"]


def test_api_key_gate(client):
    client.application.config["APP_API_KEY"] = "secret"
    try:
        assert client.post("/api/search", json={"query": "x"}).status_code == 401
    finally:
        client.application.config["APP_API_KEY"] = ""
