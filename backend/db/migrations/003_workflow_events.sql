-- Migration 003: workflow_events table
-- Append-only audit trail for workflow state transitions.
-- Separate from audit_log (which logs tool calls) — this logs state machine transitions.
-- Idempotent: safe to run multiple times.

CREATE TABLE IF NOT EXISTS workflow_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    workflow_instance_id UUID NOT NULL REFERENCES workflow_instances(id),
    event_type TEXT NOT NULL,
        -- 'submitted' | 'pending_approval_sent' | 'manager_approved'
        -- | 'manager_rejected' | 'top_of_hierarchy_approved'
        -- | 'cancelled' | 'completed' | 'timed_out'
    actor_employee_id UUID REFERENCES employees(id),
    actor_user_id TEXT,
    data JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS workflow_events_instance_idx
    ON workflow_events(tenant_id, workflow_instance_id);
CREATE INDEX IF NOT EXISTS workflow_events_created_idx
    ON workflow_events(tenant_id, created_at DESC);

ALTER TABLE workflow_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_events FORCE  ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'workflow_events' AND policyname = 'tenant_isolation'
    ) THEN
        CREATE POLICY tenant_isolation ON workflow_events FOR ALL
            USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
    END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON workflow_events TO fotopia_app;
