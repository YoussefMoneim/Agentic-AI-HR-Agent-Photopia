-- Migration 001: Enable Row Level Security on all tenant-scoped tables.
--
-- Mechanism: every protected table requires the DB session variable
--   app.current_tenant_id  to be set via  SET app.current_tenant_id = '<uuid>'
--   before any query.  If the variable is unset or NULL, the policy evaluates
--   to NULL (falsy) and returns 0 rows — fail-closed by design.
--
-- Apply to a running container:
--   docker cp backend/db/migrations/001_add_rls.sql fotopia-hr-agent-db-1:/tmp/
--   docker exec fotopia-hr-agent-db-1 psql -U fotopia -d fotopia_hr -f /tmp/001_add_rls.sql
--
-- Idempotent: DROP POLICY IF EXISTS before CREATE makes it safe to re-run.

-- ── users ────────────────────────────────────────────────────────────────────
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE users FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON users;
CREATE POLICY tenant_isolation ON users FOR ALL
    USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ── employees ────────────────────────────────────────────────────────────────
ALTER TABLE employees ENABLE ROW LEVEL SECURITY;
ALTER TABLE employees FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON employees;
CREATE POLICY tenant_isolation ON employees FOR ALL
    USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ── leave_types ──────────────────────────────────────────────────────────────
ALTER TABLE leave_types ENABLE ROW LEVEL SECURITY;
ALTER TABLE leave_types FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON leave_types;
CREATE POLICY tenant_isolation ON leave_types FOR ALL
    USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ── leave_balances ───────────────────────────────────────────────────────────
ALTER TABLE leave_balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE leave_balances FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON leave_balances;
CREATE POLICY tenant_isolation ON leave_balances FOR ALL
    USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ── leave_requests ───────────────────────────────────────────────────────────
ALTER TABLE leave_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE leave_requests FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON leave_requests;
CREATE POLICY tenant_isolation ON leave_requests FOR ALL
    USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ── leave_policies ───────────────────────────────────────────────────────────
ALTER TABLE leave_policies ENABLE ROW LEVEL SECURITY;
ALTER TABLE leave_policies FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON leave_policies;
CREATE POLICY tenant_isolation ON leave_policies FOR ALL
    USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ── workflow_instances ───────────────────────────────────────────────────────
ALTER TABLE workflow_instances ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflow_instances FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON workflow_instances;
CREATE POLICY tenant_isolation ON workflow_instances FOR ALL
    USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ── pending_actions ──────────────────────────────────────────────────────────
ALTER TABLE pending_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE pending_actions FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON pending_actions;
CREATE POLICY tenant_isolation ON pending_actions FOR ALL
    USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- ── audit_log ────────────────────────────────────────────────────────────────
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS tenant_isolation ON audit_log;
CREATE POLICY tenant_isolation ON audit_log FOR ALL
    USING      (tenant_id = current_setting('app.current_tenant_id', true)::uuid)
    WITH CHECK (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
