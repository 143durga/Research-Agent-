# JSON API (all under /api; send `X-API-Key` if APP_API_KEY is set)
| Method & path | Body | Notes |
|---|---|---|
| POST /search | query, sources[], year, author, open_access_only | returns results + per-source errors |
| POST /papers/import | PaperResult fields | dedups by DOI/external id/title |
| POST /papers/upload | multipart file, title | PDF only |
| POST /papers/{id}/import-pdf-from-url | url | downloads + ingests |
| POST /papers/{id}/analyze | - | 15 sections with claim/evidence/status |
| POST /papers/{id}/explain-simply | text | plain-language rewrite |
| POST /papers/{id}/chat | question | grounded answer + evidence chunks |
| POST /compare | paper_ids (2-10) | table + synthesis |
| POST /gaps/find | paper_ids, project_id? | potential gaps |
| POST /questions/generate | paper_ids, gap_id?, project_id?, count? | |
| POST /experiments/plan | question_id, project_id? | proposed plan |
| POST /papers/{id}/notes, /highlights, /tags | content / quote / name | |
| POST /projects, /projects/{id}/papers, /projects/{id}/notes | | |
| POST /literature-review | project_id, theme, paper_ids, ... | |
Errors: `{"error": "..."}` with 400/401/415/422/429/503.
