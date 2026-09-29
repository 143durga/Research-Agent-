# Architecture
Browser -> Flask (`routes/pages.py` HTML, `routes/api.py` JSON) -> `agent/orchestrator.py` -> capability modules -> providers + SQLite.

- **Providers** (`providers/`): `LLMProvider`, `EmbeddingProvider`, `PaperSearchProvider`; factories choose by env var.
- **Ingestion** (`ingestion/`): PDF -> pages -> heuristic sections -> overlapping chunks (section+page kept) -> embeddings -> `paper_chunks`.
- **Capabilities** (`agent/capabilities/`): paper_searcher, paper_analyzer, paper_retriever (+paper_chat), paper_comparator, gap_finder, question_generator, experiment_planner, citation_verifier. Research planning is the deterministic orchestrator itself; no autonomous agent loops.
- **Anti-fabrication**: all LLM extraction shares `NO_FABRICATION_RULE` (EXPLICITLY_STATED / INFERRED / NOT_FOUND, evidence required). Chat answers only from retrieved chunks and cites `[Paper: section, page]`. Missing metadata stays NULL. `CitationVerifier` rejects paper ids not in the DB. Experiment plans are stored as `proposed`.
- **Security**: backend-only keys, upload extension + `%PDF` magic-byte check, size limit, `secure_filename`, in-memory rate limit, optional `X-API-Key`, secret-redacting log filter. Uploaded files are never executed.
