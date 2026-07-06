-- Migrate embedding columns from vector(1536) to vector(1024)
-- to support voyage-3-multilingual (Anthropic-recommended, Arabic+English).
--
-- Safe: both tables confirmed empty before this migration.
-- HNSW indexes must be dropped before altering column type, then recreated.
-- The index on private_document_chunks will be recreated AFTER data is loaded
-- (HNSW requires data to build properly) — see seed script.

-- public_knowledge_chunks
DROP INDEX IF EXISTS public_knowledge_chunks_embedding_idx;
ALTER TABLE public_knowledge_chunks
    ALTER COLUMN embedding TYPE vector(1024);

-- private_document_chunks
DROP INDEX IF EXISTS private_document_chunks_embedding_idx;
ALTER TABLE private_document_chunks
    ALTER COLUMN embedding TYPE vector(1024);

-- Recreate HNSW index on public table (empty, fast)
CREATE INDEX IF NOT EXISTS public_knowledge_chunks_embedding_idx
    ON public_knowledge_chunks
    USING hnsw (embedding vector_cosine_ops);

-- NOTE: private_document_chunks HNSW index is NOT recreated here.
-- It will be created by the seed script after data is loaded,
-- because HNSW builds better with data present.
-- Full-text search (GIN on content_tsv) remains fully operational
-- for all queries until embeddings are populated.
