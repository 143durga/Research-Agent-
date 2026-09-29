# Researcher Agent

A local web app for finding, importing, analyzing, comparing and questioning academic papers, with evidence and source tracking on every claim. Built for AI + Cloud + Security research but domain-independent.

Stack: Python 3.10+, Flask, SQLite, pdfplumber/pypdf, numpy + scikit-learn, plain HTML/CSS/JS (no build step).

## 1. Requirements
Python 3.10+ and internet access (for paper sources and your LLM provider).

## 2. Installation
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # then edit
```

## 3. Environment variables
See `.env.example`. Key ones: `LLM_PROVIDER` (`anthropic`|`openai`), `LLM_API_KEY`, `LLM_MODEL`, `EMBEDDING_PROVIDER` (`openai`|`local_hash`), `EMBEDDING_API_KEY`, `EMBEDDING_MODEL`, `APP_API_KEY` (optional lock for the JSON API). Keys are read only by the backend.

Without an LLM key: search, library, upload/ingestion and reading work; analysis, chat, comparison, gaps, questions and experiment planning return a clear error (never fake output). Without an embedding key the app falls back to an offline **lexical** hashing embedder (lower retrieval quality; labeled in Settings).

## 4. Database setup
Automatic. Migrations in `db/migrations/*.sql` are applied at startup into `instance/researcher_agent.db` (override with `DATABASE_PATH`).

## 5. Run
```bash
python app.py     # http://localhost:5000
```

## 6. Tests
```bash
pytest -q
# if pytest is unavailable: python tests/mini_runner.py
```
Tests mock the LLM and paper sources, and generate a real PDF to exercise extraction, sectioning, chunking, embedding and retrieval.

## 7. Architecture
See `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/DATABASE.md`.

## 8. Add another LLM provider
Create `providers/llm/my_provider.py` subclassing `LLMProvider` (implement `complete`, raise `LLMUnavailableError` on failure), register it in `_PROVIDERS` in `providers/llm/factory.py`, set `LLM_PROVIDER=my_provider`.

## 9. Add another paper source
Create `providers/search/my_source.py` subclassing `PaperSearchProvider` returning `PaperResult`s (leave unknown fields empty), register it in `ALL_PROVIDERS` in `providers/search/aggregator.py`, and add a checkbox in `templates/search.html`.

## V1.1 validation status (read this before assuming anything was tested live)
This sandbox has no outbound internet access and no configured API keys, so V1.1 could not make a single
real call to Semantic Scholar, Crossref, arXiv, an LLM, or an embedding API. All guardrail and workflow
logic was instead validated with **53 automated tests** (mocked network/LLM boundaries) plus a **real
headless-Chromium click-through** of every page. See the validation report delivered with this build for
exactly what was and was not exercised, and run the app yourself with real keys/network to complete
real-service validation.

## Known limitations
- Single local user; no login UI (optional API-key gate only).
- Section detection is heuristic; papers with unusual headings land in an "other" bucket.
- Vector search is in-process cosine similarity over SQLite rows (fine for personal libraries, not thousands of papers).
- Project pages show gaps/questions created with a project id via the API; the Gap Finder/Questions pages do not yet have a project selector.
- Scanned PDFs without a text layer are rejected (no OCR).
