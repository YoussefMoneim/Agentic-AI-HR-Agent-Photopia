-- Email agent thread context (short-term memory).
-- Stores structured turn history per email thread so follow-up emails
-- (e.g. "can I take 5 days of that?") resolve context from prior turns.
--
-- Turn history is structured (intent + extracted_params + reply summary),
-- not raw LLM chat — it feeds services/email_agent.py::_classify_intent(),
-- and never generates reply content directly. That file's invariant
-- ("never LLM-generated body text") is unchanged by this table.

CREATE TABLE IF NOT EXISTS email_conversation_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    thread_id       TEXT NOT NULL,
    employee_email  TEXT NOT NULL,
    messages        JSONB NOT NULL DEFAULT '[]',
    last_message_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, thread_id)
);

CREATE INDEX IF NOT EXISTS idx_email_sessions_tenant_thread
    ON email_conversation_sessions (tenant_id, thread_id);

CREATE INDEX IF NOT EXISTS idx_email_sessions_employee
    ON email_conversation_sessions (tenant_id, employee_email, last_message_at DESC);

-- RLS: tenant isolation (same explicit USING+WITH CHECK pattern as
-- private_document_chunks in 012_pgvector.sql / sharepoint_sync_state in 020)
ALTER TABLE email_conversation_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_conversation_sessions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON email_conversation_sessions;
CREATE POLICY tenant_isolation ON email_conversation_sessions FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON email_conversation_sessions TO fotopia_app;
