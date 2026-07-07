-- Stores SharePoint sync state per tenant
-- delta_link: Microsoft Graph delta token — tracks what changed since last sync
-- Losing this forces a full re-sync (safe but slow)

CREATE TABLE IF NOT EXISTS sharepoint_sync_state (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    site_url        TEXT NOT NULL,
    folder_path     TEXT NOT NULL,
    delta_link      TEXT,           -- NULL = never synced, triggers full sync
    last_synced_at  TIMESTAMPTZ,
    last_error      TEXT,           -- last error message if sync failed
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, site_url, folder_path)
);

CREATE INDEX IF NOT EXISTS idx_sharepoint_sync_tenant
    ON sharepoint_sync_state (tenant_id);

-- RLS: tenant isolation (same explicit USING+WITH CHECK pattern as
-- private_document_chunks in 012_pgvector.sql)
ALTER TABLE sharepoint_sync_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE sharepoint_sync_state FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON sharepoint_sync_state;
CREATE POLICY tenant_isolation ON sharepoint_sync_state FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
