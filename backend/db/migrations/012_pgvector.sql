-- Enable pgvector extension for semantic search
CREATE EXTENSION IF NOT EXISTS vector;

-- Tier 1: public knowledge (labour law, public references — no tenant, no ACL)
CREATE TABLE IF NOT EXISTS public_knowledge_chunks (
    id          BIGSERIAL PRIMARY KEY,
    source      TEXT NOT NULL,
    chunk_index INT NOT NULL,
    content     TEXT NOT NULL,
    embedding   vector(1536),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS public_knowledge_chunks_embedding_idx
    ON public_knowledge_chunks USING hnsw (embedding vector_cosine_ops);

-- Tier 2/3: private, tenant-scoped, ACL-enforced
-- classified_at is nullable: NULL = quarantine (never returned by search);
-- ingestion script sets to now() at classification time.
CREATE TABLE IF NOT EXISTS private_document_chunks (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       UUID NOT NULL REFERENCES tenants(id),
    document_id     TEXT NOT NULL,       -- logical identifier, e.g. "03_leave_policy"
    chunk_index     INT NOT NULL,
    content         TEXT NOT NULL,
    embedding       vector(1536),        -- reserved for future semantic search
    sensitivity     TEXT NOT NULL DEFAULT 'public_tenant',
    allowed_roles   TEXT[] NOT NULL DEFAULT '{}',
    source_file     TEXT NOT NULL,       -- path relative to policies/ dir
    classified_at   TIMESTAMPTZ,         -- NULL = quarantine; search filters IS NOT NULL
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    content_tsv     tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);
CREATE INDEX IF NOT EXISTS private_document_chunks_embedding_idx
    ON private_document_chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS private_document_chunks_tenant_idx
    ON private_document_chunks(tenant_id, sensitivity);
CREATE INDEX IF NOT EXISTS private_document_chunks_tsv_idx
    ON private_document_chunks USING GIN (content_tsv);

-- RLS: tenant isolation
ALTER TABLE private_document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE private_document_chunks FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON private_document_chunks;
CREATE POLICY tenant_isolation ON private_document_chunks FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
