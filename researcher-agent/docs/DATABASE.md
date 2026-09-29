# Database (SQLite)
Tables: users, papers (UNIQUE doi), authors, paper_authors, paper_sections, paper_chunks (chunk text + `embedding_json`, provider/model = the EmbeddingReference), projects, project_papers, notes, highlights, tags, paper_tags, analyses, research_gaps, research_questions, experiment_plans, citations, search_history, chat_messages, literature_reviews, schema_migrations.
Dedup order: DOI, external id (arXiv/S2 id), case-insensitive title. Add migrations as new numbered `.sql` files.
