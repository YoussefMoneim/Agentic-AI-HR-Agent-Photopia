-- Demo document uploads for sensitivity scanning demonstration.
-- Content stored as text in DB (demo only — not for production file storage).
CREATE TABLE IF NOT EXISTS demo_documents (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id        UUID NOT NULL REFERENCES tenants(id),
    uploaded_by      TEXT NOT NULL,
    filename         TEXT NOT NULL,
    content_text     TEXT NOT NULL,
    file_size_bytes  INT,
    sensitivity_scan JSONB NOT NULL DEFAULT '{}',
    is_sensitive     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    is_demo          BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS demo_documents_tenant_idx
    ON demo_documents(tenant_id, created_at DESC);

ALTER TABLE demo_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE demo_documents FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON demo_documents;
CREATE POLICY tenant_isolation ON demo_documents FOR ALL
    USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON demo_documents TO fotopia_app;
