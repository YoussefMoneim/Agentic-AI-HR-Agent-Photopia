-- Onboarding orchestrator state (Week 1 MVP — 5-question interview).
-- Tracks which step a chat session's onboarding interview is on, and the
-- answers collected so far, so the flow survives a backend restart between
-- rehearsal and the live demo. Fixed question templates driven by plain
-- Python (backend/agent/onboarding.py), never the LLM tool-use loop —
-- deliberately separate from _sessions (in-memory, raw LLM message blocks).

CREATE TABLE IF NOT EXISTS onboarding_sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id           UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    session_id          TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'in_progress',
        -- in_progress | completed | abandoned
    current_step        INTEGER NOT NULL DEFAULT 1,
        -- 1..5
    answers             JSONB NOT NULL DEFAULT '{}',
    started_by_user_id  TEXT NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at        TIMESTAMPTZ,
    UNIQUE (tenant_id, session_id)
);

CREATE INDEX IF NOT EXISTS idx_onboarding_sessions_tenant_session
    ON onboarding_sessions (tenant_id, session_id);

-- RLS: tenant isolation (same explicit USING+WITH CHECK pattern as
-- email_conversation_sessions in 021_email_conversation_sessions.sql)
ALTER TABLE onboarding_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE onboarding_sessions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON onboarding_sessions;
CREATE POLICY tenant_isolation ON onboarding_sessions FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON onboarding_sessions TO fotopia_app;
