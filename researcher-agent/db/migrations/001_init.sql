-- Researcher Agent initial schema
-- SQLite. Foreign keys enforced at connection level (see database.py).

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS papers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doi TEXT UNIQUE,                      -- used for de-duplication when present
    external_id TEXT,                     -- e.g. arXiv id / Semantic Scholar paperId, used for dedup when no DOI
    title TEXT NOT NULL,
    abstract TEXT,
    year INTEGER,
    venue TEXT,
    source TEXT,                          -- semantic_scholar | crossref | arxiv | upload | url
    source_url TEXT,
    pdf_url TEXT,
    pdf_path TEXT,                        -- local path once downloaded/uploaded
    citation_count INTEGER,
    open_access INTEGER DEFAULT 0,
    keywords TEXT,                        -- JSON array, when available
    raw_metadata_json TEXT,               -- full raw response from the source provider, for traceability
    full_text_extracted INTEGER DEFAULT 0,
    ingestion_status TEXT DEFAULT 'metadata_only', -- metadata_only | extracting | chunked | failed
    ingestion_error TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_papers_title ON papers(title);
CREATE INDEX IF NOT EXISTS idx_papers_external_id ON papers(external_id);

CREATE TABLE IF NOT EXISTS authors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS paper_authors (
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    author_id INTEGER NOT NULL REFERENCES authors(id) ON DELETE CASCADE,
    position INTEGER DEFAULT 0,
    PRIMARY KEY (paper_id, author_id)
);

CREATE TABLE IF NOT EXISTS paper_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    section_name TEXT NOT NULL,     -- normalized: abstract, introduction, methodology, dataset, experiments, results, discussion, limitations, conclusion, references, other
    content TEXT NOT NULL,
    page_start INTEGER,
    page_end INTEGER,
    order_index INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sections_paper ON paper_sections(paper_id);

CREATE TABLE IF NOT EXISTS paper_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    section_name TEXT,
    page INTEGER,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER,
    embedding_json TEXT,            -- JSON array of floats (the "EmbeddingReference")
    embedding_provider TEXT,
    embedding_model TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chunks_paper ON paper_chunks(paper_id);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    objective TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_papers (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (project_id, paper_id)
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS highlights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    quote TEXT NOT NULL,
    section TEXT,
    page INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS paper_tags (
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (paper_id, tag_id)
);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    sections_json TEXT NOT NULL,   -- structured list of {section, claim, evidence, evidence_location, status}
    model_used TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_analyses_paper ON analyses(paper_id);

CREATE TABLE IF NOT EXISTS research_gaps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    gap_type TEXT NOT NULL,   -- dataset|methodological|evaluation|generalization|security|reproducibility|deployment|scalability|theoretical|application
    description TEXT NOT NULL,
    supporting_papers_json TEXT NOT NULL,  -- [paper_id, ...]
    evidence_json TEXT NOT NULL,           -- [{paper_id, quote, section}]
    rationale TEXT NOT NULL,
    potential_question TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS research_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    question TEXT NOT NULL,
    motivation TEXT,
    supporting_papers_json TEXT,
    evidence_json TEXT,
    possible_method TEXT,
    possible_dataset TEXT,
    possible_metrics TEXT,
    difficulty TEXT,
    open_assumptions TEXT,
    source_gap_id INTEGER REFERENCES research_gaps(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS experiment_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    research_question_id INTEGER REFERENCES research_questions(id) ON DELETE CASCADE,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    hypothesis TEXT NOT NULL,
    independent_variables TEXT,
    dependent_variables TEXT,
    dataset TEXT,
    baseline TEXT,
    proposed_method TEXT,
    experimental_groups_json TEXT,
    metrics_json TEXT,
    evaluation_procedure TEXT,
    ablation_study TEXT,
    reproducibility_requirements TEXT,
    threats_to_validity TEXT,
    status TEXT DEFAULT 'proposed',   -- always 'proposed' -- never marked completed with fabricated results
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER REFERENCES papers(id) ON DELETE CASCADE,
    source_type TEXT,      -- semantic_scholar|crossref|arxiv|upload|url
    source_url TEXT,
    title TEXT,
    authors TEXT,
    publication TEXT,
    year INTEGER,
    doi TEXT,
    section TEXT,
    page INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS search_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    filters_json TEXT,
    sources_json TEXT,
    result_count INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id INTEGER NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
    role TEXT NOT NULL,          -- user | assistant
    content TEXT NOT NULL,
    evidence_json TEXT,          -- [{chunk_id, section, page, snippet}]
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_chat_paper ON chat_messages(paper_id);

CREATE TABLE IF NOT EXISTS literature_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    theme TEXT NOT NULL,
    papers_json TEXT NOT NULL,
    agreement TEXT,
    disagreement TEXT,
    evolution TEXT,
    limitations TEXT,
    open_questions TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);
