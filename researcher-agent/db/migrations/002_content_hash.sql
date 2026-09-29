-- V1.1: lets re-ingestion reuse embeddings for identical chunk text (avoids duplicate embedding calls)
ALTER TABLE paper_chunks ADD COLUMN content_hash TEXT;
CREATE INDEX IF NOT EXISTS idx_chunks_hash ON paper_chunks(content_hash, embedding_provider, embedding_model);
